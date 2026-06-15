"""src/rule/classifiers/status_policy.py — StatusPolicyMixin 단위 테스트."""

from src.rule.classifiers.status_policy import StatusPolicyMixin
from src.rule.models import CriterionResult, FetchResult
from src.rule.config import EvalConfig


def _make_criterion(name: str, passed: bool, reason: str = "reason", confidence: float = 0.9) -> CriterionResult:
    return CriterionResult(name=name, passed=passed, reason=reason, confidence=confidence)


def _make_homepage(ok: bool = True, fetched_by: str = "requests", text: str = "", links: list | None = None) -> FetchResult:
    return FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200 if ok else 403,
        ok=ok,
        html="",
        text=text,
        title="",
        meta_description="",
        links=links or [],
        fetched_by=fetched_by,
    )


class ConcretePolicy(StatusPolicyMixin):
    def __init__(self, config: EvalConfig | None = None):
        self.config = config or EvalConfig()


class TestReviewGate:
    """_review_gate 수동 검토 필요 여부 판별 검증."""

    def setup_method(self):
        self.policy = ConcretePolicy()
        self.all_pass_criteria = {
            "usable_now": _make_criterion("usable_now", True),
            "clear_function_desc": _make_criterion("clear_function_desc", True, confidence=0.9),
            "has_pricing": _make_criterion("has_pricing", True),
            "has_docs_or_help": _make_criterion("has_docs_or_help", True),
            "has_privacy_or_data_policy": _make_criterion("has_privacy_or_data_policy", True),
        }

    def test_no_review_when_all_criteria_pass(self):
        homepage = _make_homepage()
        extracted = {"ai_scope": {"scope_decision": "ai"}}
        required, reasons = self.policy._review_gate(self.all_pass_criteria, homepage, extracted, "curated")
        assert required is False
        assert reasons == []

    def test_review_when_non_ai_scope_gate(self):
        criteria = {k: _make_criterion(k, False, reason="AI 사이트 판별 게이트에서 제외됨") for k in self.all_pass_criteria}
        homepage = _make_homepage()
        required, reasons = self.policy._review_gate(criteria, homepage, {}, "rejected")
        assert required is False

    def test_review_when_uncertain_scope(self):
        homepage = _make_homepage()
        extracted = {"ai_scope": {"scope_decision": "uncertain"}}
        required, reasons = self.policy._review_gate(self.all_pass_criteria, homepage, extracted, "curated")
        assert required is True
        assert any("uncertain" in r for r in reasons)

    def test_review_when_low_clear_desc_confidence(self):
        criteria = dict(self.all_pass_criteria)
        criteria["clear_function_desc"] = _make_criterion("clear_function_desc", True, confidence=0.5)
        homepage = _make_homepage()
        required, reasons = self.policy._review_gate(criteria, homepage, {"ai_scope": {"scope_decision": "ai"}}, "curated")
        assert required is True

    def test_review_when_anti_bot_blocked(self):
        homepage = _make_homepage()
        extracted = {"anti_bot_blocked": True, "ai_scope": {"scope_decision": "ai"}}
        required, reasons = self.policy._review_gate(self.all_pass_criteria, homepage, extracted, "incubating")
        assert required is True
        assert any("anti-bot" in r for r in reasons)

    def test_review_when_contact_sales_only(self):
        homepage = _make_homepage()
        extracted = {"contact_sales_only": True, "ai_scope": {"scope_decision": "ai"}}
        required, reasons = self.policy._review_gate(self.all_pass_criteria, homepage, extracted, "incubating")
        assert required is True

    def test_review_when_curated_missing_docs(self):
        criteria = dict(self.all_pass_criteria)
        criteria["has_docs_or_help"] = _make_criterion("has_docs_or_help", False)
        homepage = _make_homepage()
        extracted = {"ai_scope": {"scope_decision": "ai"}}
        required, reasons = self.policy._review_gate(criteria, homepage, extracted, "curated")
        assert required is True
        assert any("docs" in r for r in reasons)

    def test_review_when_curated_missing_policy(self):
        criteria = dict(self.all_pass_criteria)
        criteria["has_privacy_or_data_policy"] = _make_criterion("has_privacy_or_data_policy", False)
        homepage = _make_homepage()
        extracted = {"ai_scope": {"scope_decision": "ai"}}
        required, reasons = self.policy._review_gate(criteria, homepage, extracted, "curated")
        assert required is True
        assert any("policy" in r for r in reasons)
