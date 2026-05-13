"""테스트 설정."""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# 테스트 환경 변수 — 실제 외부 API 호출 없이 인증만 통과
os.environ.setdefault("API_KEY", "test-api-key-change-in-production")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

from src.db.models.base import Base
from src.db.session import get_db
from src.main import app


@pytest.fixture(scope="function", autouse=True)
def reset_app():
    """각 테스트 후 FastAPI 의존성 초기화."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def db():
    """독립적인 메모리 DB 세션."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db):
    """테스트 클라이언트."""
    def override_get_db():
        yield db
    
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)
