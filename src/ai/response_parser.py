"""Gemini API 응답 파싱 헬퍼."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_WEIGHT_UTILITY = 0.4
_WEIGHT_TRUST = 0.3
_WEIGHT_ORIGINALITY = 0.3
_HARD_PASS_CONFIDENCE_THRESHOLD = 0.8
_REVIEW_CONFIDENCE_THRESHOLD = 0.7
_REVIEW_SCORE_THRESHOLD = 60.0


def default_response() -> dict[str, Any]:
    """파싱 실패 시 기본 응답 구조."""
    return {
        "is_ai_tool": False,
        "title": "Unknown",
        "description": "분석 실패",
        "categories": [],
        "tags": [],
        "scores": {"utility": 0, "trust": 0, "originality": 0},
        "confidence": 0,
        "total_score": 0.0,
        "hard_pass": False,
        "review_required": True,
        "parse_failed": True,
    }


def blocked_response() -> dict[str, Any]:
    """크롤링 차단 사이트용 응답 구조."""
    return {
        "is_ai_tool": False,
        "title": None,
        "description": "크롤링 차단으로 분석 불가",
        "categories": [],
        "tags": [],
        "scores": {"utility": 0, "trust": 0, "originality": 0},
        "confidence": 0,
        "total_score": 0.0,
        "hard_pass": False,
        "review_required": True,
        "anti_bot_blocked": True,
    }


def parse_single(response: Any) -> dict[str, Any]:
    """단건 응답 파싱 — Structured Output이므로 직접 파싱."""
    if not response.candidates:
        logger.warning("Gemini candidate 없음 — 크롤링 차단으로 판단")
        return blocked_response()
    try:
        if response.text:
            return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError):
        pass
    logger.warning("단건 응답 파싱 실패, 기본값 반환")
    return default_response()


def parse_batch(response: Any, urls: list[str]) -> list[dict[str, Any]]:
    """배치 응답 파싱. 길이 불일치 또는 항목 오류 시 기본값으로 보완."""
    results: list[dict[str, Any]] = []
    try:
        if response.text:
            parsed = json.loads(response.text)
            if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
                results = parsed["results"]
            elif isinstance(parsed, list):
                results = parsed
    except (json.JSONDecodeError, AttributeError):
        logger.warning("배치 응답 파싱 실패, 전체 기본값 반환")

    while len(results) < len(urls):
        results.append(default_response())

    for i, result in enumerate(results[:len(urls)]):
        if not isinstance(result, dict) or "is_ai_tool" not in result:
            results[i] = default_response()
        results[i]["analyzer"] = "gemini"

    return results[:len(urls)]


def check_finish_reason(url: str, response: Any) -> None:
    """비정상 종료 여부 로깅."""
    try:
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None:
            block_reason = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
            logger.warning("[%s] Gemini 응답에 candidate가 없습니다. block_reason=%s", url, block_reason)
            return
        finish_reason = candidate.finish_reason
        reason_name = finish_reason.name if finish_reason else "UNKNOWN"
        if reason_name == "MAX_TOKENS":
            logger.warning("[%s] 응답이 max_output_tokens 한도에 도달해 잘렸습니다.", url)
        elif reason_name not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            logger.warning("[%s] 비정상 종료: finish_reason=%s", url, reason_name)
    except Exception as e:
        logger.debug("[%s] finish_reason 확인 중 오류: %s", url, e)


def compute_quality_fields(result: dict[str, Any]) -> dict[str, Any]:
    """Gemini 응답에서 total_score, hard_pass, review_required를 파생한다.

    total_score: scores 가중 평균을 0–100으로 환산
        (utility * 0.4 + trust * 0.3 + originality * 0.3) * 10
    hard_pass: confidence >= 0.8 이고 is_ai_tool=True
    review_required: confidence < 0.7 이거나 (is_ai_tool이고 total_score < 60)
    """
    scores = result.get("scores") or {}
    try:
        utility = float(scores.get("utility") or 0)
        trust = float(scores.get("trust") or 0)
        originality = float(scores.get("originality") or 0)
        total_score = round(
            (utility * _WEIGHT_UTILITY + trust * _WEIGHT_TRUST + originality * _WEIGHT_ORIGINALITY) * 10, 2
        )
    except (TypeError, ValueError):
        total_score = 0.0

    confidence = float(result.get("confidence") or 0)
    is_ai_tool = bool(result.get("is_ai_tool"))

    hard_pass = is_ai_tool and confidence >= _HARD_PASS_CONFIDENCE_THRESHOLD
    review_required = (
        confidence < _REVIEW_CONFIDENCE_THRESHOLD
        or (is_ai_tool and total_score < _REVIEW_SCORE_THRESHOLD)
    )

    return {
        "total_score": total_score,
        "hard_pass": hard_pass,
        "review_required": review_required,
    }
