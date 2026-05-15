"""AI 웹사이트 ORM 모델."""

from sqlalchemy import Column, BigInteger, String, Boolean, Text, Integer, Float, DateTime, CheckConstraint
from .base import BaseModel

# 접근 불가 URL 재시도 대기 기간 (초). 이 기간이 지나면 재분석 대상으로 전환된다.
UNREACHABLE_TTL_SECONDS = 7 * 24 * 3600

# ai_site.status 허용 값
SITE_STATUS_OK = "ok"
SITE_STATUS_UNREACHABLE = "unreachable"
SITE_STATUS_BLOCKED = "blocked"
SITE_STATUS_FAILURE = "failure"


class AISite(BaseModel):
    """분석된 AI 서비스 웹사이트 정보."""

    __tablename__ = "ai_site"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'unreachable', 'blocked', 'failure')",
            name="ck_ai_site_status",
        ),
    )

    site_id = Column(BigInteger, primary_key=True, autoincrement=True,
                     comment="사이트 고유 식별자")
    title = Column(String(255), nullable=True,
                   comment="사이트 제목")
    url = Column(String(2048), nullable=False, unique=True, index=True,
                 comment="정규화된 사이트 URL (유니크)")
    analyzer = Column(String(50), nullable=True,
                      comment="분석에 사용된 분석기 종류 (rule / gemini 등)")
    is_ai_tool = Column(Boolean, nullable=False, index=True,
                        comment="AI 도구 여부")
    description = Column(Text, nullable=True,
                         comment="사이트 기능 요약 설명")
    score_utility = Column(Integer, nullable=True,
                           comment="유용성 점수 (1–10)")
    score_trust = Column(Integer, nullable=True,
                         comment="신뢰성 점수 (1–10)")
    score_originality = Column(Integer, nullable=True,
                               comment="독창성 점수 (1–10)")
    total_score = Column(Float, nullable=True,
                         comment="규칙기반 파이프라인 종합 점수 (0–100)")
    hard_pass = Column(Boolean, nullable=True,
                       comment="필수 품질 기준 전체 통과 여부")
    review_required = Column(Boolean, nullable=True,
                             comment="수동 검수 필요 여부")
    last_analyzed_at = Column(DateTime, nullable=True, index=True,
                              comment="마지막 분석 완료 시각 (UTC)")
    status = Column(String(20), nullable=True, index=True,
                    comment="분석 상태 (ok / unreachable / blocked / failure). NULL은 미분류.")
    unreachable_since = Column(DateTime, nullable=True,
                               comment="400 접근 불가 최초 감지 시각 (UTC). NULL이면 접근 가능 상태.")
