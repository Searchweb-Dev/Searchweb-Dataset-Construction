"""src/rule/classifiers/ai_scope_classifier.py — AiScopeClassifierMixin 단위 테스트."""

from src.rule.classifiers.ai_scope_classifier import AiScopeClassifierMixin
from src.rule.models import FetchResult
from src.rule.config import EvalConfig


def _make_fetch_result(
    url: str = "https://example.com",
    final_url: str = "https://example.com",
    ok: bool = True,
    text: str = "",
    title: str = "",
    meta_description: str = "",
    links: list | None = None,
    status_code: int = 200,
) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=final_url,
        status_code=status_code,
        ok=ok,
        html="",
        text=text,
        title=title,
        meta_description=meta_description,
        links=links or [],
    )


class ConcreteClassifier(AiScopeClassifierMixin):
    """테스트용 구체 클래스."""
    def __init__(self):
        self.config = EvalConfig()


class TestInferAiSiteScope:
    """_infer_ai_site_scope AI/non-AI 판정 로직 검증."""

    def setup_method(self):
        self.cls = ConcreteClassifier()
        self.homepage = _make_fetch_result("https://example.com", "https://example.com")

    def test_strong_ai_signals_return_ai(self):
        blob = "machine learning deep learning neural network artificial intelligence transformer model"
        result = self.cls._infer_ai_site_scope(blob, self.homepage)
        assert result["is_ai_site"] is True
        assert result["scope_decision"] == "ai"

    def test_strong_non_ai_signals_return_non_ai(self):
        blob = "restaurant menu food delivery dining cuisine catering chef kitchen recipe"
        result = self.cls._infer_ai_site_scope(blob, self.homepage)
        assert result["is_ai_site"] is False or result["scope_decision"] in ("non_ai", "uncertain")

    def test_ai_domain_hint(self):
        homepage = _make_fetch_result("https://openai.com", "https://openai.com")
        blob = "language model chat completion"
        result = self.cls._infer_ai_site_scope(blob, homepage)
        assert result["is_ai_site"] is True

    def test_tld_ai_hint(self):
        homepage = _make_fetch_result("https://awesome.ai", "https://awesome.ai")
        blob = "artificial intelligence assistant chatbot llm"
        result = self.cls._infer_ai_site_scope(blob, homepage)
        assert result["is_ai_site"] is True

    def test_result_contains_required_fields(self):
        blob = "ai tool machine learning"
        result = self.cls._infer_ai_site_scope(blob, self.homepage)
        for key in ("is_ai_site", "scope_decision", "confidence", "ai_signal_score", "non_ai_signal_score"):
            assert key in result

    def test_confidence_between_0_and_1(self):
        blob = "machine learning deep learning"
        result = self.cls._infer_ai_site_scope(blob, self.homepage)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_ai_keyword_hits_list(self):
        blob = "machine learning deep learning"
        result = self.cls._infer_ai_site_scope(blob, self.homepage)
        assert isinstance(result["ai_keyword_hits"], list)

    def test_uncertain_when_borderline(self):
        # 약한 AI 신호만 있고 non-AI 신호도 없는 경우
        blob = "ai assistant helper tool"
        result = self.cls._infer_ai_site_scope(blob, self.homepage)
        assert result["scope_decision"] in ("ai", "uncertain")


class TestClassifyAiScope:
    """_classify_ai_scope 페이지 기반 판정 검증."""

    def test_uses_text_cache_when_provided(self):
        cls = ConcreteClassifier()
        homepage = _make_fetch_result()
        all_pages = {}
        text_cache = {"ai_scope_blob": "machine learning deep learning neural network"}
        result = cls._classify_ai_scope(homepage, all_pages, text_cache=text_cache)
        assert "is_ai_site" in result

    def test_builds_blob_from_pages_when_no_cache(self):
        cls = ConcreteClassifier()
        homepage = _make_fetch_result(
            text="artificial intelligence machine learning deep learning",
            ok=True,
        )
        all_pages = {"https://example.com": homepage}
        result = cls._classify_ai_scope(homepage, all_pages)
        assert "is_ai_site" in result
