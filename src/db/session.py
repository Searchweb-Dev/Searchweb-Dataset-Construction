"""데이터베이스 세션 설정."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.core.config import get_db_url

engine = create_engine(
    get_db_url(),
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """DB 세션 생성."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
