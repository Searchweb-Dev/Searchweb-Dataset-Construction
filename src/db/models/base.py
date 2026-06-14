"""공통 베이스 ORM 모델."""

from sqlalchemy import Column, Integer, DateTime, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class BaseModel(Base):
    """모든 ORM 테이블에 공통으로 적용되는 감시 컬럼."""

    __abstract__ = True

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False,
                        comment="레코드 생성 시각 (UTC)")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
                        comment="레코드 최종 수정 시각 (UTC)")
    deleted_at = Column(DateTime(timezone=True), nullable=True, default=None,
                        comment="소프트 삭제 시각 (NULL이면 유효 레코드)")
    created_by_member_id = Column(Integer, nullable=True,
                                  comment="생성한 회원 ID")
    updated_by_member_id = Column(Integer, nullable=True,
                                  comment="최종 수정한 회원 ID")
    deleted_by_member_id = Column(Integer, nullable=True,
                                  comment="삭제한 회원 ID")
