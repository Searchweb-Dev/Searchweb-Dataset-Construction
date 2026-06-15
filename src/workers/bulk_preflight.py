"""bulk 분석 사전 판별 — 스킵 여부 결정 및 Job 레코드 일괄 생성."""

import logging
from uuid import UUID, uuid4

from src.db.models import AnalysisJob, AISite
from src.db.session import SessionLocal
from src.core.enums import JobStatus
from src.core.url import normalize_url
from src.workers.job_status import is_failed_analysis
from src.db.models.ai_site import SITE_STATUS_UNREACHABLE
from src.core.config import get_unreachable_ttl_seconds
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _is_unreachable_blocked(site: AISite) -> bool:
    """접근 불가 TTL 이내인지 확인한다."""
    if site.status != SITE_STATUS_UNREACHABLE or site.unreachable_since is None:
        return False
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    elapsed = (now_naive - site.unreachable_since).total_seconds()
    return elapsed < get_unreachable_ttl_seconds()


def prepare_bulk_urls(
    urls: list[str],
    force_reanalyze: bool,
) -> tuple[list[str], int, dict[str, UUID]]:
    """스킵 대상을 제외한 분석 대상 URL 목록과 Job ID 맵을 반환한다.

    Returns:
        (pending_urls, skipped_count, job_id_map)
    """
    pending_urls: list[str] = []
    skipped = 0
    job_id_map: dict[str, UUID] = {}

    db = SessionLocal()
    try:
        normalized_urls = [normalize_url(u) for u in urls]
        if not force_reanalyze:
            existing_map: dict[str, AISite] = {
                row.url: row
                for row in db.query(AISite).filter(AISite.url.in_(normalized_urls)).all()
            }
            for url in normalized_urls:
                ex = existing_map.get(url)
                if ex and _is_unreachable_blocked(ex):
                    skipped += 1
                    logger.warning("접근 불가 TTL 이내 — 분석 스킵: %s", url)
                elif ex and is_failed_analysis(ex):
                    logger.warning("이전 분석이 실패 상태입니다. 재분석합니다: %s (status=%r)", url, ex.status)
                    pending_urls.append(url)
                elif ex and ex.analyzer in (None, "rule"):
                    logger.info("rule 분류 결과를 LLM으로 재분석합니다: %s (analyzer=%s)", url, ex.analyzer)
                    pending_urls.append(url)
                elif ex:
                    skipped += 1
                    logger.debug("분석 스킵 (LLM 캐시, analyzer=%s): %s", ex.analyzer, url)
                else:
                    pending_urls.append(url)
        else:
            pending_urls = [normalize_url(u) for u in urls]

        for url in pending_urls:
            job = AnalysisJob(
                job_id=uuid4(),
                url=url,
                status=JobStatus.PENDING,
                retry_count=0,
                request_source="batch_ai_tools",
            )
            db.add(job)
            db.flush()
            job_id_map[url] = job.job_id
        db.commit()
    finally:
        db.close()

    return pending_urls, skipped, job_id_map
