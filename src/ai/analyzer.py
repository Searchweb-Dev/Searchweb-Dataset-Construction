"""LLM 분석기 팩토리. LLM_PROVIDER 환경변수로 백엔드를 선택한다."""

import logging
from typing import Optional, Any

from src.core.config import get_llm_provider, get_gemini_api_key, get_claude_api_key
from src.ai.gemini_analyzer import GeminiAnalyzer
from src.ai.prompts import SYSTEM_PROMPT, CLAUDE_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


def _make_claude_analyzer(api_key: Optional[str]) -> Any:
    """Claude 분석기 생성. anthropic 패키지가 없으면 ImportError를 발생시킨다."""
    try:
        from anthropic import Anthropic
        import json
        import time

        class ClaudeAnalyzer:
            """Claude를 사용한 웹사이트 분석기."""

            def __init__(self, key: Optional[str] = None):
                """Claude 클라이언트 초기화."""
                self.client = Anthropic(api_key=key)
                self.model = "claude-sonnet-4-6"
                self.cache_stats: dict[str, int] = {"hits": 0, "misses": 0}

            def analyze_website(
                self,
                url: str,
                page_content: str,
                screenshot_base64: Optional[str] = None,
            ) -> dict[str, Any]:
                """웹사이트를 분석하여 AI 여부 및 분류 판정."""
                start_time = time.time()

                messages: list[dict] = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": self._build_analysis_prompt(url, page_content),
                            }
                        ],
                    }
                ]

                if screenshot_base64:
                    messages[0]["content"].append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_base64,
                        },
                    })

                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    messages=messages,
                    system=[
                        {
                            "type": "text",
                            "text": self._get_system_prompt(),
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                )

                result = self._parse_response(response.content[0].text)

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

            def _build_analysis_prompt(self, url: str, page_content: str) -> str:
                return CLAUDE_ANALYSIS_PROMPT.format(
                    url=url,
                    page_content=page_content[:4000],
                )

            def _get_system_prompt(self) -> str:
                return SYSTEM_PROMPT

            def _parse_response(self, response_text: str) -> dict[str, Any]:
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
                return {
                    "is_ai_tool": False,
                    "title": "Unknown",
                    "description": "분석 실패",
                    "categories": [],
                    "tags": [],
                    "scores": {"utility": 0, "trust": 0, "originality": 0},
                    "confidence": 0,
                }

        return ClaudeAnalyzer(api_key)

    except ImportError:
        raise ImportError(
            "LLM_PROVIDER=claude 이지만 anthropic 패키지가 설치되어 있지 않습니다. "
            "`uv add anthropic`으로 설치하세요."
        )


def get_analyzer(api_key: Optional[str] = None) -> Any:
    """LLM_PROVIDER 환경변수에 따라 적절한 분석기 인스턴스를 반환한다."""
    provider = get_llm_provider()

    if provider == "claude":
        key = api_key or get_claude_api_key()
        logger.info("LLM 프로바이더: Claude")
        return _make_claude_analyzer(key)

    key = api_key or get_gemini_api_key()
    logger.info("LLM 프로바이더: Gemini")
    return GeminiAnalyzer(api_key=key)


# detector.py의 `from src.ai.analyzer import WebAnalyzer` 호환용 별칭
WebAnalyzer = get_analyzer
