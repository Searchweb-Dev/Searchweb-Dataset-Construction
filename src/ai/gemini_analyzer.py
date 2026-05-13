"""Gemini API를 사용한 웹사이트 분석기 (url_context + Structured Output 방식)."""

import logging
import time
from typing import Any, Optional

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from src.core.config import get_gemini_model
from src.ai.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT, BATCH_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)

# Structured Output 응답 스키마 — 프롬프트 예시 JSON 대체
_SITE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_ai_tool": {"type": "boolean"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level_1": {"type": "string"},
                    "level_2": {"type": "string"},
                    "level_3": {"type": "string"},
                    "is_primary": {"type": "boolean"},
                },
                "required": ["level_1", "level_2", "is_primary"],
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "scores": {
            "type": "object",
            "properties": {
                "utility": {"type": "integer"},
                "trust": {"type": "integer"},
                "originality": {"type": "integer"},
            },
            "required": ["utility", "trust", "originality"],
        },
        "confidence": {"type": "number"},
    },
    "required": ["is_ai_tool", "title", "description", "categories", "tags", "scores", "confidence"],
}

_BATCH_SCHEMA = {
    "type": "array",
    "items": _SITE_SCHEMA,
}


def _is_retryable(exc: BaseException) -> bool:
    """503 / 429 계열 오류인지 판별한다."""
    msg = str(exc)
    return "503" in msg or "429" in msg or "UNAVAILABLE" in msg or "RESOURCE_EXHAUSTED" in msg


class GeminiAnalyzer:
    """Gemini url_context 툴 + Structured Output을 사용한 웹사이트 분석기."""

    def __init__(self, api_key: Optional[str] = None):
        """Gemini 클라이언트 초기화."""
        self.client = genai.Client(api_key=api_key)
        self.model = get_gemini_model()

    def analyze_website(self, url: str) -> dict[str, Any]:
        """단건 URL 분석."""
        start_time = time.time()
        response = self._generate_single(url)
        self._check_finish_reason(url, response)

        result = self._parse_single(response)
        result["analyzer"] = "gemini"

        elapsed = time.time() - start_time
        logger.info(f"Gemini 단건 분석 완료: {elapsed:.2f}초")
        return result

    def analyze_websites_batch(self, urls: list[str]) -> list[dict[str, Any]]:
        """URL 목록을 LLM 호출 1회로 배치 분석한다.

        Args:
            urls: 분석할 URL 목록 (1~5개).

        Returns:
            입력 순서와 동일한 순서의 분석 결과 리스트.
            개별 URL 파싱 실패 시 해당 항목을 기본값으로 채운다.
        """
        if not urls:
            return []
        if len(urls) == 1:
            return [self.analyze_website(urls[0])]

        start_time = time.time()
        url_list = "\n".join(f"{i+1}. {url}" for i, url in enumerate(urls))
        prompt = BATCH_ANALYSIS_PROMPT.format(url_list=url_list)

        response = self._generate_batch(prompt)
        self._check_finish_reason(",".join(urls), response)

        results = self._parse_batch(response, urls)

        elapsed = time.time() - start_time
        logger.info(f"Gemini 배치 분석 완료: {len(urls)}개 URL, {elapsed:.2f}초")
        return results

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _generate_single(self, url: str) -> Any:
        """단건 분석 — 503/429 시 지수 백오프 재시도."""
        return self.client.models.generate_content(
            model=self.model,
            contents=ANALYSIS_PROMPT.format(url=url),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[types.Tool(url_context=types.UrlContext())],
                response_mime_type="application/json",
                response_schema=_SITE_SCHEMA,
            ),
        )

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _generate_batch(self, prompt: str) -> Any:
        """배치 분석 — 503/429 시 지수 백오프 재시도."""
        return self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[types.Tool(url_context=types.UrlContext())],
                response_mime_type="application/json",
                response_schema=_BATCH_SCHEMA,
            ),
        )

    def _parse_single(self, response: Any) -> dict[str, Any]:
        """단건 응답 파싱 — Structured Output이므로 직접 파싱."""
        import json
        try:
            if response.text:
                return json.loads(response.text)
        except (json.JSONDecodeError, AttributeError):
            pass
        logger.warning("단건 응답 파싱 실패, 기본값 반환")
        return self._default_response()

    def _parse_batch(self, response: Any, urls: list[str]) -> list[dict[str, Any]]:
        """배치 응답 파싱. 길이 불일치 또는 항목 오류 시 기본값으로 보완."""
        import json
        results: list[dict[str, Any]] = []
        try:
            if response.text:
                parsed = json.loads(response.text)
                if isinstance(parsed, list):
                    results = parsed
        except (json.JSONDecodeError, AttributeError):
            logger.warning("배치 응답 파싱 실패, 전체 기본값 반환")

        # URL 수와 결과 수가 맞지 않으면 기본값으로 패딩
        while len(results) < len(urls):
            results.append(self._default_response())

        for i, result in enumerate(results[:len(urls)]):
            if not isinstance(result, dict) or "is_ai_tool" not in result:
                results[i] = self._default_response()
            results[i]["analyzer"] = "gemini"

        return results[:len(urls)]

    def _check_finish_reason(self, url: str, response: Any) -> None:
        """비정상 종료 여부 로깅."""
        try:
            candidate = response.candidates[0] if response.candidates else None
            if candidate is None:
                logger.warning(f"[{url}] Gemini 응답에 candidate가 없습니다.")
                return
            finish_reason = candidate.finish_reason
            reason_name = finish_reason.name if finish_reason else "UNKNOWN"
            if reason_name == "MAX_TOKENS":
                logger.warning(f"[{url}] 응답이 max_output_tokens 한도에 도달해 잘렸습니다.")
            elif reason_name not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                logger.warning(f"[{url}] 비정상 종료: finish_reason={reason_name}")
        except Exception as e:
            logger.debug(f"[{url}] finish_reason 확인 중 오류: {e}")

    def _default_response(self) -> dict[str, Any]:
        """파싱 실패 시 기본 응답 구조."""
        return {
            "is_ai_tool": False,
            "title": "Unknown",
            "description": "분석 실패",
            "categories": [],
            "tags": [],
            "scores": {"utility": 0, "trust": 0, "originality": 0},
            "confidence": 0,
        }
