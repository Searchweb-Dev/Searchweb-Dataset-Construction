"""FastAPI 메인 앱."""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import analyze_routes, job_routes, rule_routes
from src.core.config import get_allowed_origins
from src.db.models.base import Base
from src.db.session import engine

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="AI Site Detection Worker",
    version="0.1.0",
    description="Claude + MCP 기반 AI 웹사이트 판별 Worker",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_routes.router, prefix="/api/v1/analyze", tags=["analyze"])
app.include_router(rule_routes.router, prefix="/api/v1/rule", tags=["rule"])
app.include_router(job_routes.router, prefix="/api/v1/jobs", tags=["jobs"])


@app.on_event("startup")
async def startup() -> None:
    """앱 시작 시 DB 테이블 생성."""
    Base.metadata.create_all(bind=engine)


@app.get("/health", tags=["health"])
def health_check():
    """헬스 체크."""
    return {"status": "ok"}
