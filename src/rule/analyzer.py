"""
규칙기반 URL 분류기를 래핑하는 RuleAnalyzer 모듈.

EvaluationResult를 detector.py가 기대하는 분석 dict로 변환하여 반환한다.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from src.rule.models import CriterionResult, EvaluationResult
from src.rule.pipeline import run_quality_pipeline

logger = logging.getLogger(__name__)

# 카테고리 매핑 테이블: primary_category → (level_1, level_2)
_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "Writing & Docs": ("text", "text-generation"),
    "Coding": ("code", "code-generation"),
    "Research": ("text", "research-assistant"),
    "Design & Creative": ("image", "image-generation"),
    "Data & Analytics": ("data", "data-analysis"),
    "Ops & Automation": ("business", "workflow-automation"),
    "Meeting & Sales": ("business", "meeting-assistant"),
}

_DEFAULT_CATEGORY = ("other", "general")


def _map_primary_category(primary_category: str) -> tuple[str, str]:
    """primary_category 문자열을 (level_1, level_2) 튜플로 변환한다."""
    return _CATEGORY_MAP.get(primary_category, _DEFAULT_CATEGORY)


def _extract_host(url: str) -> str:
    """URL에서 호스트명을 추출한다. 실패 시 원본 URL을 반환한다."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


def _clamp_score(value: int, min_val: int = 1, max_val: int = 10) -> int:
    """정수값을 [min_val, max_val] 범위로 클램프한다."""
    return max(min_val, min(max_val, value))


def _map_to_analysis_dict(result: EvaluationResult, input_url: str) -> dict[str, Any]:
    """EvaluationResult를 detector.py가 기대하는 분석 dict로 변환한다.

    Args:
        result: 파이프라인 실행 완료 객체.
        input_url: 원본 입력 URL (title 폴백용).

    Returns:
        _validate_analysis() 통과 보장 스키마 dict.
    """
    extracted = result.extracted if isinstance(result.extracted, dict) else {}
    ai_scope = extracted.get("ai_scope", {})
    taxonomy = extracted.get("taxonomy", {})

    scope_decision = str(ai_scope.get("scope_decision", "")).lower() if isinstance(ai_scope, dict) else ""
    is_ai_tool = scope_decision in ("ai", "uncertain")

    homepage_title = str(extracted.get("homepage_title", "")).strip()
    if homepage_title:
        title = homepage_title
    else:
        title = _extract_host(input_url) or _extract_host(result.normalized_url) or result.normalized_url

    one_line_summary = str(taxonomy.get("one_line_summary", "")).strip() if isinstance(taxonomy, dict) else ""
    if one_line_summary:
        description = one_line_summary[:50]
    elif homepage_title:
        description = homepage_title[:50]
    else:
        description = ""

    raw_confidence = ai_scope.get("confidence", 0.5) if isinstance(ai_scope, dict) else 0.5
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    categories: list[dict[str, Any]] = []
    taxonomy_skipped = bool(taxonomy.get("taxonomy_skipped")) if isinstance(taxonomy, dict) else True
    if not taxonomy_skipped and isinstance(taxonomy, dict):
        primary_category = str(taxonomy.get("primary_category", "")).strip()
        level_1, level_2 = _map_primary_category(primary_category)
        categories = [
            {
                "level_1": level_1,
                "level_2": level_2,
                "level_3": "",
                "is_primary": True,
            }
        ]

    sub_tasks = taxonomy.get("sub_tasks", []) if isinstance(taxonomy, dict) else []
    tags: list[str] = [str(t) for t in sub_tasks[:3]] if isinstance(sub_tasks, list) else []

    total_score = result.total_score
    if total_score is not None:
        try:
            utility_raw = round(float(total_score) / 10)
        except (TypeError, ValueError):
            utility_raw = 5
    else:
        utility_raw = 5
    score_utility = _clamp_score(utility_raw)

    criteria = result.criteria if isinstance(result.criteria, dict) else {}
    privacy_criterion: CriterionResult | None = criteria.get("has_privacy_or_data_policy")
    if privacy_criterion is not None:
        try:
            trust_raw = round(float(privacy_criterion.confidence) * 10)
        except (TypeError, ValueError):
            trust_raw = 5
    else:
        trust_raw = 5
    score_trust = _clamp_score(trust_raw)

    return {
        "is_ai_tool": is_ai_tool,
        "title": title,
        "description": description,
        "confidence": confidence,
        "categories": categories,
        "tags": tags,
        "scores": {
            "utility": score_utility,
            "trust": score_trust,
            "originality": 5,
        },
        "analyzer": "rule",
        "hard_pass": result.hard_pass,
        "total_score": result.total_score,
        "review_required": result.review_required,
    }


class RuleAnalyzer:
    """규칙기반 8단계 파이프라인을 통해 웹사이트를 분석하는 분석기.

    detector.py의 get_analyzer()에서 반환되며, LLM 분석기와 동일한 인터페이스를 구현한다.
    """

    def analyze_website(self, url: str) -> dict[str, Any]:
        """단일 URL을 규칙기반 파이프라인으로 분석하고 분석 결과 dict를 반환한다.

        Args:
            url: 분석할 웹사이트 URL.

        Returns:
            _validate_analysis() 통과 보장 스키마 dict.
            {
                "is_ai_tool": bool,
                "title": str,
                "description": str,
                "confidence": float,
                "categories": list[dict],
                "tags": list[str],
                "scores": {"utility": int, "trust": int, "originality": int},
                "analyzer": "rule",
            }

        Raises:
            Exception: 파이프라인 실행 중 발생한 예외는 그대로 전파한다.
        """
        logger.info("[RuleAnalyzer] 분석 시작: %s", url)
        result = run_quality_pipeline(url)
        analysis = _map_to_analysis_dict(result, url)
        logger.info(
            "[RuleAnalyzer] 분석 완료: %s → is_ai_tool=%s, confidence=%.2f",
            url,
            analysis["is_ai_tool"],
            analysis["confidence"],
        )
        return analysis
