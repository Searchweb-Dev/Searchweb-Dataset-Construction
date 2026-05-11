"""Gemini API를 사용한 웹사이트 분석기 (url_context 방식)."""

import json
import logging
import time
from typing import Any, Optional

from google import genai
from google.genai import types

from src.core.config import get_gemini_model

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 웹사이트 분석 전문가입니다.
주어진 URL과 페이지 내용을 분석하여 다음을 판정하세요:

1. 해당 웹사이트가 AI 도구/서비스인지 판정
2. 서비스의 분류 (대/중/소분류)
3. 주요 기능별 태그
4. 유용성, 신뢰도, 독창성을 1-10점으로 평가

판정 기준:
- AI 도구: ChatGPT, Claude, Gemini, 이미지생성AI 등 AI 기술 기반 서비스
- 신뢰도: 공식 정보 출처, 명확한 개인정보보호정책 여부
- 유용성: 실용적 가치, 사용자 편의성

신중하고 객관적으로 판정하세요."""

_ANALYSIS_PROMPT = """다음 웹사이트를 분석하고 결과를 순수 JSON만 반환하세요. 설명, 마크다운, 코드블록 없이 JSON 객체만 출력하세요.

URL: {url}

반환 형식 (이 JSON 구조만 출력):
{{
  "is_ai_tool": true,
  "title": "서비스 제목",
  "description": "서비스 설명 (한글)",
  "categories": [
    {{"level_1": "대분류", "level_2": "중분류", "level_3": "소분류", "is_primary": true}}
  ],
  "tags": ["태그1", "태그2"],
  "scores": {{"utility": 7, "trust": 8, "originality": 6}},
  "confidence": 0.9
}}

URL에 접근할 수 없거나 분석이 불가한 경우에도 반드시 위 JSON 형식으로 반환하세요:
- is_ai_tool: false
- confidence: 0
- 나머지 필드: 빈 값
"""


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
            contents=_ANALYSIS_PROMPT.format(url=url),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                tools=[types.Tool(url_context=types.UrlContext())],
                max_output_tokens=2048,
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
            return self._default_response()

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
