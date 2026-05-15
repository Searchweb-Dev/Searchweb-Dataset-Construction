"""AI 웹사이트 ORM 모델."""

from sqlalchemy import Column, BigInteger, String, Boolean, Text, Integer, Float, DateTime
from .base import BaseModel


class AISite(BaseModel):
    """분석된 AI 서비스 웹사이트 정보."""

    __tablename__ = "ai_site"

    site_id = Column(BigInteger, primary_key=True, autoincrement=True,
                     comment="사이트 고유 식별자")
    title = Column(String(255), nullable=True,
                   comment="사이트 제목")
    url = Column(String(2048), nullable=False, unique=True, index=True,
                 comment="정규화된 사이트 URL (유니크)")
    canonical_url = Column(String(2048), nullable=True,
                           comment="사이트가 선언한 canonical URL")
    analyzer = Column(String(50), nullable=True,
                      comment="분석에 사용된 분석기 종류 (rule / gemini 등)")
    is_ai_tool = Column(Boolean, nullable=False, index=True,
                        comment="AI 도구 여부")
    description = Column(Text, nullable=True,
                         comment="사이트 기능 요약 설명")
    favicon_url = Column(String(2048), nullable=True,
                         comment="파비콘 이미지 URL")
    screenshot_url = Column(String(2048), nullable=True,
                            comment="스크린샷 이미지 URL")
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
