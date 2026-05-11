"""Gemini API를 사용한 웹사이트 분석기 (url_context 방식)."""

import json
import logging
import time
from typing import Any, Optional

from google import genai
from google.genai import types

from src.core.config import get_gemini_model
from src.ai.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


class GeminiAnalyzer:
    """Gemini url_context 툴을 사용한 웹사이트 분석기."""

    def __init__(self, api_key: Optional[str] = None):
        """Gemini 클라이언트 초기화."""
        self.client = genai.Client(api_key=api_key)
        self.model = get_gemini_model()

    def analyze_website(self, url: str) -> dict[str, Any]:
        """url_context 툴로 웹사이트를 직접 fetch하여 AI 여부 및 분류 판정."""
        start_time = time.time()

        response = self.client.models.generate_content(
            model=self.model,
            contents=ANALYSIS_PROMPT.format(url=url),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[types.Tool(url_context=types.UrlContext())],
            ),
        )

        self._check_finish_reason(url, response)
        if not response.text:
            logger.warning(f"[{url}] Gemini 응답 텍스트가 비어있습니다.")
        result = self._parse_response(response.text or "")

        elapsed = time.time() - start_time
        logger.info(f"Gemini 분석 완료: {elapsed:.2f}초")

        return result

    def _check_finish_reason(self, url: str, response: Any) -> None:
        """AFC 상한 초과 등 비정상 종료 여부를 로깅."""
        try:
            candidate = response.candidates[0] if response.candidates else None
            if candidate is None:
                logger.warning(f"[{url}] Gemini 응답에 candidate가 없습니다.")
                return

            finish_reason = candidate.finish_reason
            reason_name = finish_reason.name if finish_reason else "UNKNOWN"

            if reason_name == "MAX_TOKENS":
                logger.warning(
                    f"[{url}] Gemini 응답이 max_output_tokens 한도에 도달해 잘렸습니다."
                )
            elif reason_name not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                logger.warning(
                    f"[{url}] Gemini 비정상 종료: finish_reason={reason_name}. "
                    "AFC 상한(max remote calls) 초과 또는 기타 중단 가능성이 있습니다."
                )
        except Exception as e:
            logger.debug(f"[{url}] finish_reason 확인 중 오류: {e}")

    def _parse_response(self, response_text: str) -> dict[str, Any]:
        """Gemini 응답 파싱. 마크다운 코드블록 및 텍스트 혼합 형태도 처리."""
        text = response_text.strip()

        # 1. 마크다운 코드블록 추출
        if "```" in text:
            start = text.find("```")
            end = text.rfind("```")
            if start != end:
                inner = text[start:end + 3]
                lines = inner.splitlines()
                text = "\n".join(lines[1:-1]).strip()

        # 2. 텍스트 중 JSON 객체 부분만 추출 ({...})
        if not text.startswith("{"):
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start != -1 and brace_end != -1 and brace_start < brace_end:
                text = text[brace_start:brace_end + 1]

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}\n원본: {response_text[:200]}")
            recovered = self._recover_truncated_json(text)
            if recovered:
                return recovered
            return self._default_response()

    def _recover_truncated_json(self, text: str) -> dict[str, Any] | None:
        """잘린 JSON을 닫는 괄호를 추가해 복구 시도."""
        depth_curly = text.count("{") - text.count("}")
        depth_square = text.count("[") - text.count("]")
        if depth_curly <= 0 and depth_square <= 0:
            return None
        candidate = text.rstrip().rstrip(",")
        candidate += "]" * depth_square + "}" * depth_curly
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    def _default_response(self) -> dict[str, Any]:
        """기본 응답 구조."""
        return {
            "is_ai_tool": False,
            "title": "Unknown",
            "description": "분석 실패",
            "categories": [],
            "tags": [],
            "scores": {
                "utility": 0,
                "trust": 0,
                "originality": 0,
            },
            "confidence": 0,
        }
