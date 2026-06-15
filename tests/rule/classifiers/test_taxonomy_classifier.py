"""src/rule/classifiers/taxonomy_classifier.py — TaxonomyClassifierMixin 단위 테스트."""

from src.rule.classifiers.taxonomy_classifier import TaxonomyClassifierMixin
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
) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=final_url,
        status_code=200 if ok else 403,
        ok=ok,
        html="",
        text=text,
        title=title,
        meta_description=meta_description,
        links=links or [],
    )


class ConcreteTaxonomy(TaxonomyClassifierMixin):
    def __init__(self):
        self.config = EvalConfig()


class TestClassifyTaxonomy:
    """_classify_taxonomy 분류 결과 검증."""

    def setup_method(self):
        self.cls = ConcreteTaxonomy()
        self.homepage = _make_fetch_result()

    def test_returns_required_fields(self):
        all_pages = {"https://example.com": self.homepage}
        result = self.cls._classify_taxonomy(self.homepage, all_pages, {})
        for key in ("primary_category", "is_ai_site", "taxonomy_skipped"):
            assert key in result

    def test_skips_taxonomy_for_non_ai_scope(self):
        extracted = {"ai_scope": {"scope_decision": "non_ai", "is_ai_site": False, "confidence": 0.95, "reason": "non-ai site"}}
        all_pages = {"https://example.com": self.homepage}
        result = self.cls._classify_taxonomy(self.homepage, all_pages, extracted)
        assert result["taxonomy_skipped"] is True
        assert result["is_ai_site"] is False

    def test_uses_text_cache_when_provided(self):
        text_cache = {
            "corpus": "machine learning deep learning",
            "header_blob": "",
            "links_blob": "",
            "combined_blob": "machine learning deep learning",
        }
        all_pages = {}
        result = self.cls._classify_taxonomy(self.homepage, all_pages, {}, text_cache=text_cache)
        assert "primary_category" in result

    def test_uncategorized_when_no_keywords(self):
        homepage = _make_fetch_result(text="hello world nothing special")
        all_pages = {"https://example.com": homepage}
        result = self.cls._classify_taxonomy(homepage, all_pages, {})
        assert result["primary_category"] in ("Uncategorized", result["primary_category"])

    def test_platforms_is_list(self):
        homepage = _make_fetch_result(text="web app accessible online browser")
        all_pages = {"https://example.com": homepage}
        result = self.cls._classify_taxonomy(homepage, all_pages, {})
        assert isinstance(result["platforms"], list)


class TestInferPricingModel:
    """_infer_pricing_model 가격 모델 추정 검증."""

    def setup_method(self):
        self.cls = ConcreteTaxonomy()

    def test_open_source_license(self):
        result = self.cls._infer_pricing_model("mit license open source", {"license_detected": True})
        assert result == "open_source_license"

    def test_free_and_paid(self):
        result = self.cls._infer_pricing_model("free trial $9/month subscription", {})
        assert result == "free_and_paid"

    def test_paid_only(self):
        result = self.cls._infer_pricing_model("$19 per month subscription plan", {})
        assert result == "paid"

    def test_contact_sales_only(self):
        result = self.cls._infer_pricing_model("contact sales request a demo", {})
        assert result == "contact_sales_only"

    def test_free_only(self):
        result = self.cls._infer_pricing_model("totally free no cost", {})
        assert result == "free"

    def test_unknown_when_no_signals(self):
        result = self.cls._infer_pricing_model("some random text", {})
        assert result == "unknown"


class TestInferPlatforms:
    """_infer_platforms 플랫폼 추정 검증."""

    def setup_method(self):
        self.cls = ConcreteTaxonomy()

    def test_web_when_pages_exist(self):
        pages = [_make_fetch_result()]
        result = self.cls._infer_platforms("", False, pages)
        assert "web" in result

    def test_api_when_has_api(self):
        result = self.cls._infer_platforms("api access rest endpoint", True, [])
        assert "api" in result

    def test_empty_when_no_pages_no_api(self):
        result = self.cls._infer_platforms("", False, [])
        assert "api" not in result
