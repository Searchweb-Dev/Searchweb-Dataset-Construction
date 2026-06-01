"""src/rule/pipeline.py — 파이프라인 step 단위 테스트."""

import pytest
from unittest.mock import MagicMock, patch
from src.rule.pipeline import (
    _build_shared_text_cache,
    step_extract_signals,
    step_classify_taxonomy,
    step_assess_ai_scope,
    step_evaluate_criteria,
    step_score_and_predict_status,
    step_review_and_finalize_status,
    step_build_summary,
    step_fetch_and_collect_pages,
)
from src.rule.models import FetchResult, CriterionResult
from src.rule.config import EvalConfig


def _make_fetch_result(
    url: str = "https://example.com",
    ok: bool = True,
    text: str = "machine learning ai tool",
    title: str = "AI Tool",
    meta_description: str = "",
    fetched_by: str = "requests",
) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        status_code=200 if ok else 403,
        ok=ok,
        html="",
        text=text,
        title=title,
        meta_description=meta_description,
        links=[],
        fetched_by=fetched_by,
    )


def _make_criterion(name: str, passed: bool, confidence: float = 0.9, reason: str = "") -> CriterionResult:
    return CriterionResult(name=name, passed=passed, reason=reason, confidence=confidence)


def _make_full_criteria(all_pass: bool = True) -> dict[str, CriterionResult]:
    names = ["usable_now", "clear_function_desc", "has_pricing", "has_docs_or_help", "has_privacy_or_data_policy"]
    return {n: _make_criterion(n, all_pass) for n in names}


class TestBuildSharedTextCache:
    """_build_shared_text_cache 캐시 생성 검증."""

    def test_returns_required_keys(self):
        page = _make_fetch_result()
        cache = _build_shared_text_cache({page.final_url: page})
        for key in ("corpus", "header_blob", "links_blob", "combined_blob", "ai_scope_blob"):
            assert key in cache

    def test_empty_when_no_pages(self):
        cache = _build_shared_text_cache({})
        assert cache["corpus"].strip() == ""
        assert cache["combined_blob"].strip() == ""

    def test_skips_failed_pages(self):
        good = _make_fetch_result("https://a.com", ok=True, text="ai machine learning")
        bad = _make_fetch_result("https://b.com", ok=False, text="secret content")
        cache = _build_shared_text_cache({"https://a.com": good, "https://b.com": bad})
        assert "secret content" not in cache["corpus"]


class TestStepExtractSignals:
    """step_extract_signals 신호 추출 검증."""

    def test_sets_extracted_in_context(self):
        evaluator = MagicMock()
        evaluator._extract_structured_signals.return_value = {"pricing_pages": [], "docs_pages": []}
        homepage = _make_fetch_result()
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "all_pages": {homepage.final_url: homepage},
        }
        step_extract_signals(evaluator, ctx)
        assert "extracted" in ctx
        assert "shared_text_cache" in ctx

    def test_extracted_contains_all_pages(self):
        evaluator = MagicMock()
        evaluator._extract_structured_signals.return_value = {"has_waitlist_signal": False}
        homepage = _make_fetch_result()
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "all_pages": {homepage.final_url: homepage},
        }
        step_extract_signals(evaluator, ctx)
        evaluator._extract_structured_signals.assert_called_once()


class TestStepClassifyTaxonomy:
    """step_classify_taxonomy taxonomy 분류 검증."""

    def test_sets_taxonomy_in_extracted(self):
        evaluator = MagicMock()
        evaluator._classify_taxonomy.return_value = {"primary_category": "AI Chatbot", "taxonomy_skipped": False, "primary_confidence": 0.8}
        homepage = _make_fetch_result()
        extracted: dict = {}
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "all_pages": {homepage.final_url: homepage},
            "extracted": extracted,
        }
        step_classify_taxonomy(evaluator, ctx)
        assert "taxonomy" in extracted


class TestStepAssessAiScope:
    """step_assess_ai_scope AI scope 판정 검증."""

    def test_sets_ai_scope_in_extracted(self):
        evaluator = MagicMock()
        evaluator._classify_ai_scope.return_value = {"is_ai_site": True, "scope_decision": "ai", "confidence": 0.9}
        homepage = _make_fetch_result()
        extracted: dict = {}
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "all_pages": {homepage.final_url: homepage},
            "extracted": extracted,
        }
        step_assess_ai_scope(evaluator, ctx)
        assert "ai_scope" in extracted
        assert extracted["ai_scope"]["is_ai_site"] is True


class TestStepEvaluateCriteria:
    """step_evaluate_criteria 품질 기준 평가 검증."""

    def test_sets_criteria_and_counts(self):
        evaluator = MagicMock()
        evaluator.config = EvalConfig()
        evaluator._build_criteria.return_value = _make_full_criteria(all_pass=True)
        homepage = _make_fetch_result()
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "all_pages": {homepage.final_url: homepage},
            "extracted": {},
        }
        step_evaluate_criteria(evaluator, ctx)
        assert ctx["passed_count"] == 5
        assert ctx["hard_pass"] is True

    def test_hard_pass_false_when_criteria_fail(self):
        evaluator = MagicMock()
        evaluator.config = EvalConfig()
        criteria = _make_full_criteria(all_pass=False)
        evaluator._build_criteria.return_value = criteria
        homepage = _make_fetch_result()
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "all_pages": {},
            "extracted": {},
        }
        step_evaluate_criteria(evaluator, ctx)
        assert ctx["passed_count"] == 0
        assert ctx["hard_pass"] is False


class TestStepScoreAndPredictStatus:
    """step_score_and_predict_status 상태 예측 검증."""

    def test_sets_predicted_status(self):
        evaluator = MagicMock()
        evaluator.config = EvalConfig()
        evaluator._build_score_context.return_value = {"total_score": 90.0, "criterion_scores": {}}
        evaluator._predict_status.return_value = "curated"
        homepage = _make_fetch_result()
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "extracted": {},
            "criteria": _make_full_criteria(),
            "passed_count": 5,
            "hard_pass": True,
        }
        step_score_and_predict_status(evaluator, ctx)
        assert ctx["predicted_status"] == "curated"
        assert "score_context" in ctx

    def test_anti_bot_upgrades_rejected_to_incubating(self):
        evaluator = MagicMock()
        evaluator.config = EvalConfig()
        evaluator._build_score_context.return_value = {"total_score": 0.0, "criterion_scores": {}}
        evaluator._predict_status.return_value = "rejected"
        homepage = _make_fetch_result(ok=False)
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "extracted": {"anti_bot_blocked": True},
            "criteria": _make_full_criteria(all_pass=False),
            "passed_count": 0,
            "hard_pass": False,
        }
        step_score_and_predict_status(evaluator, ctx)
        assert ctx["predicted_status"] == "incubating"


class TestStepReviewAndFinalizeStatus:
    """step_review_and_finalize_status 최종 상태 확정 검증."""

    def test_final_status_equals_predicted_when_no_review(self):
        evaluator = MagicMock()
        evaluator.config = EvalConfig()
        evaluator._review_gate.return_value = (False, [])
        homepage = _make_fetch_result()
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "extracted": {},
            "criteria": _make_full_criteria(),
            "predicted_status": "incubating",
        }
        step_review_and_finalize_status(evaluator, ctx)
        assert ctx["final_status"] == "incubating"
        assert ctx["review_required"] is False

    def test_curated_downgrades_to_incubating_when_review_required(self):
        evaluator = MagicMock()
        evaluator.config = EvalConfig(curated_requires_no_review=True)
        evaluator._review_gate.return_value = (True, ["missing docs"])
        homepage = _make_fetch_result()
        ctx = {
            "normalized_url": "https://example.com",
            "homepage": homepage,
            "extracted": {},
            "criteria": _make_full_criteria(),
            "predicted_status": "curated",
        }
        step_review_and_finalize_status(evaluator, ctx)
        assert ctx["final_status"] == "incubating"


class TestStepBuildSummary:
    """step_build_summary 요약 문자열 생성 검증."""

    def test_sets_summary_in_context(self):
        evaluator = MagicMock()
        evaluator._build_summary.return_value = "총 5/5개 기준 충족."
        ctx = {
            "criteria": _make_full_criteria(),
            "predicted_status": "curated",
            "final_status": "curated",
            "passed_count": 5,
            "review_required": False,
            "review_reasons": [],
            "score_context": {"total_score": 90.0},
        }
        step_build_summary(evaluator, ctx)
        assert ctx["summary"] == "총 5/5개 기준 충족."
