"""AI 사이트 응답 스키마."""

from datetime import datetime
from pydantic import BaseModel, Field


class CategoryResponse(BaseModel):
    """카테고리 분류 스키마."""

    level_1: str
    level_2: str
    level_3: str | None = None
    is_primary: bool = False

    model_config = {"from_attributes": True}


class ScoreResponse(BaseModel):
    """점수 스키마."""

    utility: int | None = Field(None, ge=1, le=10)
    trust: int | None = Field(None, ge=1, le=10)
    originality: int | None = Field(None, ge=1, le=10)


class AISiteResponse(BaseModel):
    """AI 사이트 분석 결과 스키마."""

    site_id: int
    url: str
    is_ai_tool: bool
    title: str | None = None
    description: str | None = None
    categories: list[CategoryResponse] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    scores: ScoreResponse = Field(default_factory=ScoreResponse)
    analyzer: str | None = None
    last_analyzed_at: datetime | None = None

    model_config = {"from_attributes": True}
