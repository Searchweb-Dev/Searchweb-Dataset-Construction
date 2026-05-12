"""FastAPI 메인 앱."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.db.models.base import Base
from src.db.session import engine
from src.api import routes
from src.core.config import get_allowed_origins

app = FastAPI(
    title="AI Site Detection Worker",
    version="0.1.0",
    description="Claude + MCP 기반 AI 웹사이트 판별 Worker"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router, prefix="/api/v1")


@app.on_event("startup")
async def startup() -> None:
    """앱 시작 시 DB 테이블 생성."""
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health_check():
    """헬스 체크."""
    return {"status": "ok"}
