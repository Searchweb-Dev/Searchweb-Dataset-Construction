"""
평가 결과 표현용 데이터 모델과 LLM 인터페이스를 정의하는 모듈.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.rule.keywords import ACTION_KEYWORDS, TASK_NOUNS
from src.rule.utils import lower


@dataclass
class Evidence:
    """개별 판정 근거(출처 URL, 스니펫, 라벨)를 표현한다."""
    url: str
    snippet: str
    label: str


@dataclass
class CriterionResult:
    """단일 품질 기준의 판정 결과를 표현한다."""
    name: str
    passed: bool
    reason: str
    confidence: float = 1.0
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class FetchResult:
    """페이지 fetch 결과(상태코드, 본문, 링크, 에러 등)를 담는다."""
    url: str
    final_url: str
    status_code: int
    ok: bool
    html: str
    text: str
    title: str
    meta_description: str
    links: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None
    fetched_by: str = "requests"


@dataclass
class EvaluationResult:
    """단일 URL 평가의 최종 출력 구조를 담는다."""
    input_url: str
    normalized_url: str
    predicted_status: str
    final_status: str
    passed_count: int
    hard_pass: bool
    review_required: bool
    review_reasons: list[str]
    criteria: dict[str, CriterionResult]
    summary: str
    extracted: dict[str, object]
    total_score: float | None = None
    score_breakdown: dict[str, float] | None = None
    management: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """결과를 JSON 직렬화 가능한 dict 형태로 변환한다."""
        out = {
            "input_url": self.input_url,
            "normalized_url": self.normalized_url,
            "predicted_status": self.predicted_status,
            "final_status": self.final_status,
            "passed_count": self.passed_count,
            "hard_pass": self.hard_pass,
        }
        if self.total_score is not None:
            out["total_score"] = round(self.total_score, 2)
        if self.score_breakdown is not None:
            out["score_breakdown"] = {k: round(v, 2) for k, v in self.score_breakdown.items()}
        out["review_required"] = self.review_required
        out["review_reasons"] = self.review_reasons
        out["criteria"] = {
            k: {
                "name": v.name,
                "passed": v.passed,
                "reason": v.reason,
                "confidence": v.confidence,
                "evidence": [asdict(e) for e in v.evidence],
            }
            for k, v in self.criteria.items()
        }
        out["summary"] = self.summary
        out["extracted"] = self.extracted
        if self.management is not None:
            out["management"] = self.management
        return out


class ClearDescriptionLLM:
    """기능 설명 명확성 판정용 LLM 인터페이스."""

    def evaluate(self, payload: dict[str, str]) -> dict[str, object]:
        """입력 payload를 받아 기능 설명 판정 결과를 반환한다."""
        raise NotImplementedError


class DummyLLM(ClearDescriptionLLM):
    """LLM 연동 전 테스트용 휴리스틱 스텁 구현체."""

    def evaluate(self, payload: dict[str, str]) -> dict[str, object]:
        """간단한 키워드 매칭으로 기능 설명 명확성을 추정한다."""
        candidate = lower(payload.get("candidate_sentence", ""))
        passed = any(k in candidate for k in ACTION_KEYWORDS) and any(k in candidate for k in TASK_NOUNS)
        return {
            "passed": passed,
            "confidence": 0.72 if passed else 0.45,
            "reason": "LLM 스텁 판정",
            "summary": payload.get("candidate_sentence", ""),
        }
