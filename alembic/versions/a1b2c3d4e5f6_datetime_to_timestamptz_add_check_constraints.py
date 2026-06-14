"""DateTime → TIMESTAMPTZ 변환 및 CHECK 제약조건 추가

Revision ID: a1b2c3d4e5f6
Revises: 80b30e8e3a59
Create Date: 2026-06-14 00:00:00.000000

변경 내용:
  1. 모든 테이블의 DateTime 컬럼을 TIMESTAMPTZ(timezone=True)로 변환
  2. ai_site: ck_ai_site_status CHECK 제약조건 추가
  3. analysis_job: ck_analysis_job_status CHECK 제약조건 추가
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '80b30e8e3a59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# DateTime 컬럼 목록: (테이블, 컬럼, nullable, comment)
_DATETIME_COLUMNS = [
    ('ai_site', 'created_at', False, '레코드 생성 시각 (UTC)'),
    ('ai_site', 'updated_at', False, '레코드 최종 수정 시각 (UTC)'),
    ('ai_site', 'deleted_at', True, '소프트 삭제 시각 (NULL이면 유효 레코드)'),
    ('ai_site', 'last_analyzed_at', True, '마지막 분석 완료 시각 (UTC)'),
    ('ai_site', 'unreachable_since', True, '접근 불가 최초 감지 시각 (UTC). NULL이면 접근 가능 상태.'),
    ('ai_category', 'created_at', False, '레코드 생성 시각 (UTC)'),
    ('ai_category', 'updated_at', False, '레코드 최종 수정 시각 (UTC)'),
    ('ai_category', 'deleted_at', True, '소프트 삭제 시각 (NULL이면 유효 레코드)'),
    ('ai_tag', 'created_at', False, '레코드 생성 시각 (UTC)'),
    ('ai_tag', 'updated_at', False, '레코드 최종 수정 시각 (UTC)'),
    ('ai_tag', 'deleted_at', True, '소프트 삭제 시각 (NULL이면 유효 레코드)'),
    ('analysis_job', 'created_at', False, '레코드 생성 시각 (UTC)'),
    ('analysis_job', 'updated_at', False, '레코드 최종 수정 시각 (UTC)'),
    ('analysis_job', 'deleted_at', True, '소프트 삭제 시각 (NULL이면 유효 레코드)'),
    ('analysis_job', 'started_at', True, '작업 시작 시각 (UTC)'),
    ('analysis_job', 'completed_at', True, '작업 완료 시각 (UTC)'),
]


def upgrade() -> None:
    """Upgrade schema."""
    # 1. DateTime → TIMESTAMPTZ 변환
    for table, column, nullable, comment in _DATETIME_COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            existing_nullable=nullable,
            comment=comment,
            postgresql_using=f'{column} AT TIME ZONE \'UTC\'',
        )

    # 2. ai_site CHECK 제약조건
    op.create_check_constraint(
        'ck_ai_site_status',
        'ai_site',
        "status IN ('ok', 'unreachable', 'blocked', 'failure')",
    )

    # 3. analysis_job CHECK 제약조건
    op.create_check_constraint(
        'ck_analysis_job_status',
        'analysis_job',
        "status IN ('pending', 'processing', 'success', 'failed')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    # CHECK 제약조건 제거
    op.drop_constraint('ck_analysis_job_status', 'analysis_job', type_='check')
    op.drop_constraint('ck_ai_site_status', 'ai_site', type_='check')

    # TIMESTAMPTZ → DateTime 롤백
    for table, column, nullable, comment in _DATETIME_COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=nullable,
            comment=comment,
            postgresql_using=f'{column} AT TIME ZONE \'UTC\'',
        )
