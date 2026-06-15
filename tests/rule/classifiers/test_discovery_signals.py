"""src/rule/classifiers/discovery_signals.py — DiscoverySignalMixin 단위 테스트."""

from unittest.mock import MagicMock
from src.rule.classifiers.discovery_signals import DiscoverySignalMixin
from src.rule.models import FetchResult
from src.rule.config import EvalConfig


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_fetch(
    url: str = "https://example.com",
    ok: bool = True,
    text: str = "",
    title: str = "",
    meta_description: str = "",
    links: list | None = None,
    status_code: int = 200,
    final_url: str | None = None,
) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=final_url or url,
        status_code=status_code,
        ok=ok,
        html="",
        text=text,
        title=title,
        meta_description=meta_description,
        links=links or [],
    )


class ConcreteDiscovery(DiscoverySignalMixin):
    """테스트용 구체 클래스."""
    def __init__(self, config=None):
        self.config = config or EvalConfig()
        self.fetcher = MagicMock()
        self.fetcher.is_challenge_text = None
        self.fetcher.playwright_enabled = False
        self.fetcher.playwright_disabled_reason = None


# ---------------------------------------------------------------------------
# _collect_candidate_urls
# ---------------------------------------------------------------------------

class TestCollectCandidateUrls:
    def test_returns_list(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(links=[("Pricing", "https://example.com/pricing")])
        result = cls._collect_candidate_urls("https://example.com", homepage)
        assert isinstance(result, list)

    def test_includes_pricing_link(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(links=[("Pricing", "https://example.com/pricing")])
        result = cls._collect_candidate_urls("https://example.com", homepage)
        assert any("pricing" in u for u in result)

    def test_includes_docs_link(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(links=[("Documentation", "https://docs.example.com/guide")])
        result = cls._collect_candidate_urls("https://example.com", homepage)
        assert any("docs" in u for u in result)

    def test_includes_policy_link(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(links=[("Privacy Policy", "https://example.com/privacy")])
        result = cls._collect_candidate_urls("https://example.com", homepage)
        assert any("privacy" in u for u in result)

    def test_respects_max_total_candidate_pages(self):
        config = EvalConfig(max_total_candidate_pages=3)
        cls = ConcreteDiscovery(config)
        links = [(f"link{i}", f"https://example.com/page{i}") for i in range(20)]
        homepage = _make_fetch(links=links)
        result = cls._collect_candidate_urls("https://example.com", homepage)
        assert len(result) <= 3

    def test_no_duplicates(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(links=[
            ("Pricing", "https://example.com/pricing"),
            ("Plans", "https://example.com/pricing"),
        ])
        result = cls._collect_candidate_urls("https://example.com", homepage)
        assert len(result) == len(set(result))

    def test_adds_fallback_probes_when_homepage_fails(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(ok=False, status_code=403)
        result = cls._collect_candidate_urls("https://example.com", homepage)
        assert len(result) > 0

    def test_openai_domain_gets_external_candidates(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(url="https://chatgpt.com", final_url="https://chatgpt.com")
        result = cls._collect_candidate_urls("https://chatgpt.com", homepage)
        assert any("chatgpt.com" in u or "openai.com" in u for u in result)


# ---------------------------------------------------------------------------
# _extract_structured_signals
# ---------------------------------------------------------------------------

class TestExtractStructuredSignals:
    def test_returns_required_keys(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(text="sign up now start today")
        result = cls._extract_structured_signals(homepage, [homepage])
        for key in (
            "homepage_accessible", "pricing_pages", "docs_pages",
            "policy_pages", "anti_bot_blocked", "has_waitlist_signal",
        ):
            assert key in result

    def test_detects_pricing_page(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch()
        pricing = _make_fetch(
            url="https://example.com/pricing",
            title="Pricing Plans",
            meta_description="Choose a plan",
            text="$9/month starter $29/month pro subscription monthly",
        )
        result = cls._extract_structured_signals(homepage, [homepage, pricing])
        assert pricing.url in result["pricing_pages"]

    def test_detects_docs_page(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch()
        docs = _make_fetch(url="https://docs.example.com/guide", title="Documentation Guide")
        result = cls._extract_structured_signals(homepage, [homepage, docs])
        assert docs.url in result["docs_pages"]

    def test_detects_policy_page(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch()
        policy = _make_fetch(url="https://example.com/privacy", title="Privacy Policy")
        result = cls._extract_structured_signals(homepage, [homepage, policy])
        assert policy.url in result["policy_pages"]

    def test_detects_faq_only_docs(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch()
        faq_page = _make_fetch(
            url="https://example.com/faq",
            title="FAQ",
            text="faq frequently asked questions answers help center",
        )
        result = cls._extract_structured_signals(homepage, [homepage, faq_page])
        # FAQ 키워드는 있으나 docs/guide/quickstart 등이 없으면 faq_only_docs=True
        assert "faq_only_docs" in result

    def test_detects_license_signal(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch()
        page = _make_fetch(url="https://example.com/license", text="mit license open source apache 2.0")
        result = cls._extract_structured_signals(homepage, [homepage, page])
        assert result["license_detected"] is True

    def test_anti_bot_detected_via_error(self):
        cls = ConcreteDiscovery()
        homepage = FetchResult(
            url="https://example.com",
            final_url="https://example.com",
            status_code=403,
            ok=False,
            html="",
            text="",
            title="",
            meta_description="",
            links=[],
            error="anti_bot_challenge_detected",
        )
        result = cls._extract_structured_signals(homepage, [homepage])
        assert result["anti_bot_blocked"] is True

    def test_mass_403_triggers_anti_bot(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(ok=False, status_code=403)
        candidates = [
            _make_fetch(url=f"https://example.com/page{i}", ok=False, status_code=403)
            for i in range(6)
        ]
        result = cls._extract_structured_signals(homepage, [homepage] + candidates)
        assert result["anti_bot_blocked"] is True

    def test_contact_sales_only_detected(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch()
        page = _make_fetch(
            url="https://example.com/contact",
            text="contact sales request a demo",
        )
        result = cls._extract_structured_signals(homepage, [homepage, page])
        assert result["contact_sales_only"] is True

    def test_homepage_not_ok_sets_accessible_false(self):
        cls = ConcreteDiscovery()
        homepage = _make_fetch(ok=False, status_code=404)
        result = cls._extract_structured_signals(homepage, [homepage])
        assert result["homepage_accessible"] is False
