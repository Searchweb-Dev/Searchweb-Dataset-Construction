"""LLM 관련 설정."""

import os
from functools import lru_cache


@lru_cache
def get_llm_provider() -> str:
    """LLM 프로바이더 반환. 환경변수 미설정 시 RuntimeError 발생."""
    provider = os.getenv("LLM_PROVIDER")
    if not provider:
        raise RuntimeError("LLM_PROVIDER 환경변수가 설정되지 않았습니다.")
    return provider


@lru_cache
def get_gemini_api_key() -> str:
    """Gemini API 키 반환. 환경변수 미설정 시 RuntimeError 발생."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
    return key


@lru_cache
def get_gemini_model() -> str:
    """Gemini 모델명 반환. 환경변수 미설정 시 RuntimeError 발생."""
    model = os.getenv("GEMINI_MODEL")
    if not model:
        raise RuntimeError("GEMINI_MODEL 환경변수가 설정되지 않았습니다.")
    return model


@lru_cache
def get_gemini_retry_multiplier() -> float:
    """Gemini API 재시도 지수 백오프 multiplier 반환."""
    return float(os.getenv("GEMINI_RETRY_MULTIPLIER", "1"))


@lru_cache
def get_gemini_retry_min_wait() -> float:
    """Gemini API 재시도 최소 대기(초) 반환."""
    return float(os.getenv("GEMINI_RETRY_MIN_WAIT", "2"))


@lru_cache
def get_gemini_retry_max_wait() -> float:
    """Gemini API 재시도 최대 대기(초) 반환."""
    return float(os.getenv("GEMINI_RETRY_MAX_WAIT", "30"))


@lru_cache
def get_gemini_retry_attempts() -> int:
    """Gemini API 재시도 최대 횟수 반환."""
    return int(os.getenv("GEMINI_RETRY_ATTEMPTS", "2"))
