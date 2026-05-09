"""Gemini API를 사용한 웹사이트 분석기."""

import base64
import json
import logging
import time
from typing import Optional, Any

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


class GeminiAnalyzer:
    """Gemini를 사용한 웹사이트 분석기."""

    def __init__(self, api_key: Optional[str] = None):
        """Gemini 클라이언트 초기화."""
        self.client = genai.Client(api_key=api_key)
        self.model = get_gemini_model()

    def analyze_website(
        self,
        url: str,
        page_content: str,
        screenshot_base64: Optional[str] = None,
    ) -> dict[str, Any]:
        """웹사이트를 분석하여 AI 여부 및 분류 판정."""
        start_time = time.time()

        parts: list[Any] = [self._build_analysis_prompt(url, page_content)]

        if screenshot_base64:
            image_bytes = (
                base64.b64decode(screenshot_base64)
                if isinstance(screenshot_base64, str)
                else screenshot_base64
            )
            parts.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/png",
                )
            )

        response = self.client.models.generate_content(
            model=self.model,
            contents=parts,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                max_output_tokens=2048,
            ),
        )

        result = self._parse_response(response.text)

        elapsed = time.time() - start_time
        logger.info(f"Gemini 분석 완료: {elapsed:.2f}초")

        return result

    def _build_analysis_prompt(self, url: str, page_content: str) -> str:
        """분석 프롬프트 생성."""
        return f"""다음 웹사이트를 분석하고 AI 판별 및 분류 결과를 JSON으로 반환하세요.

URL: {url}

페이지 내용:
{page_content[:4000]}

다음 정보를 JSON으로 반환하세요:
1. is_ai_tool (boolean): AI 도구 여부
2. title (string): 서비스 제목
3. description (string): 서비스 설명 (한글)
4. categories (array):
   - level_1 (string): 대분류
   - level_2 (string): 중분류
   - level_3 (string): 소분류
   - is_primary (boolean): 주요 카테고리 여부
5. tags (array): 기능별 태그
6. scores (object):
   - utility (1-10): 유용성
   - trust (1-10): 신뢰도
   - originality (1-10): 독창성
7. confidence (0-1): 판단 신뢰도
"""

    def _parse_response(self, response_text: str) -> dict[str, Any]:
        """Gemini 응답 파싱."""
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}")
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
