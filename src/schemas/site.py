"""AI 사이트 응답 스키마."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class CategoryResponse(BaseModel):
    """카테고리 분류 스키마."""

    level_1: str
    level_2: str
    level_3: Optional[str] = None
    is_primary: bool = False

    model_config = {"from_attributes": True}


class ScoreResponse(BaseModel):
    """점수 스키마."""

    utility: Optional[int] = Field(None, ge=0, le=10)
    trust: Optional[int] = Field(None, ge=0, le=10)
    originality: Optional[int] = Field(None, ge=0, le=10)


class AISiteResponse(BaseModel):
    """AI 사이트 분석 결과 스키마."""

    site_id: int
    url: str
    is_ai_tool: bool
    title: Optional[str] = None
    description: Optional[str] = None
    categories: list[CategoryResponse] = []
    tags: list[str] = []
    scores: ScoreResponse = ScoreResponse()
    analyzer: Optional[str] = None
    last_analyzed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
