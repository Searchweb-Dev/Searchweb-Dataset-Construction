"""분석 작업 요청/응답 스키마."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, HttpUrl, Field

from .site import AISiteResponse


class AnalysisJobRequest(BaseModel):
    """분석 요청 스키마. 단건 또는 다건 URL을 모두 지원한다."""

    urls: list[HttpUrl] = Field(min_length=1, max_length=5, description="분석할 URL 목록 (최대 5개)")
    force_reanalyze: bool = False


class AnalysisJobResponse(BaseModel):
    """분석 작업 응답 스키마."""

    job_id: UUID
    url: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    result: Optional[AISiteResponse] = None

    model_config = {"from_attributes": True}


class BatchAnalysisResponse(BaseModel):
    """배치 분석 응답 스키마."""

    total: int = Field(description="요청된 전체 URL 수")
    accepted: int = Field(description="분석 대상으로 접수된 URL 수")
    message: str = Field(description="배치 작업 접수 안내")


class BatchFilePathRequest(BaseModel):
    """서버 경로 배치 분석 요청 스키마."""

    file_path: str = Field(description="서버 내 분석 대상 파일 경로 (JSON 또는 텍스트)")
    force_reanalyze: bool = False
