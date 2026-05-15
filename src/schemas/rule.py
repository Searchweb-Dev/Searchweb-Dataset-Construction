"""규칙기반 분류기 요청/응답 스키마."""

from typing import Any

from pydantic import BaseModel, HttpUrl


class RuleClassifyRequest(BaseModel):
    """규칙기반 분류 요청 스키마."""

    url: HttpUrl


class CriterionResponse(BaseModel):
    """단일 품질 기준 판정 결과 스키마."""

    name: str
    passed: bool
    reason: str
    confidence: float
    evidence: list[dict[str, str]] = []


class RuleClassifyResponse(BaseModel):
    """규칙기반 분류 결과 스키마."""

    site_id: int | None = None
    input_url: str
    normalized_url: str
    predicted_status: str
    final_status: str
    passed_count: int
    hard_pass: bool
    total_score: float | None = None
    score_breakdown: dict[str, float] | None = None
    review_required: bool
    review_reasons: list[str]
    criteria: dict[str, CriterionResponse] = {}
    summary: str
    extracted: dict[str, Any] = {}
