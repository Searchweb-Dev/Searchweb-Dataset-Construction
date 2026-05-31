"""Job DB 상태 갱신 헬퍼."""

import logging
from typing import Any
from uuid import UUID

from src.db.models import AnalysisJob, AISite
from src.db.session import SessionLocal
from src.core.enums import JobStatus
from src.core.util import utc_now
from src.db.models.ai_site import (
    SITE_STATUS_UNREACHABLE,
    SITE_STATUS_BLOCKED,
    SITE_STATUS_FAILURE,
)

logger = logging.getLogger(__name__)


def is_failed_analysis(site: AISite) -> bool:
    """이전 분석이 실패 상태인지 확인."""
    return site.status in (SITE_STATUS_FAILURE, SITE_STATUS_BLOCKED)


def mark_site_status(db: Any, url: str, status: str) -> None:
    """URL의 분석 실패 상태를 DB에 기록한다.

    기존 레코드가 없으면 최소 정보로 새 레코드를 생성한다.
    unreachable의 경우 unreachable_since는 최초 감지 시각을 보존한다.
    """
    now = utc_now()
    site = db.query(AISite).filter(AISite.url == url).first()
    if site:
        site.status = status
        if status == SITE_STATUS_UNREACHABLE and site.unreachable_since is None:
            site.unreachable_since = now
        db.commit()
    else:
        site = AISite(
            url=url,
            is_ai_tool=False,
            status=status,
            unreachable_since=now if status == SITE_STATUS_UNREACHABLE else None,
        )
        db.add(site)
        db.commit()


def update_job_statuses(
    success_map: dict[UUID, int | None],
    failure_map: dict[UUID, str],
) -> None:
    """병렬 분석 완료 후 Job 상태를 세션 하나로 일괄 업데이트한다."""
    db = SessionLocal()
    try:
        all_ids = list(success_map) + list(failure_map)
        jobs = {
            job.job_id: job
            for job in db.query(AnalysisJob).filter(AnalysisJob.job_id.in_(all_ids)).all()
        }
        now = utc_now()
        for job_id, site_id in success_map.items():
            if job := jobs.get(job_id):
                job.status = JobStatus.SUCCESS
                job.site_id = site_id
                job.completed_at = now
        for job_id, error in failure_map.items():
            if job := jobs.get(job_id):
                job.status = JobStatus.FAILED
                job.error_message = error
                job.completed_at = now
        db.commit()
    finally:
        db.close()
