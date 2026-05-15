"""분석 작업 ORM 모델."""

import uuid

from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, Uuid

from .base import BaseModel


class AnalysisJob(BaseModel):
    """AI 사이트 분석 작업 기록."""

    __tablename__ = "analysis_job"

    job_id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
                    comment="작업 고유 식별자 (UUID v4)")
    site_id = Column(BigInteger, ForeignKey("ai_site.site_id"), nullable=True, index=True,
                     comment="분석 완료 후 연결된 사이트 ID (ai_site.site_id 참조)")
    url = Column(String(2048), nullable=False, index=True,
                 comment="분석 요청 URL")
    status = Column(String(20), nullable=False, default="pending", index=True,
                    comment="작업 상태 (pending / processing / success / failed)")
    error_message = Column(Text, nullable=True,
                           comment="실패 시 오류 메시지")
    started_at = Column(DateTime, nullable=True,
                        comment="작업 시작 시각 (UTC)")
    completed_at = Column(DateTime, nullable=True,
                          comment="작업 완료 시각 (UTC)")
    retry_count = Column(Integer, nullable=False, default=0,
                         comment="재시도 횟수")
    request_source = Column(String(50), nullable=True,
                            comment="요청 출처 (예: api, batch, manual)")
