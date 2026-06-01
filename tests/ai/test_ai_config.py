"""src/ai/config.py — 환경변수 getter 단위 테스트."""

import pytest
from src.ai import config as ai_config


@pytest.fixture(autouse=True)
def clear_lru_caches():
    """각 테스트 전 lru_cache 초기화."""
    ai_config.get_llm_provider.cache_clear()
    ai_config.get_gemini_api_key.cache_clear()
    ai_config.get_gemini_model.cache_clear()
    ai_config.get_gemini_retry_multiplier.cache_clear()
    ai_config.get_gemini_retry_min_wait.cache_clear()
    ai_config.get_gemini_retry_max_wait.cache_clear()
    ai_config.get_gemini_retry_attempts.cache_clear()
    yield
    ai_config.get_llm_provider.cache_clear()
    ai_config.get_gemini_api_key.cache_clear()
    ai_config.get_gemini_model.cache_clear()
    ai_config.get_gemini_retry_multiplier.cache_clear()
    ai_config.get_gemini_retry_min_wait.cache_clear()
    ai_config.get_gemini_retry_max_wait.cache_clear()
    ai_config.get_gemini_retry_attempts.cache_clear()


class TestGetLlmProvider:
    def test_returns_provider_when_set(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        assert ai_config.get_llm_provider() == "gemini"

    def test_raises_when_not_set(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        with pytest.raises(RuntimeError, match="LLM_PROVIDER"):
            ai_config.get_llm_provider()


class TestGetGeminiApiKey:
    def test_returns_key_when_set(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "my-secret-key")
        assert ai_config.get_gemini_api_key() == "my-secret-key"

    def test_raises_when_not_set(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            ai_config.get_gemini_api_key()


class TestGetGeminiModel:
    def test_returns_model_when_set(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
        assert ai_config.get_gemini_model() == "gemini-2.0-flash"

    def test_raises_when_not_set(self, monkeypatch):
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        with pytest.raises(RuntimeError, match="GEMINI_MODEL"):
            ai_config.get_gemini_model()


class TestGetGeminiRetrySettings:
    def test_multiplier_default(self, monkeypatch):
        monkeypatch.delenv("GEMINI_RETRY_MULTIPLIER", raising=False)
        assert ai_config.get_gemini_retry_multiplier() == 1.0

    def test_multiplier_custom(self, monkeypatch):
        monkeypatch.setenv("GEMINI_RETRY_MULTIPLIER", "2.5")
        assert ai_config.get_gemini_retry_multiplier() == 2.5

    def test_min_wait_default(self, monkeypatch):
        monkeypatch.delenv("GEMINI_RETRY_MIN_WAIT", raising=False)
        assert ai_config.get_gemini_retry_min_wait() == 2.0

    def test_max_wait_default(self, monkeypatch):
        monkeypatch.delenv("GEMINI_RETRY_MAX_WAIT", raising=False)
        assert ai_config.get_gemini_retry_max_wait() == 30.0

    def test_attempts_default(self, monkeypatch):
        monkeypatch.delenv("GEMINI_RETRY_ATTEMPTS", raising=False)
        assert ai_config.get_gemini_retry_attempts() == 2

    def test_attempts_custom(self, monkeypatch):
        monkeypatch.setenv("GEMINI_RETRY_ATTEMPTS", "5")
        assert ai_config.get_gemini_retry_attempts() == 5
