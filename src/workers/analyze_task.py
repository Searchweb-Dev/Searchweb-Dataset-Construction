"""웹사이트 AI 판별 비동기 작업."""

import itertools
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.db.models import AnalysisJob, AISite
from src.db.session import SessionLocal
from src.ai.analyzer import get_llm_analyzer
from src.db.site_service import AIDetector
from src.workers.celery_app import app
from src.workers.job_status import mark_site_status, update_job_statuses, is_failed_analysis
from src.workers.bulk_preflight import prepare_bulk_urls, _is_unreachable_blocked
from src.core.result_writer import write_batch
from src.core.url import normalize_url
from src.core.util import utc_now
from src.core.error_policy import get_policy
from src.core.exceptions import AnalysisError, SiteUnreachableError
from src.core.error_policy import (
    ApiNotFoundError,
    ApiPreconditionError,
    RateLimitError,
    ApiServerUnavailableError,
    ApiServerInternalError,
    ApiUnauthenticatedError,
    ApiPermissionDeniedError,
    ApiTimeoutError,
)
from src.core.enums import JobStatus
from src.db.models.ai_site import SITE_STATUS_FAILURE

logger = logging.getLogger(__name__)

_BATCH_CONCURRENCY = int(os.getenv("BATCH_CONCURRENCY", "5"))


@app.task(bind=True, max_retries=3, autoretry_for=(), time_limit=300, soft_time_limit=240)
def analyze_url(self, job_id: str, url: str) -> dict[str, Any]:
    """웹사이트 분석 작업 (단건).

    Args:
        job_id: 분석 작업 ID (UUID)
        url: 분석 대상 URL

    Returns:
        분석 결과 딕셔너리
    """
    url = normalize_url(url)
    db = SessionLocal()

    try:
        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == UUID(job_id)).first()
        if not job:
            logger.error("Job을 찾을 수 없음: %s", job_id)
            return {"error": "Job not found"}

        job.status = JobStatus.PROCESSING
        job.started_at = utc_now()
        db.commit()
        logger.info("Job 상태 업데이트 (processing): %s", job_id)

        existing = db.query(AISite).filter(AISite.url == url).first()
        if existing and job.request_source != "force":
            if _is_unreachable_blocked(existing):
                logger.warning("접근 불가 TTL 이내 — 분석 스킵: %s", url)
                job.status = JobStatus.FAILED
                job.completed_at = utc_now()
                job.error_message = "사이트 접근 불가 (TTL 이내 스킵)"
                db.commit()
                return {"job_id": str(job_id), "status": JobStatus.FAILED, "error": "unreachable"}
            elif is_failed_analysis(existing):
                logger.warning(
                    "이전 분석이 실패 상태입니다. 재분석합니다: %s (title=%r, description=%r)",
                    url, existing.title, existing.description,
                )
            elif existing.analyzer == "rule":
                logger.info("rule 분류 결과를 LLM으로 재분석합니다: %s", url)
            else:
                logger.info("캐시에 결과가 있어 결과 파일 쓰기를 건너뜁니다: %s", url)
                job.status = JobStatus.SUCCESS
                job.completed_at = utc_now()
                job.site_id = existing.site_id
                db.commit()
                return {
                    "job_id": str(job_id),
                    "status": JobStatus.SUCCESS,
                    "site_id": existing.site_id,
                    "is_ai_tool": existing.is_ai_tool,
                }

        detector = AIDetector(db, analyzer=get_llm_analyzer())
        result = detector.detect_and_save(url)

        if not result:
            raise AnalysisError("분석 실패")

        job.status = JobStatus.SUCCESS
        job.completed_at = utc_now()
        job.site_id = result.get("site_id")
        db.commit()
        logger.info("분석 완료: %s -> %s", job_id, result)

        return {
            "job_id": str(job_id),
            "status": JobStatus.SUCCESS,
            "site_id": result.get("site_id"),
            "is_ai_tool": result.get("is_ai_tool"),
        }

    except (SiteUnreachableError, ApiNotFoundError) as e:
        policy = get_policy(e)
        logger.warning("%s — %s 기록: %s", policy.description, policy.site_status, url)
        db.rollback()
        mark_site_status(url, policy.site_status)

        db.expire_all()
        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.completed_at = utc_now()
            job.error_message = str(e)
            db.commit()

        return {"job_id": str(job_id), "status": JobStatus.FAILED, "error": policy.site_status}

    except (RateLimitError, ApiTimeoutError, ApiServerUnavailableError, ApiServerInternalError) as e:
        policy = get_policy(e)
        logger.warning("%s — 재시도 예정: %s", policy.description, url)
        db.rollback()
        db.expire_all()

        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if job:
            job.retry_count = self.request.retries
            job.error_message = str(e)

            if self.request.retries < self.max_retries:
                job.status = JobStatus.PENDING
            else:
                job.status = JobStatus.FAILED
                job.completed_at = utc_now()
                logger.error("최종 실패 (%s): %s", policy.description, job_id)

            db.commit()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))

        return {"job_id": str(job_id), "status": JobStatus.FAILED, "error": str(e)}

    except (ApiUnauthenticatedError, ApiPermissionDeniedError, ApiPreconditionError) as e:
        policy = get_policy(e)
        logger.error("%s — 재시도 불가, 즉시 실패: %s", policy.description, url)
        db.rollback()
        mark_site_status(url, policy.site_status)
        db.expire_all()

        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.completed_at = utc_now()
            job.error_message = str(e)
            db.commit()

        return {"job_id": str(job_id), "status": JobStatus.FAILED, "error": policy.kind}

    except Exception as e:
        logger.error("분석 작업 실패: %s", e, exc_info=True)
        db.rollback()
        db.expire_all()

        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == UUID(job_id)).first()
        if job:
            job.retry_count = self.request.retries
            job.error_message = str(e)

            if self.request.retries < self.max_retries:
                job.status = JobStatus.PENDING
                logger.info("재시도 대기: %s (시도: %d/%d)", job_id, self.request.retries + 1, self.max_retries)
            else:
                job.status = JobStatus.FAILED
                job.completed_at = utc_now()
                mark_site_status(url, SITE_STATUS_FAILURE)
                logger.error("최종 실패: %s", job_id)

            db.commit()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))

        return {"job_id": str(job_id), "status": JobStatus.FAILED, "error": str(e)}

    finally:
        db.close()


@app.task(bind=True, max_retries=3, autoretry_for=(), time_limit=600, soft_time_limit=540)
def analyze_urls_batch(self, job_ids: list[str], urls: list[str]) -> dict[str, Any]:
    """URL 목록을 ThreadPoolExecutor로 병렬 단건 분석한다.

    Args:
        job_ids: 분석 작업 ID 목록 (urls와 동일 순서).
        urls: 분석 대상 URL 목록 (최대 5개).

    Returns:
        성공/실패 건수 요약 딕셔너리.
    """
    logger.info("배치 분석 task 시작: %d개 URL %s", len(urls), urls)
    db = SessionLocal()
    now = utc_now()

    try:
        jobs = {
            str(job.job_id): job
            for job in db.query(AnalysisJob).filter(
                AnalysisJob.job_id.in_(job_ids)
            ).all()
        }
        for job in jobs.values():
            job.status = JobStatus.PROCESSING
            job.started_at = now
        db.commit()
        logger.info("Job 상태 PROCESSING 업데이트 완료: %d건", len(jobs))
    finally:
        db.close()

    job_id_map: dict[str, UUID] = {url: UUID(jid) for jid, url in zip(job_ids, urls)}
    success_map: dict[UUID, int | None] = {}
    failure_map: dict[UUID, str] = {}

    with ThreadPoolExecutor(max_workers=_BATCH_CONCURRENCY) as executor:
        futures = {
            executor.submit(_analyze_one, url, job_id_map[url]): url
            for url in urls
        }
        remaining = set(futures)
        while remaining:
            done, remaining = wait(remaining, return_when=FIRST_COMPLETED)
            for future in done:
                done_url, job_id, result, error = future.result()
                if error:
                    logger.error("배치 항목 분석 실패: %s (%s)", done_url, error)
                    failure_map[job_id] = error
                else:
                    success_map[job_id] = result.get("site_id") if result else None
                    logger.info(
                        "항목 분류 완료: %s | is_ai_tool=%s",
                        done_url, result.get("is_ai_tool") if result else None,
                    )

    update_job_statuses(success_map, failure_map)

    success = len(success_map)
    failed = len(failure_map)
    logger.info("배치 분류 task 완료: 성공=%d 실패=%d 전체=%d", success, failed, len(urls))
    return {"success": success, "failed": failed, "total": len(urls)}


def _mark_jobs_processing(job_ids: list[UUID]) -> None:
    """Job 목록을 PROCESSING 상태로 일괄 전환한다."""
    db = SessionLocal()
    now = utc_now()
    try:
        db.query(AnalysisJob).filter(AnalysisJob.job_id.in_(job_ids)).update(
            {"status": JobStatus.PROCESSING, "started_at": now},
            synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()


def _analyze_one(
    url: str,
    job_id: UUID,
    rate_limit_event: threading.Event | None = None,
) -> tuple[str, UUID, dict[str, Any] | None, str | None]:
    """URL 하나를 독립 DB 세션으로 분석한다. ThreadPoolExecutor 워커에서 호출된다.

    rate_limit_event가 이미 set 상태이면 API 호출 없이 즉시 스킵을 반환한다.

    Returns:
        (url, job_id, result_or_None, error_or_None)
    """
    if rate_limit_event is not None and rate_limit_event.is_set():
        return url, job_id, None, "rate_limit_skip"

    db = SessionLocal()
    try:
        detector = AIDetector(db, analyzer=get_llm_analyzer())
        result = detector.detect_and_save(url)
        if not result:
            return url, job_id, None, "분석 실패"
        return url, job_id, result, None
    except (SiteUnreachableError, ApiNotFoundError) as e:
        policy = get_policy(e)
        logger.warning("%s — %s 기록: %s", policy.description, policy.site_status, url)
        mark_site_status(url, policy.site_status)
        return url, job_id, None, policy.site_status
    except RateLimitError as e:
        policy = get_policy(e)
        logger.warning("%s: %s", policy.description, url)
        if rate_limit_event is not None:
            rate_limit_event.set()
        return url, job_id, None, str(e)
    except (ApiTimeoutError, ApiServerUnavailableError, ApiServerInternalError) as e:
        policy = get_policy(e)
        logger.warning("%s: %s", policy.description, url)
        return url, job_id, None, str(e)
    except (ApiUnauthenticatedError, ApiPermissionDeniedError, ApiPreconditionError) as e:
        policy = get_policy(e)
        logger.error("%s: %s", policy.description, url)
        mark_site_status(url, policy.site_status)
        return url, job_id, None, str(e)
    except Exception as e:
        return url, job_id, None, str(e)
    finally:
        db.close()


@app.task(autoretry_for=(), max_retries=0, time_limit=3600, soft_time_limit=3300)
def analyze_urls_bulk(urls: list[str], force_reanalyze: bool, source_path: str | None = None) -> dict[str, Any]:
    """URL 목록을 병렬 분석하고 결과를 파일 한 개에 저장한다.

    Args:
        urls: 분석할 URL 문자열 목록.
        force_reanalyze: True면 이미 분석된 URL도 재분석.
        source_path: 출력 파일명 기준이 될 원본 파일 경로.

    Returns:
        analyzed/skipped/failed/output_path 정보 딕셔너리
    """
    if not urls:
        return {"analyzed": 0, "skipped": 0, "failed": 0, "output_path": None}

    logger.info(
        "[배치 시작] 총 %d건 수신 (source=%s, force_reanalyze=%s)",
        len(urls), source_path or "unknown", force_reanalyze,
    )

    checked_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    pending_urls, skipped, job_id_map = prepare_bulk_urls(urls, force_reanalyze)

    logger.info(
        "[배치 대상 확정] 총 %d건 → 분석 대상 %d건, 스킵 %d건 (force_reanalyze=%s)",
        len(urls), len(pending_urls), skipped, force_reanalyze,
    )

    if not pending_urls:
        logger.info("배치 완료: 분석 0건, 스킵 %d건, 실패 0건", skipped)
        return {"analyzed": 0, "skipped": skipped, "failed": 0, "output_path": None}

    _mark_jobs_processing(list(job_id_map.values()))

    batch_results: list[tuple[str, dict[str, Any]]] = []
    success_map: dict[UUID, int | None] = {}
    failure_map: dict[UUID, str] = {}
    rate_limit_event = threading.Event()

    with ThreadPoolExecutor(max_workers=_BATCH_CONCURRENCY) as executor:
        pending_iter = iter(pending_urls)
        active_futures: dict[Any, str] = {}

        for url in itertools.islice(pending_iter, _BATCH_CONCURRENCY):
            active_futures[executor.submit(_analyze_one, url, job_id_map[url], rate_limit_event)] = url

        while active_futures:
            done, _ = wait(active_futures, return_when=FIRST_COMPLETED)
            for future in done:
                done_url, job_id, result, error = future.result()
                del active_futures[future]

                if error:
                    logger.error("배치 항목 분석 실패: %s (%s)", done_url, error)
                    failure_map[job_id] = error
                else:
                    batch_results.append((done_url, result))
                    success_map[job_id] = result.get("site_id")
                    logger.info("배치 분석 완료: %s", done_url)

                if rate_limit_event.is_set():
                    continue

                next_url = next(pending_iter, None)
                if next_url:
                    active_futures[executor.submit(
                        _analyze_one, next_url, job_id_map[next_url], rate_limit_event
                    )] = next_url

        if rate_limit_event.is_set():
            for url in pending_iter:
                job_id = job_id_map[url]
                logger.warning("할당량 초과로 배치 조기 종료 — 스킵: %s", url)
                failure_map[job_id] = "rate_limit_skip"

    if rate_limit_event.is_set():
        logger.warning(
            "API 할당량 초과로 배치 조기 종료: 분석 %d건 완료, %d건 미처리",
            len(batch_results),
            sum(1 for v in failure_map.values() if v == "rate_limit_skip"),
        )

    update_job_statuses(success_map, failure_map)

    url_by_job_id = {jid: u for u, jid in job_id_map.items()}
    failure_list = [(url_by_job_id[jid], err) for jid, err in failure_map.items() if jid in url_by_job_id]
    output_path = write_batch(batch_results, checked_at=checked_at, failures=failure_list, source_path=source_path)

    failed = len(failure_map)
    logger.info(
        "배치 완료: 분석 %d건, 스킵 %d건, 실패 %d건, 출력 파일: %s",
        len(batch_results), skipped, failed, output_path,
    )

    return {
        "analyzed": len(batch_results),
        "skipped": skipped,
        "failed": failed,
        "output_path": output_path,
    }
