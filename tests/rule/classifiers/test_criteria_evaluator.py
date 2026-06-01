"""src/rule/classifiers/criteria_evaluator.py — CriteriaEvaluatorMixin / WeightedQualityEvaluator 단위 테스트."""

import pytest
from unittest.mock import MagicMock
from src.rule.classifiers.criteria_evaluator import (
    CriteriaEvaluatorMixin,
    WeightedQualityEvaluator,
    DummyLLM,
)
from src.rule.classifiers.discovery_signals import DiscoverySignalMixin
from src.rule.classifiers.ai_scope_classifier import AiScopeClassifierMixin
from src.rule.classifiers.taxonomy_classifier import TaxonomyClassifierMixin
from src.rule.classifiers.status_policy import StatusPolicyMixin
from src.rule.models import CriterionResult, Evidence, FetchResult
from src.rule.config import EvalConfig


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_fetch(
    url: str = "https://example.com",
    ok: bool = True,
    text: str = "",
    title: str = "AI Tool",
    meta_description: str = "",
    links: list | None = None,
    status_code: int = 200,
    error: str | None = None,
    fetched_by: str = "requests",
) -> FetchResult:
    return FetchResult(
        url=url, final_url=url, status_code=status_code, ok=ok,
        html="", text=text, title=title, meta_description=meta_description,
        links=links or [], error=error, fetched_by=fetched_by,
    )


def _make_criterion(name: str, passed: bool, confidence: float = 0.9, reason: str = "") -> CriterionResult:
    return CriterionResult(name=name, passed=passed, reason=reason, confidence=confidence)


def _all_criteria(passed: bool = True) -> dict[str, CriterionResult]:
    names = ["usable_now", "clear_function_desc", "has_pricing", "has_docs_or_help", "has_privacy_or_data_policy"]
    return {n: _make_criterion(n, passed) for n in names}


class ConcreteCriteriaEval(CriteriaEvaluatorMixin):
    """테스트용 구체 클래스."""
    def __init__(self, config=None):
        self.config = config or EvalConfig()
        self.llm = None


# ---------------------------------------------------------------------------
# DummyLLM
# ---------------------------------------------------------------------------

class TestDummyLLM:
    def test_passed_when_action_and_noun(self):
        llm = DummyLLM()
        result = llm.evaluate({"candidate_sentence": "generate images using AI models"})
        assert result["passed"] is True

    def test_not_passed_when_generic(self):
        llm = DummyLLM()
        result = llm.evaluate({"candidate_sentence": "we are the best platform"})
        assert result["passed"] is False

    def test_returns_required_keys(self):
        llm = DummyLLM()
        result = llm.evaluate({"candidate_sentence": "test"})
        for k in ("passed", "confidence", "reason"):
            assert k in result


# ---------------------------------------------------------------------------
# _build_non_ai_scope_criteria
# ---------------------------------------------------------------------------

class TestBuildNonAiScopeCriteria:
    def test_all_criteria_fail(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        criteria = ev._build_non_ai_scope_criteria(homepage, "restaurant site")
        assert all(not c.passed for c in criteria.values())
        assert len(criteria) == 5

    def test_reason_contains_detail(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        criteria = ev._build_non_ai_scope_criteria(homepage, "my detail reason")
        reason = list(criteria.values())[0].reason
        assert "my detail reason" in reason

    def test_empty_detail_uses_default_reason(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        criteria = ev._build_non_ai_scope_criteria(homepage, "")
        assert "AI 사이트 판별 게이트에서 제외됨" in list(criteria.values())[0].reason


# ---------------------------------------------------------------------------
# _build_criteria — non_ai 분기
# ---------------------------------------------------------------------------

class TestBuildCriteria:
    def test_returns_non_ai_criteria_for_non_ai_scope(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        extracted = {"ai_scope": {"scope_decision": "non_ai", "reason": "food site"}}
        criteria = ev._build_criteria(homepage, {homepage.url: homepage}, extracted)
        assert all(not c.passed for c in criteria.values())

    def test_returns_evaluations_for_ai_scope(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch(
            text="Sign up now and start using our AI tool immediately.",
            meta_description="An AI tool that helps you generate content fast.",
        )
        extracted = {"ai_scope": {"scope_decision": "ai"}}
        criteria = ev._build_criteria(homepage, {homepage.url: homepage}, extracted)
        assert len(criteria) == 5
        for name in ("usable_now", "clear_function_desc", "has_pricing", "has_docs_or_help", "has_privacy_or_data_policy"):
            assert name in criteria


# ---------------------------------------------------------------------------
# _eval_usable_now
# ---------------------------------------------------------------------------

class TestEvalUsableNow:
    def test_passes_with_signup_link(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch(
            text="Get started today.",
            links=[("Sign up", "https://example.com/signup"), ("Login", "https://example.com/login")],
        )
        result = ev._eval_usable_now(homepage, {homepage.url: homepage}, {})
        assert result.passed is True

    def test_fails_with_waitlist_only(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch(text="Join our waitlist. Coming soon. Early access only.")
        result = ev._eval_usable_now(homepage, {homepage.url: homepage}, {})
        assert result.passed is False

    def test_fails_when_homepage_not_ok(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch(ok=False, status_code=403, error="forbidden")
        result = ev._eval_usable_now(homepage, {}, {})
        assert result.passed is False

    def test_anti_bot_returns_false(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch(ok=False, status_code=403)
        result = ev._eval_usable_now(homepage, {}, {"anti_bot_blocked": True})
        assert result.passed is False


# ---------------------------------------------------------------------------
# _eval_clear_function_desc
# ---------------------------------------------------------------------------

class TestEvalClearFunctionDesc:
    def test_passes_with_action_noun_description(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch(
            meta_description="Generate professional reports using our AI assistant for business teams.",
        )
        result = ev._eval_clear_function_desc(homepage, {homepage.url: homepage}, {})
        assert result.name == "clear_function_desc"

    def test_returns_criterion_result(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        result = ev._eval_clear_function_desc(homepage, {}, {})
        assert isinstance(result, CriterionResult)
        assert result.name == "clear_function_desc"


# ---------------------------------------------------------------------------
# _eval_pricing
# ---------------------------------------------------------------------------

class TestEvalPricing:
    def test_passes_with_pricing_pages(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        pricing_page = _make_fetch(url="https://example.com/pricing", text="$9/month basic plan")
        all_pages = {homepage.url: homepage, pricing_page.url: pricing_page}
        extracted = {"pricing_pages": [pricing_page.url]}
        result = ev._eval_pricing(homepage, all_pages, extracted)
        assert result.passed is True

    def test_fails_with_no_pricing_info(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        result = ev._eval_pricing(homepage, {homepage.url: homepage}, {})
        assert result.passed is False

    def test_contact_sales_when_config_false(self):
        config = EvalConfig(contact_sales_counts_as_pricing=False)
        ev = ConcreteCriteriaEval(config)
        homepage = _make_fetch()
        result = ev._eval_pricing(homepage, {homepage.url: homepage}, {"contact_sales_only": True})
        assert result.passed is False

    def test_contact_sales_when_config_true(self):
        config = EvalConfig(contact_sales_counts_as_pricing=True)
        ev = ConcreteCriteriaEval(config)
        homepage = _make_fetch()
        result = ev._eval_pricing(homepage, {homepage.url: homepage}, {"contact_sales_only": True})
        assert result.passed is True

    def test_oss_license_as_pricing(self):
        config = EvalConfig(license_counts_as_pricing_for_oss=True)
        ev = ConcreteCriteriaEval(config)
        homepage = _make_fetch()
        result = ev._eval_pricing(homepage, {homepage.url: homepage}, {"license_detected": True})
        assert result.passed is True


# ---------------------------------------------------------------------------
# _eval_docs
# ---------------------------------------------------------------------------

class TestEvalDocs:
    def test_passes_with_docs_pages(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        docs_page = _make_fetch(url="https://docs.example.com/guide", title="Documentation")
        all_pages = {homepage.url: homepage, docs_page.url: docs_page}
        extracted = {"docs_pages": [docs_page.url]}
        result = ev._eval_docs(homepage, all_pages, extracted)
        assert result.passed is True

    def test_fails_without_docs(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        result = ev._eval_docs(homepage, {homepage.url: homepage}, {})
        assert result.passed is False

    def test_faq_only_with_config_false(self):
        config = EvalConfig(faq_counts_as_docs=False)
        ev = ConcreteCriteriaEval(config)
        homepage = _make_fetch()
        faq_page = _make_fetch(url="https://example.com/faq", title="FAQ")
        extracted = {"docs_pages": [faq_page.url], "faq_only_docs": True}
        result = ev._eval_docs(homepage, {faq_page.url: faq_page}, extracted)
        assert result.passed is False


# ---------------------------------------------------------------------------
# _eval_policy
# ---------------------------------------------------------------------------

class TestEvalPolicy:
    def test_passes_with_privacy_page(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        policy_page = _make_fetch(
            url="https://example.com/privacy",
            title="Privacy Policy",
            text="We protect your personal data under GDPR and privacy policy.",
        )
        all_pages = {homepage.url: homepage, policy_page.url: policy_page}
        extracted = {"policy_pages": [policy_page.url]}
        result = ev._eval_policy(homepage, all_pages, extracted)
        assert result.passed is True

    def test_fails_without_policy(self):
        ev = ConcreteCriteriaEval()
        homepage = _make_fetch()
        result = ev._eval_policy(homepage, {homepage.url: homepage}, {})
        assert result.passed is False


# ---------------------------------------------------------------------------
# _calculate_weighted_scores
# ---------------------------------------------------------------------------

class TestCalculateWeightedScores:
    def test_all_pass_gives_nonzero_score(self):
        ev = ConcreteCriteriaEval()
        criteria = _all_criteria(passed=True)
        breakdown, total, scores = ev._calculate_weighted_scores(criteria)
        assert total > 0

    def test_all_fail_gives_zero_score(self):
        ev = ConcreteCriteriaEval()
        criteria = _all_criteria(passed=False)
        _, total, _ = ev._calculate_weighted_scores(criteria)
        assert total == 0.0

    def test_score_bounded_by_weights(self):
        ev = ConcreteCriteriaEval()
        criteria = _all_criteria(passed=True)
        _, total, _ = ev._calculate_weighted_scores(criteria)
        assert 0.0 <= total <= 100.0


# ---------------------------------------------------------------------------
# WeightedQualityEvaluator._predict_status
# ---------------------------------------------------------------------------

class TestWeightedPredictStatus:
    def _make_evaluator(self, config=None):
        fetcher = MagicMock()
        return WeightedQualityEvaluator(fetcher=fetcher, config=config or EvalConfig())

    def _score_ctx(self, total: float, usable: float = 0.9, clear: float = 0.9,
                   docs: float = 0.9, privacy: float = 0.9) -> dict:
        return {
            "total_score": total,
            "criterion_scores": {
                "usable_now": usable,
                "clear_function_desc": clear,
                "has_docs_or_help": docs,
                "has_privacy_or_data_policy": privacy,
            },
        }

    def test_rejects_low_usable_score(self):
        ev = self._make_evaluator()
        ctx = self._score_ctx(90.0, usable=0.1)
        assert ev._predict_status({}, 0, False, ctx) == "rejected"

    def test_rejects_low_clear_desc(self):
        ev = self._make_evaluator()
        ctx = self._score_ctx(90.0, clear=0.1)
        assert ev._predict_status({}, 0, False, ctx) == "rejected"

    def test_curated_when_high_score_and_docs_policy(self):
        ev = self._make_evaluator()
        ctx = self._score_ctx(90.0)
        assert ev._predict_status({}, 5, True, ctx) == "curated"

    def test_incubating_when_curated_but_low_docs(self):
        config = EvalConfig(curated_score_threshold=85.0, docs_min_for_curated=0.8)
        ev = self._make_evaluator(config)
        ctx = self._score_ctx(90.0, docs=0.1)
        assert ev._predict_status({}, 4, True, ctx) == "incubating"

    def test_incubating_when_medium_score(self):
        ev = self._make_evaluator()
        ctx = self._score_ctx(70.0)
        assert ev._predict_status({}, 3, False, ctx) == "incubating"

    def test_rejected_when_low_score(self):
        ev = self._make_evaluator()
        ctx = self._score_ctx(30.0)
        assert ev._predict_status({}, 1, False, ctx) == "rejected"
