"""LLM 분석기 팩토리. LLM_PROVIDER 환경변수로 백엔드를 선택한다."""

import logging
from typing import Any, Optional

from src.core.config import get_llm_provider, get_gemini_api_key, get_claude_api_key
from src.ai.gemini_analyzer import GeminiAnalyzer

logger = logging.getLogger(__name__)


def get_analyzer(api_key: Optional[str] = None) -> Any:
    """LLM_PROVIDER 환경변수에 따라 적절한 분석기 인스턴스를 반환한다."""
    provider = get_llm_provider()

    if provider == "claude":
        try:
            from src.ai.claude_analyzer import ClaudeAnalyzer
        except ImportError:
            raise ImportError(
                "LLM_PROVIDER=claude 이지만 anthropic 패키지가 설치되어 있지 않습니다. "
                "`uv add anthropic`으로 설치하세요."
            )
        key = api_key or get_claude_api_key()
        logger.info("LLM 프로바이더: Claude")
        return ClaudeAnalyzer(api_key=key)

    key = api_key or get_gemini_api_key()
    logger.info("LLM 프로바이더: Gemini")
    return GeminiAnalyzer(api_key=key)
