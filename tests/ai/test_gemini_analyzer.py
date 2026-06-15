"""src/ai/gemini_analyzer.py — GeminiAnalyzer 단위 테스트."""

import pytest
from unittest.mock import MagicMock, patch
from src.ai.gemini_analyzer import _is_retryable, _raise_typed_error, GeminiAnalyzer
from src.core.exceptions import (
    SiteUnreachableError,
    RateLimitError,
    ApiTimeoutError,
)


@pytest.fixture(autouse=True)
def set_gemini_env(monkeypatch):
    """Gemini 관련 환경변수 설정."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    # lru_cache 초기화
    from src.ai import config as ai_config
    ai_config.get_gemini_model.cache_clear()
    ai_config.get_gemini_retry_attempts.cache_clear()
    ai_config.get_gemini_retry_min_wait.cache_clear()
    ai_config.get_gemini_retry_max_wait.cache_clear()
    ai_config.get_gemini_retry_multiplier.cache_clear()


class TestIsRetryable:
    """_is_retryable 재시도 판별 검증."""

    def test_rate_limit_error_is_retryable(self):
        exc = RuntimeError("resource_exhausted quota exceeded")
        assert _is_retryable(exc) is True

    def test_timeout_error_is_retryable(self):
        exc = RuntimeError("deadline_exceeded")
        assert _is_retryable(exc) is True

    def test_auth_error_not_retryable(self):
        exc = RuntimeError("unauthenticated request failed")
        assert _is_retryable(exc) is False

    def test_not_found_not_retryable(self):
        exc = RuntimeError("not_found resource")
        assert _is_retryable(exc) is False


class TestRaiseTypedError:
    """_raise_typed_error 도메인 예외 발생 검증."""

    def test_raises_site_unreachable_for_invalid_argument(self):
        exc = RuntimeError("invalid_argument url context failed")
        with pytest.raises(SiteUnreachableError):
            _raise_typed_error(exc, "https://example.com")

    def test_raises_rate_limit_for_resource_exhausted(self):
        exc = RuntimeError("resource_exhausted quota")
        with pytest.raises(RateLimitError):
            _raise_typed_error(exc, "https://example.com")

    def test_raises_timeout_for_deadline_exceeded(self):
        exc = RuntimeError("deadline_exceeded request")
        with pytest.raises(ApiTimeoutError):
            _raise_typed_error(exc, "https://example.com")

    def test_raises_original_for_unknown(self):
        exc = RuntimeError("something totally random xyz")
        with pytest.raises(RuntimeError):
            _raise_typed_error(exc, "https://example.com")

    def test_error_message_includes_url(self):
        exc = RuntimeError("resource_exhausted quota")
        with pytest.raises(RateLimitError, match="https://example.com"):
            _raise_typed_error(exc, "https://example.com")


class TestGeminiAnalyzerInit:
    """GeminiAnalyzer 초기화 검증."""

    def test_init_creates_client(self):
        with patch("src.ai.gemini_analyzer.genai.Client") as mock_client:
            analyzer = GeminiAnalyzer(api_key="test-key")
            mock_client.assert_called_once_with(api_key="test-key")
            assert analyzer.model == "gemini-2.0-flash"


class TestGeminiAnalyzerAnalyzeWebsite:
    """GeminiAnalyzer.analyze_website 단건 분석 검증."""

    def _make_analyzer(self):
        with patch("src.ai.gemini_analyzer.genai.Client"):
            analyzer = GeminiAnalyzer(api_key="test-key")
        return analyzer

    def _make_response(self, payload: dict) -> MagicMock:
        import json
        resp = MagicMock()
        resp.text = json.dumps(payload)
        candidate = MagicMock()
        candidate.finish_reason = MagicMock()
        candidate.finish_reason.name = "STOP"
        resp.candidates = [candidate]
        return resp

    def test_analyze_website_returns_dict(self):
        analyzer = self._make_analyzer()
        response = self._make_response({"is_ai_tool": True, "title": "TestAI", "confidence": 0.9,
                                        "description": "desc", "categories": [], "tags": [], "scores": {"utility": 8, "trust": 7, "originality": 6}})
        with patch.object(analyzer, "_generate", return_value=response):
            result = analyzer.analyze_website("https://example.com")
        assert result["is_ai_tool"] is True
        assert result["analyzer"] == "gemini"
        assert "total_score" in result
        assert "hard_pass" in result

    def test_analyze_website_raises_typed_error_on_exception(self):
        analyzer = self._make_analyzer()
        with patch.object(analyzer, "_generate", side_effect=RuntimeError("resource_exhausted")):
            with pytest.raises(RateLimitError):
                analyzer.analyze_website("https://example.com")


class TestGeminiAnalyzerAnalyzeWebsitesBatch:
    """GeminiAnalyzer.analyze_websites_batch 배치 분석 검증."""

    def _make_analyzer(self):
        with patch("src.ai.gemini_analyzer.genai.Client"):
            analyzer = GeminiAnalyzer(api_key="test-key")
        return analyzer

    def test_empty_urls_returns_empty(self):
        analyzer = self._make_analyzer()
        result = analyzer.analyze_websites_batch([])
        assert result == []

    def test_single_url_delegates_to_analyze_website(self):
        analyzer = self._make_analyzer()
        expected = {"is_ai_tool": True, "analyzer": "gemini", "title": "AI"}
        with patch.object(analyzer, "analyze_website", return_value=expected) as mock:
            result = analyzer.analyze_websites_batch(["https://example.com"])
        mock.assert_called_once_with("https://example.com")
        assert result == [expected]

    def test_batch_returns_one_result_per_url(self):
        import json
        analyzer = self._make_analyzer()
        payload = {"results": [
            {"is_ai_tool": True, "title": "A", "confidence": 0.9, "description": "", "categories": [], "tags": [], "scores": {"utility": 8, "trust": 7, "originality": 6}},
            {"is_ai_tool": False, "title": "B", "confidence": 0.3, "description": "", "categories": [], "tags": [], "scores": {"utility": 2, "trust": 2, "originality": 2}},
        ]}
        resp = MagicMock()
        resp.text = json.dumps(payload)
        candidate = MagicMock()
        candidate.finish_reason = MagicMock()
        candidate.finish_reason.name = "STOP"
        resp.candidates = [candidate]
        with patch.object(analyzer, "_generate", return_value=resp):
            results = analyzer.analyze_websites_batch(["https://a.com", "https://b.com"])
        assert len(results) == 2
        assert "total_score" in results[0]
