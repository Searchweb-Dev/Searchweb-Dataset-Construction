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
