"""웹사이트 AI 판별 비동기 작업."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from src.db.models import AnalysisJob, AISite
from src.db.session import SessionLocal
from src.ai.analyzer import get_llm_analyzer
from src.ai.detector import AIDetector
from src.workers.celery_app import app
from src.core.result_writer import write_batch
from src.core.url import normalize_url
from src.core.util import utc_now
from src.core.error_policy import get_policy
from src.core.exceptions import (
    AnalysisError,
    SiteUnreachableError,
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
from src.db.models.ai_site import (
    UNREACHABLE_TTL_SECONDS,
    SITE_STATUS_OK,
    SITE_STATUS_UNREACHABLE,
    SITE_STATUS_BLOCKED,
    SITE_STATUS_FAILURE,
)

logger = logging.getLogger(__name__)

# 배치 병렬 실행 시 동시에 처리할 최대 URL 수.
# LLM API rate limit과 DB 연결 수를 고려하여 조정한다.
_BATCH_CONCURRENCY = int(os.getenv("BATCH_CONCURRENCY", "5"))


def _is_failed_analysis(site: AISite) -> bool:
    """이전 분석이 실패 상태인지 확인."""
    return site.status in (SITE_STATUS_FAILURE, SITE_STATUS_BLOCKED)


def _is_unreachable_blocked(site: AISite) -> bool:
    """접근 불가 TTL 이내인지 확인한다.

    status가 unreachable이고 unreachable_since 기록 후 UNREACHABLE_TTL_SECONDS 이내이면
    True를 반환해 재분석 없이 스킵한다. TTL이 지났으면 False를 반환하여 재시도 대상으로 전환한다.
    """
    if site.status != SITE_STATUS_UNREACHABLE or site.unreachable_since is None:
        return False
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    elapsed = (now_naive - site.unreachable_since).total_seconds()
    return elapsed < UNREACHABLE_TTL_SECONDS


def _mark_site_status(db: Any, url: str, status: str) -> None:
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


@app.task(bind=True, max_retries=3, autoretry_for=(), time_limit=300, soft_time_limit=240)
def analyze_url(self, job_id: str, url: str) -> dict[str, Any]:
    """
    웹사이트 분석 작업 (단건).

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
            elif _is_failed_analysis(existing):
                logger.warning(
                    "이전 분석이 실패 상태입니다. 재분석합니다: %s (title=%r, description=%r)",
                    url, existing.title, existing.description,
                )
            elif existing.analyzer == "rule":
                # rule 분류 결과는 LLM으로 재분석해 upsert
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

        # CLASSIFIER_MODE 무관하게 항상 LLM으로 분석
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
        db.expire_all()
        _mark_site_status(db, url, policy.site_status)

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
        db.expire_all()
        _mark_site_status(db, url, policy.site_status)

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
                _mark_site_status(db, url, SITE_STATUS_FAILURE)
                logger.error("최종 실패: %s", job_id)

            db.commit()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))

        return {"job_id": str(job_id), "status": JobStatus.FAILED, "error": str(e)}

    finally:
        db.close()


# 전역 task_autoretry_for 미설정 — 재시도는 각 태스크가 명시적으로 관리한다.
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
        for future in as_completed(futures):
            url, job_id, result, error = future.result()
            if error:
                logger.error("배치 항목 분석 실패: %s (%s)", url, error)
                failure_map[job_id] = error
            else:
                success_map[job_id] = result.get("site_id") if result else None
                logger.info(
                    "항목 분류 완료: %s | is_ai_tool=%s",
                    url, result.get("is_ai_tool") if result else None,
                )

    _update_job_statuses(success_map, failure_map)

    success = len(success_map)
    failed = len(failure_map)
    logger.info("배치 분류 task 완료: 성공=%d 실패=%d 전체=%d", success, failed, len(urls))
    return {"success": success, "failed": failed, "total": len(urls)}


def _analyze_one(url: str, job_id: UUID) -> tuple[str, UUID, dict[str, Any] | None, str | None]:
    """
    URL 하나를 독립 DB 세션으로 분석한다. ThreadPoolExecutor 워커에서 호출된다.

    Returns:
        (url, job_id, result_or_None, error_or_None)
    """
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
        _mark_site_status(db, url, policy.site_status)
        return url, job_id, None, policy.site_status
    except (RateLimitError, ApiTimeoutError, ApiServerUnavailableError, ApiServerInternalError) as e:
        policy = get_policy(e)
        logger.warning("%s: %s", policy.description, url)
        return url, job_id, None, str(e)
    except (ApiUnauthenticatedError, ApiPermissionDeniedError, ApiPreconditionError) as e:
        policy = get_policy(e)
        logger.error("%s: %s", policy.description, url)
        _mark_site_status(db, url, policy.site_status)
        return url, job_id, None, str(e)
    except Exception as e:
        return url, job_id, None, str(e)
    finally:
        db.close()


def _update_job_statuses(
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


@app.task(autoretry_for=(), max_retries=0, time_limit=3600, soft_time_limit=3300)
def analyze_urls_bulk(urls: list[str], force_reanalyze: bool, source_path: str | None = None) -> dict[str, Any]:
    """
    URL 목록을 병렬 분석하고 결과를 파일 한 개에 저장한다.

    LLM API 호출은 ThreadPoolExecutor로 병렬 실행되고,
    DB 쓰기는 각 워커의 독립 세션에서 처리된다.
    모든 URL 처리가 끝난 뒤 write_batch()를 한 번만 호출한다.

    Args:
        urls: 분석할 URL 문자열 목록.
        force_reanalyze: True면 이미 분석된 URL도 재분석.
        source_path: 출력 파일명 기준이 될 원본 파일 경로. 미지정 시 기본 ai-tools.json.

    Returns:
        analyzed/skipped/failed/output_path 정보 딕셔너리
    """
    if not urls:
        return {"analyzed": 0, "skipped": 0, "failed": 0, "output_path": None}

    checked_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    # 1. 스킵 여부 사전 판별 + Job 레코드 일괄 생성 (단일 세션)
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
                elif ex and _is_failed_analysis(ex):
                    logger.warning(
                        "이전 분석이 실패 상태입니다. 재분석합니다: %s (status=%r)", url, ex.status
                    )
                    pending_urls.append(url)
                elif ex and ex.analyzer in (None, "rule"):
                    # analyze API와 동일하게 rule/미분석 결과는 LLM 재분석 대상
                    logger.info("rule 분류 결과를 LLM으로 재분석합니다: %s (analyzer=%s)", url, ex.analyzer)
                    pending_urls.append(url)
                elif ex:
                    # LLM 분석 결과가 있으면 캐시 히트로 스킵
                    skipped += 1
                    logger.debug("분석 스킵 (LLM 캐시, analyzer=%s): %s", ex.analyzer, url)
                else:
                    pending_urls.append(url)
        else:
            pending_urls = normalized_urls

        now = utc_now()
        for url in pending_urls:
            job = AnalysisJob(
                job_id=uuid4(),
                url=url,
                status=JobStatus.PROCESSING,
                started_at=now,
                retry_count=0,
                request_source="batch_ai_tools",
            )
            db.add(job)
            db.flush()
            job_id_map[url] = job.job_id
        db.commit()
    finally:
        db.close()

    logger.info(
        "대상 판단 완료: 전체 %d건 → 분석 대상 %d건, 스킵 %d건 (force_reanalyze=%s)",
        len(normalized_urls), len(pending_urls), skipped, force_reanalyze,
    )

    if not pending_urls:
        logger.info("배치 완료: 분석 0건, 스킵 %d건, 실패 0건", skipped)
        return {"analyzed": 0, "skipped": skipped, "failed": 0, "output_path": None}

    batch_results: list[tuple[str, dict[str, Any]]] = []
    success_map: dict[UUID, int | None] = {}
    failure_map: dict[UUID, str] = {}

    # ThreadPoolExecutor로 병렬 단건 처리
    with ThreadPoolExecutor(max_workers=_BATCH_CONCURRENCY) as executor:
        futures = {
            executor.submit(_analyze_one, url, job_id_map[url]): url
            for url in pending_urls
        }
        for future in as_completed(futures):
            url, job_id, result, error = future.result()
            if error:
                logger.error("배치 항목 분석 실패: %s (%s)", url, error)
                failure_map[job_id] = error
            else:
                batch_results.append((url, result))
                success_map[job_id] = result.get("site_id")
                logger.info("배치 분석 완료: %s", url)

    # Job 상태 일괄 업데이트 (세션 1개)
    _update_job_statuses(success_map, failure_map)

    # 이번 배치 전체 결과(성공+실패)를 파일 한 개에 저장
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
