"""Gemini API를 사용한 웹사이트 분석기 (url_context + Structured Output 방식)."""

import json
import logging
import time
from typing import Any

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from src.core.config import get_gemini_model
from src.core.error_policy import ApiErrorKind, classify_api_error
from src.core.exceptions import (
    SiteUnreachableError,
    RateLimitError,
    ApiServerUnavailableError,
    ApiServerInternalError,
    ApiUnauthenticatedError,
    ApiPermissionDeniedError,
    ApiTimeoutError,
    ApiPreconditionError,
    ApiNotFoundError,
)
from src.ai.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT, BATCH_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)

_WEIGHT_UTILITY = 0.4
_WEIGHT_TRUST = 0.3
_WEIGHT_ORIGINALITY = 0.3
_HARD_PASS_CONFIDENCE_THRESHOLD = 0.8
_REVIEW_CONFIDENCE_THRESHOLD = 0.7
_REVIEW_SCORE_THRESHOLD = 60.0

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
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": _SITE_SCHEMA,
        }
    },
    "required": ["results"],
}


def _is_retryable(exc: BaseException) -> bool:
    """재시도 가능한 오류인지 판별한다."""
    from src.core.error_policy import get_policy
    return get_policy(exc).retryable


def _raise_typed_error(exc: BaseException, url: str) -> None:
    """에러 종류에 따라 적절한 도메인 예외를 발생시킨다."""
    kind = classify_api_error(exc)
    _KIND_TO_EXC = {
        ApiErrorKind.UNREACHABLE:       (SiteUnreachableError,      f"사이트 접근 불가 (400): {url}"),
        ApiErrorKind.PRECONDITION_FAILED: (ApiPreconditionError,    f"사전 조건 미충족 (400): {url}"),
        ApiErrorKind.NOT_FOUND:         (ApiNotFoundError,          f"리소스 없음 (404): {url}"),
        ApiErrorKind.AUTH_ERROR:        (ApiUnauthenticatedError,   f"API 인증 실패 (401): {url}"),
        ApiErrorKind.PERMISSION_DENIED: (ApiPermissionDeniedError,  f"API 권한 없음 (403): {url}"),
        ApiErrorKind.RATE_LIMITED:      (RateLimitError,            f"API 할당량 초과 (429): {url}"),
        ApiErrorKind.TIMEOUT:           (ApiTimeoutError,           f"API 타임아웃 (504): {url}"),
        ApiErrorKind.SERVER_UNAVAILABLE: (ApiServerUnavailableError, f"API 서버 일시 불가 (503): {url}"),
        ApiErrorKind.SERVER_INTERNAL:   (ApiServerInternalError,    f"API 서버 내부 오류 (500): {url}"),
    }
    if kind in _KIND_TO_EXC:
        exc_cls, msg = _KIND_TO_EXC[kind]
        raise exc_cls(msg) from exc
    raise exc


class GeminiAnalyzer:
    """Gemini url_context 툴 + Structured Output을 사용한 웹사이트 분석기."""

    def __init__(self, api_key: str | None = None):
        """Gemini 클라이언트 초기화."""
        self.client = genai.Client(api_key=api_key)
        self.model = get_gemini_model()

    def analyze_website(self, url: str) -> dict[str, Any]:
        """단건 URL 분석."""
        logger.info("[Gemini] 단건 분석 시작: %s", url)
        start_time = time.time()
        try:
            response = self._generate_single(url)
        except (
            SiteUnreachableError, ApiPreconditionError, ApiNotFoundError,
            ApiUnauthenticatedError, ApiPermissionDeniedError,
            RateLimitError, ApiTimeoutError,
            ApiServerUnavailableError, ApiServerInternalError,
        ):
            raise
        except Exception as exc:
            _raise_typed_error(exc, url)
        self._check_finish_reason(url, response)

        result = self._parse_single(response)
        result["analyzer"] = "gemini"
        result.update(self._compute_quality_fields(result))

        elapsed = time.time() - start_time
        logger.info(
            "[Gemini] 단건 분석 완료: %s | is_ai_tool=%s confidence=%.2f (%.2f초)",
            url, result.get("is_ai_tool"), result.get("confidence", 0), elapsed,
        )
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

        logger.info("[Gemini] 배치 분석 시작: %d개 URL %s", len(urls), urls)
        start_time = time.time()
        url_list = "\n".join(f"{i}. {url}" for i, url in enumerate(urls, start=1))
        prompt = BATCH_ANALYSIS_PROMPT.format(url_list=url_list)

        response = self._generate_batch(prompt)
        self._check_finish_reason(",".join(urls), response)

        results = self._parse_batch(response, urls)
        for r in results:
            r.update(self._compute_quality_fields(r))

        elapsed = time.time() - start_time
        logger.info("[Gemini] 배치 분석 완료: %d개 URL (%.2f초)", len(urls), elapsed)
        for url, result in zip(urls, results):
            logger.info(
                "[Gemini]   └ %s | is_ai_tool=%s confidence=%.2f title=%r",
                url, result.get("is_ai_tool"), result.get("confidence", 0), result.get("title", ""),
            )
        return results

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(2),
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
        stop=stop_after_attempt(2),
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
        try:
            if response.text:
                return json.loads(response.text)
        except (json.JSONDecodeError, AttributeError):
            pass
        logger.warning("단건 응답 파싱 실패, 기본값 반환")
        return self._default_response()

    def _parse_batch(self, response: Any, urls: list[str]) -> list[dict[str, Any]]:
        """배치 응답 파싱. 길이 불일치 또는 항목 오류 시 기본값으로 보완."""
        results: list[dict[str, Any]] = []
        try:
            if response.text:
                parsed = json.loads(response.text)
                if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
                    results = parsed["results"]
                elif isinstance(parsed, list):
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
                logger.warning("[%s] Gemini 응답에 candidate가 없습니다.", url)
                return
            finish_reason = candidate.finish_reason
            reason_name = finish_reason.name if finish_reason else "UNKNOWN"
            if reason_name == "MAX_TOKENS":
                logger.warning("[%s] 응답이 max_output_tokens 한도에 도달해 잘렸습니다.", url)
            elif reason_name not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                logger.warning("[%s] 비정상 종료: finish_reason=%s", url, reason_name)
        except Exception as e:
            logger.debug("[%s] finish_reason 확인 중 오류: %s", url, e)

    def _compute_quality_fields(self, result: dict[str, Any]) -> dict[str, Any]:
        """Gemini 응답에서 total_score, hard_pass, review_required를 파생한다.

        total_score: scores 가중 평균을 0–100으로 환산
            (utility * 0.4 + trust * 0.3 + originality * 0.3) * 10
        hard_pass: confidence >= 0.8 이고 is_ai_tool=True
        review_required: confidence < 0.7 이거나 (is_ai_tool이고 total_score < 60)
        """
        scores = result.get("scores") or {}
        try:
            utility = float(scores.get("utility") or 0)
            trust = float(scores.get("trust") or 0)
            originality = float(scores.get("originality") or 0)
            total_score = round(
                (utility * _WEIGHT_UTILITY + trust * _WEIGHT_TRUST + originality * _WEIGHT_ORIGINALITY) * 10, 2
            )
        except (TypeError, ValueError):
            total_score = 0.0

        confidence = float(result.get("confidence") or 0)
        is_ai_tool = bool(result.get("is_ai_tool"))

        hard_pass = is_ai_tool and confidence >= _HARD_PASS_CONFIDENCE_THRESHOLD
        review_required = confidence < _REVIEW_CONFIDENCE_THRESHOLD or (is_ai_tool and total_score < _REVIEW_SCORE_THRESHOLD)

        return {
            "total_score": total_score,
            "hard_pass": hard_pass,
            "review_required": review_required,
        }

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
            "total_score": 0.0,
            "hard_pass": False,
            "review_required": True,
        }
