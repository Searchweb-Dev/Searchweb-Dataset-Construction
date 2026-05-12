"""Claude API를 사용한 웹사이트 분석기."""

import json
import logging
import time
from typing import Any, Optional

from anthropic import Anthropic

from src.ai.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


class ClaudeAnalyzer:
    """Claude를 사용한 웹사이트 분석기."""

    def __init__(self, api_key: Optional[str] = None):
        """Claude 클라이언트 초기화."""
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-6"
        self.cache_stats: dict[str, int] = {"hits": 0, "misses": 0}

    def analyze_website(self, url: str) -> dict[str, Any]:
        """웹사이트를 분석하여 AI 여부 및 분류 판정."""
        start_time = time.time()

        messages: list[dict] = [
            {
                "role": "user",
                "content": ANALYSIS_PROMPT.format(url=url),
            }
        ]

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=messages,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        )

        result = self._parse_response(response.content[0].text)
        result["analyzer"] = "claude"

        usage = response.usage
        if hasattr(usage, "cache_read_input_tokens") and usage.cache_read_input_tokens:
            self.cache_stats["hits"] += 1
            logger.info(f"캐시 히트: {usage.cache_read_input_tokens} 토큰 절감")
        else:
            self.cache_stats["misses"] += 1
            logger.info("캐시 미스: 새로운 캐시 생성")

        elapsed = time.time() - start_time
        logger.info(f"Claude 분석 완료: {elapsed:.2f}초")
        return result

    def _parse_response(self, response_text: str) -> dict[str, Any]:
        """Claude 응답 파싱."""
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start == -1 or json_end == 0:
                logger.error("응답에서 JSON을 찾을 수 없음")
                return self._default_response()
            return json.loads(response_text[json_start:json_end])
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
            "scores": {"utility": 0, "trust": 0, "originality": 0},
            "confidence": 0,
        }
