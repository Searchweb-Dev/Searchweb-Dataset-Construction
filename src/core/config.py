"""애플리케이션 설정."""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


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
    """LLM 프로바이더 반환. gemini | claude"""
    return os.getenv("LLM_PROVIDER", "gemini")


def get_gemini_api_key() -> str:
    """Gemini API 키 반환."""
    return os.getenv("GEMINI_API_KEY", "")


def get_gemini_model() -> str:
    """Gemini 모델명 반환."""
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


def get_claude_api_key() -> str:
    """Claude API 키 반환."""
    return os.getenv("ANTHROPIC_API_KEY", "")
