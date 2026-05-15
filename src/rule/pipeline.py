"""
품질 평가 파이프라인의 단일 URL 진입점을 제공하는 모듈.

CLI 코드, registry I/O, 배치 처리 코드는 포함하지 않는다.
단일 URL 분석 함수 run_quality_pipeline()만 노출한다.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

from src.rule.config import EvalConfig, get_rule_config
from src.rule.classifiers.criteria_evaluator import WeightedQualityEvaluator
from src.rule.fetchers.page_fetcher import PageFetcher
from src.rule.models import DummyLLM, EvaluationResult
from src.rule.utils import lower, normalize_url


PipelineContext = dict[str, Any]
PipelineStep = Callable[[Any, PipelineContext], None]


def _build_shared_text_cache(all_pages: dict[str, Any]) -> dict[str, str]:
    """ai_scope/taxonomy가 공통으로 사용하는 텍스트 블롭 캐시를 생성한다."""

    usable_pages = [p for p in all_pages.values() if getattr(p, "ok", False)]
    page_blobs = [" ".join([p.final_url, p.title, p.meta_description, p.text[:5000]]) for p in usable_pages]
    header_blobs = [" ".join([p.final_url, p.title, p.meta_description]) for p in usable_pages]
    link_blobs = [f"{t} {u}" for p in usable_pages for t, u in p.links[:80]]

    corpus = lower(" ".join(page_blobs))
    header_blob = lower(" ".join(header_blobs))
    links_blob = lower(" ".join(link_blobs))
    ai_scope_blob = lower(" ".join(page_blobs + link_blobs))
    combined_blob = " ".join([corpus, header_blob, links_blob])
    return {
        "corpus": corpus,
        "header_blob": header_blob,
        "links_blob": links_blob,
        "combined_blob": combined_blob,
        "ai_scope_blob": ai_scope_blob,
    }


def step_fetch_and_collect_pages(evaluator: Any, ctx: PipelineContext) -> None:
    """홈페이지와 후보 페이지를 수집해 컨텍스트에 적재한다."""
    normalized_url = ctx["normalized_url"]
    logger.info("[%s] 페이지 수집 시작", normalized_url)

    homepage = evaluator.fetcher.fetch(normalized_url)
    if not homepage.ok:
        logger.warning("[%s] 홈페이지 수집 실패: %s", normalized_url, homepage.error)
    else:
        logger.info("[%s] 홈페이지 수집 성공 (fetched_by=%s)", normalized_url, homepage.fetched_by)

    candidate_urls = evaluator._collect_candidate_urls(normalized_url, homepage)
    if candidate_urls:
        logger.info("[%s] 후보 페이지 %d개 발견, 수집 시작", normalized_url, len(candidate_urls))

    candidate_workers = evaluator.config.candidate_fetch_workers
    if (
        evaluator.config.auto_tune_nested_parallel
        and evaluator.config.parallel_url_evaluation
        and evaluator.config.url_evaluation_workers > 1
    ):
        tuned_workers = max(1, candidate_workers // evaluator.config.url_evaluation_workers)
        if tuned_workers == 1 and candidate_workers > 1 and len(candidate_urls) > 1:
            tuned_workers = 2
        candidate_workers = tuned_workers

    if candidate_urls and evaluator.config.parallel_candidate_fetch and candidate_workers > 1:
        fetched_candidates = evaluator.fetcher.fetch_many(
            candidate_urls,
            max_workers=candidate_workers,
            lightweight=evaluator.config.candidate_lightweight_fetch,
        )
    else:
        fetched_candidates = {
            u: evaluator.fetcher.fetch(u, lightweight=evaluator.config.candidate_lightweight_fetch)
            for u in candidate_urls
        }

    all_pages: dict[str, Any] = {}
    all_pages[homepage.final_url] = homepage
    for result in fetched_candidates.values():
        all_pages[result.final_url] = result

    ctx["homepage"] = homepage
    ctx["all_pages"] = all_pages
    logger.info("[%s] 페이지 수집 완료 (총 %d개 페이지)", normalized_url, len(all_pages))


def step_extract_signals(evaluator: Any, ctx: PipelineContext) -> None:
    """수집된 페이지들에서 구조화 신호(extracted)를 추출한다."""
    normalized_url = ctx["normalized_url"]
    logger.info("[%s] 구조화 신호 추출 중...", normalized_url)
    homepage = ctx["homepage"]
    all_pages = ctx["all_pages"]
    extracted = evaluator._extract_structured_signals(homepage, list(all_pages.values()))
    ctx["shared_text_cache"] = _build_shared_text_cache(all_pages)
    ctx["extracted"] = extracted


def step_classify_taxonomy(evaluator: Any, ctx: PipelineContext) -> None:
    """추출 결과에 taxonomy 분류 결과를 추가한다."""
    normalized_url = ctx["normalized_url"]
    homepage = ctx["homepage"]
    all_pages = ctx["all_pages"]
    extracted = ctx["extracted"]
    shared_text_cache = ctx.get("shared_text_cache")

    logger.info("[%s] Taxonomy 분류 시작", normalized_url)
    taxonomy = evaluator._classify_taxonomy(homepage, all_pages, extracted, text_cache=shared_text_cache)
    extracted["taxonomy"] = taxonomy

    if not taxonomy.get("taxonomy_skipped"):
        logger.info("[%s] Taxonomy 분류 완료: %s (conf=%.2f)",
                    normalized_url, taxonomy.get("primary_category"), taxonomy.get("primary_confidence", 0))


def step_assess_ai_scope(evaluator: Any, ctx: PipelineContext) -> None:
    """평가 대상이 AI 사이트인지 스코프 게이트를 판정한다."""
    normalized_url = ctx["normalized_url"]
    homepage = ctx["homepage"]
    all_pages = ctx["all_pages"]
    extracted = ctx["extracted"]
    shared_text_cache = ctx.get("shared_text_cache")

    logger.info("[%s] AI Scope 판정 중...", normalized_url)
    ai_scope = evaluator._classify_ai_scope(homepage, all_pages, text_cache=shared_text_cache)
    extracted["ai_scope"] = ai_scope
    logger.info("[%s] AI Scope 판정 완료: %s (conf=%.2f)",
                normalized_url, ai_scope.get("scope_decision"), ai_scope.get("confidence", 0))


def step_evaluate_criteria(evaluator: Any, ctx: PipelineContext) -> None:
    """품질 기준 평가 결과와 통과 집계를 계산한다."""
    normalized_url = ctx["normalized_url"]
    logger.info("[%s] 품질 지표(Criteria) 평가 시작", normalized_url)
    homepage = ctx["homepage"]
    all_pages = ctx["all_pages"]
    extracted = ctx["extracted"]
    criteria = evaluator._build_criteria(homepage, all_pages, extracted)
    passed_count = sum(1 for c in criteria.values() if c.passed)
    hard_pass = all(criteria[name].passed for name in evaluator.config.hard_criteria)

    ctx["criteria"] = criteria
    ctx["passed_count"] = passed_count
    ctx["hard_pass"] = hard_pass
    logger.info("[%s] 품질 평가 완료: %d/5 통과 (hard_pass=%s)", normalized_url, passed_count, hard_pass)


def step_score_and_predict_status(evaluator: Any, ctx: PipelineContext) -> None:
    """점수 컨텍스트를 만들고 상태를 1차 예측한다."""
    normalized_url = ctx["normalized_url"]
    homepage = ctx["homepage"]
    extracted = ctx["extracted"]
    criteria = ctx["criteria"]
    passed_count = ctx["passed_count"]
    hard_pass = ctx["hard_pass"]

    score_context = evaluator._build_score_context(criteria)
    predicted_status = evaluator._predict_status(criteria, passed_count, hard_pass, score_context)
    total_score = float(score_context.get("total_score", 0.0))

    if bool(extracted.get("anti_bot_blocked")) and not homepage.ok and passed_count == 0 and predicted_status == "rejected":
        predicted_status = "incubating"
        logger.info("[%s] Anti-bot 차단 감지되어 rejected -> incubating 완충 적용", normalized_url)

    ctx["score_context"] = score_context
    ctx["predicted_status"] = predicted_status
    logger.info("[%s] 상태 예측: %s (Score: %.1f)", normalized_url, predicted_status, total_score)


def step_review_and_finalize_status(evaluator: Any, ctx: PipelineContext) -> None:
    """리뷰 게이트를 적용해 최종 상태와 검수 사유를 확정한다."""
    normalized_url = ctx["normalized_url"]
    homepage = ctx["homepage"]
    extracted = ctx["extracted"]
    criteria = ctx["criteria"]
    predicted_status = ctx["predicted_status"]

    review_required, review_reasons = evaluator._review_gate(criteria, homepage, extracted, predicted_status)
    final_status = predicted_status

    if predicted_status == "curated" and evaluator.config.curated_requires_no_review and review_required:
        final_status = "incubating"
        if "curated 후보였지만 수동 검수 전 보류" not in review_reasons:
            review_reasons.append("curated 후보였지만 수동 검수 전 보류")
        logger.info("[%s] Curated 후보이나 리뷰 필요 사유로 인해 incubating으로 조정", normalized_url)

    ctx["review_required"] = review_required
    ctx["review_reasons"] = review_reasons
    ctx["final_status"] = final_status
    logger.info("[%s] 최종 상태 확정: %s (Review Required: %s)", normalized_url, final_status, review_required)


def step_build_summary(evaluator: Any, ctx: PipelineContext) -> None:
    """최종 결과 요약 문자열을 생성한다."""
    summary = evaluator._build_summary(
        ctx["criteria"],
        ctx["predicted_status"],
        ctx["final_status"],
        ctx["passed_count"],
        ctx["review_required"],
        ctx["review_reasons"],
        ctx.get("score_context", {}),
    )
    ctx["summary"] = summary


DEFAULT_PIPELINE_STEPS: list[PipelineStep] = [
    step_fetch_and_collect_pages,
    step_extract_signals,
    step_assess_ai_scope,
    step_classify_taxonomy,
    step_evaluate_criteria,
    step_score_and_predict_status,
    step_review_and_finalize_status,
    step_build_summary,
]


def run_quality_pipeline(
    url: str,
    config: EvalConfig | None = None,
) -> EvaluationResult:
    """단일 URL에 대해 전체 품질 평가 파이프라인을 실행하고 EvaluationResult를 반환한다.

    Args:
        url: 분석할 웹사이트 URL.
        config: 파이프라인 설정. None이면 기본 EvalConfig()를 사용한다.

    Returns:
        EvaluationResult 객체.

    Raises:
        Exception: 파이프라인 실행 중 발생한 예외는 그대로 전파한다.
    """
    runtime_config = config or get_rule_config()
    fetcher = PageFetcher(runtime_config)
    evaluator = WeightedQualityEvaluator(fetcher=fetcher, config=runtime_config, llm=None)
    evaluator.set_pipeline_steps(DEFAULT_PIPELINE_STEPS)
    try:
        return evaluator.evaluate(url)
    finally:
        fetcher.close()
