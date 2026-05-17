"""LLM 분석기 팩토리. CLASSIFIER_MODE / LLM_PROVIDER 환경변수로 백엔드를 선택한다."""

import logging
from typing import Any

from src.core.config import get_classifier_mode, get_llm_provider, get_gemini_api_key
from src.ai.gemini_analyzer import GeminiAnalyzer

logger = logging.getLogger(__name__)


def get_analyzer(api_key: str | None = None) -> Any:
    """CLASSIFIER_MODE / LLM_PROVIDER 환경변수에 따라 적절한 분석기 인스턴스를 반환한다.

    CLASSIFIER_MODE=rule 이면 RuleAnalyzer를 반환한다.
    그 외(llm 또는 미설정)이면 LLM_PROVIDER에 따라 LLM 분석기를 반환한다.
    """
    classifier_mode = get_classifier_mode()

    if classifier_mode == "rule":
        from src.rule.analyzer import RuleAnalyzer
        logger.info("분류기 모드: rule (규칙기반 파이프라인)")
        return RuleAnalyzer()

    return get_llm_analyzer(api_key)


def get_llm_analyzer(api_key: str | None = None) -> Any:
    """CLASSIFIER_MODE 무관하게 LLM_PROVIDER에 따른 LLM 분석기를 반환한다.

    /analyze Celery task처럼 항상 LLM 분석이 필요한 경우에 사용한다.
    현재 지원 프로바이더: gemini.
    추후 프로바이더 추가 시 이 함수에 분기를 추가한다.
    """
    provider = get_llm_provider()

    if provider != "gemini":
        logger.warning(
            "LLM_PROVIDER='%s'는 아직 구현되지 않았습니다. Gemini로 폴백합니다.", provider
        )

    key = api_key or get_gemini_api_key()
    logger.info("분류기 모드: llm, LLM 프로바이더: Gemini")
    return GeminiAnalyzer(api_key=key)
