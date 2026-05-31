"""데이터베이스 세션 설정."""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool, StaticPool

from src.core.config import get_db_url

_db_url = get_db_url()

# BATCH_CONCURRENCY + 여유분(5) 이상을 권장. 기본값: 15.
_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "15"))
# 순간 초과 허용 연결 수. 기본값: 10.
_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))

if _db_url.startswith("sqlite"):
    # SQLite: 멀티스레드 환경에서 same-thread 제약 해제.
    # StaticPool은 연결 1개를 공유해 병렬 쓰기 시 "database is locked" 유발 → NullPool로 교체.
    engine = create_engine(
        _db_url,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
else:
    engine = create_engine(
        _db_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=_POOL_SIZE,
        max_overflow=_MAX_OVERFLOW,
        pool_timeout=30,
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """DB 세션 생성."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
