"""규칙기반 URL 분류 API 라우트."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.ai.detector import AIDetector
from src.api.deps import verify_api_key
from src.core.url import normalize_url
from src.db.models import AISite
from src.db.session import get_db
from src.rule.analyzer import RuleAnalyzer
from src.rule.models import EvaluationResult
from src.rule.pipeline import run_quality_pipeline
from src.schemas.rule import CriterionResponse, RuleClassifyRequest, RuleClassifyResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# 규칙기반 캐시를 신뢰할 최소 total_score 임계값
_CACHE_SCORE_THRESHOLD: float = 60.0


def _is_trustworthy_rule_cache(site: AISite) -> bool:
    """저장된 규칙기반 결과가 재분석을 생략해도 충분히 신뢰할 수 있는지 판단한다.

    hard_pass=True, review_required=False, total_score >= 임계값을 모두 만족해야 한다.
    """
    return (
        site.hard_pass is True
        and site.review_required is False
        and site.total_score is not None
        and site.total_score >= _CACHE_SCORE_THRESHOLD
    )


def _build_cached_response(site: AISite, url: str) -> RuleClassifyResponse:
    """DB에 저장된 AISite로부터 RuleClassifyResponse를 구성한다.

    criteria 상세 결과는 DB에 저장되지 않으므로 빈 dict로 반환한다.
    """
    normalized = site.url
    is_ai = site.is_ai_tool
    final_status = "curated" if is_ai else "rejected"

    return RuleClassifyResponse(
        site_id=site.site_id,
        input_url=url,
        normalized_url=normalized,
        predicted_status=final_status,
        final_status=final_status,
        passed_count=0,
        hard_pass=bool(site.hard_pass),
        total_score=site.total_score,
        score_breakdown=None,
        review_required=bool(site.review_required),
        review_reasons=[],
        criteria={},
        summary="캐시된 분석 결과 반환",
        extracted={},
    )


@router.post("/classify", response_model=RuleClassifyResponse)
def classify(
    request: RuleClassifyRequest,
    api_key: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> RuleClassifyResponse:
    """단일 URL을 규칙기반 파이프라인으로 분류하고 결과를 DB에 저장한다.

    DB에 이미 충분히 신뢰할 수 있는 결과가 있으면 파이프라인을 실행하지 않고
    저장된 결과를 반환한다. LLM 분석기(analyzer != 'rule') 결과가 있으면
    규칙 파이프라인 없이 그대로 반환한다.

    Args:
        request: 분류할 URL을 담은 요청 객체.
        api_key: API 키 검증 의존성.
        db: DB 세션 의존성.

    Returns:
        파이프라인 평가 결과 (site_id 포함).

    Raises:
        HTTPException 422: URL 형식 오류.
        HTTPException 500: 파이프라인 실행 또는 DB 저장 중 예외 발생.
    """
    url = normalize_url(str(request.url))
    logger.info("[rule/classify] 요청 수신: %s", url)

    existing = db.query(AISite).filter(AISite.url == url).first()

    if existing is not None:
        # LLM 분석 결과가 있으면 규칙 파이프라인 없이 반환
        if existing.analyzer != "rule":
            logger.info(
                "[rule/classify] LLM 분석 결과 캐시 반환 (analyzer=%s): %s",
                existing.analyzer,
                url,
            )
            return _build_cached_response(existing, url)

        # 규칙기반 결과이고 신뢰 조건을 모두 충족하면 캐시 반환
        if _is_trustworthy_rule_cache(existing):
            logger.info(
                "[rule/classify] 규칙기반 캐시 반환 (score=%.1f): %s",
                existing.total_score or 0.0,
                url,
            )
            return _build_cached_response(existing, url)

        logger.info("[rule/classify] 캐시 신뢰도 미달, 재분석: %s", url)

    # 파이프라인 실행 (상세 결과 확보)
    try:
        pipeline_result = run_quality_pipeline(url)
    except Exception as exc:
        logger.exception("[rule/classify] 파이프라인 실행 실패: %s", url)
        raise HTTPException(status_code=500, detail="분류 중 오류가 발생했습니다.") from exc

    # DB 저장 — RuleAnalyzer를 명시적으로 주입해 CLASSIFIER_MODE와 무관하게 규칙기반으로 저장
    try:
        detector = AIDetector(db, analyzer=RuleAnalyzer())
        saved = detector.detect_and_save(url)
    except Exception as exc:
        logger.exception("[rule/classify] DB 저장 실패: %s", url)
        raise HTTPException(status_code=500, detail="저장 중 오류가 발생했습니다.") from exc

    if saved is None:
        logger.error("[rule/classify] 저장 결과가 None: %s", url)
        raise HTTPException(status_code=500, detail="분류 결과 저장에 실패했습니다.")

    criteria = {
        key: CriterionResponse(
            name=cr.name,
            passed=cr.passed,
            reason=cr.reason,
            confidence=cr.confidence,
            evidence=[{"url": e.url, "snippet": e.snippet, "label": e.label} for e in cr.evidence],
        )
        for key, cr in pipeline_result.criteria.items()
    }

    return RuleClassifyResponse(
        site_id=saved.get("site_id"),
        input_url=pipeline_result.input_url,
        normalized_url=pipeline_result.normalized_url,
        predicted_status=pipeline_result.predicted_status,
        final_status=pipeline_result.final_status,
        passed_count=pipeline_result.passed_count,
        hard_pass=pipeline_result.hard_pass,
        total_score=pipeline_result.total_score,
        score_breakdown=pipeline_result.score_breakdown,
        review_required=pipeline_result.review_required,
        review_reasons=pipeline_result.review_reasons,
        criteria=criteria,
        summary=pipeline_result.summary,
        extracted=pipeline_result.extracted,
    )
