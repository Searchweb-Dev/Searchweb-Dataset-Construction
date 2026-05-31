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


@lru_cache
def get_api_key() -> str:
    """API 키 반환. 환경변수 미설정 시 RuntimeError 발생."""
    key = os.getenv("API_KEY")
    if not key:
        raise RuntimeError("API_KEY 환경변수가 설정되지 않았습니다.")
    return key


@lru_cache
def get_allowed_origins() -> tuple[str, ...]:
    """허용된 CORS 오리진 목록 반환."""
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000")
    return tuple(o.strip() for o in raw.split(",") if o.strip())


@lru_cache
def get_db_pool_timeout() -> int:
    """DB 커넥션 풀 획득 대기 타임아웃(초) 반환."""
    return int(os.getenv("DB_POOL_TIMEOUT", "30"))


@lru_cache
def get_db_pool_recycle() -> int:
    """DB 커넥션 재사용 최대 수명(초) 반환."""
    return int(os.getenv("DB_POOL_RECYCLE", "1800"))


@lru_cache
def get_unreachable_ttl_seconds() -> int:
    """접근 불가 URL 재시도 대기 기간(초) 반환."""
    days = int(os.getenv("UNREACHABLE_TTL_DAYS", "7"))
    return days * 24 * 3600


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
