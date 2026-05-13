"""애플리케이션 설정."""

import logging
import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger(__name__)


@lru_cache
def get_db_url() -> str:
    """DB URL 반환."""
    env = os.getenv("ENV", "development")

    if env == "production":
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("프로덕션 환경에서 DATABASE_URL 환경변수가 필요합니다.")
        return url

    return os.getenv("DATABASE_URL", "sqlite:///./test.db")


def get_api_key() -> str:
    """API 키 반환. 환경변수 미설정 시 RuntimeError 발생."""
    key = os.getenv("API_KEY")
    if not key:
        raise RuntimeError("API_KEY 환경변수가 설정되지 않았습니다.")
    return key


def get_allowed_origins() -> list[str]:
    """허용된 CORS 오리진 목록 반환."""
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def get_llm_provider() -> str:
    """LLM 프로바이더 반환. 환경변수 미설정 시 RuntimeError 발생."""
    provider = os.getenv("LLM_PROVIDER")
    if not provider:
        raise RuntimeError("LLM_PROVIDER 환경변수가 설정되지 않았습니다.")
    return provider


def get_gemini_api_key() -> str:
    """Gemini API 키 반환. 환경변수 미설정 시 RuntimeError 발생."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
    return key


def get_gemini_model() -> str:
    """Gemini 모델명 반환. 환경변수 미설정 시 RuntimeError 발생."""
    model = os.getenv("GEMINI_MODEL")
    if not model:
        raise RuntimeError("GEMINI_MODEL 환경변수가 설정되지 않았습니다.")
    return model


def get_classifier_mode() -> str:
    """CLASSIFIER_MODE 환경변수를 읽어 분류기 모드를 반환한다.

    유효값: "llm" | "rule". 기본값은 "llm".
    유효하지 않은 값이면 경고 로그를 출력하고 "llm"으로 폴백한다.
    """
    raw = os.getenv("CLASSIFIER_MODE", "llm")
    normalized = raw.strip().lower()
    if normalized in ("llm", "rule"):
        return normalized
    _logger.warning(
        "CLASSIFIER_MODE 환경변수 값이 유효하지 않습니다: '%s'. 'llm'으로 폴백합니다.", raw
    )
    return "llm"
