"""웹사이트 AI 판별 비동기 작업."""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional, Any
from uuid import UUID, uuid4

from src.db.models import AnalysisJob, AISite
from src.db.session import SessionLocal
from src.ai.detector import AIDetector
from src.workers.celery_app import app
from src.core.result_writer import write_batch
from src.core.url import normalize_url
from src.core.util import utc_now
from src.core.exceptions import AnalysisError
from src.core.enums import JobStatus

logger = logging.getLogger(__name__)

# 배치 병렬 실행 시 동시에 처리할 최대 URL 수.
# LLM API rate limit과 DB 연결 수를 고려하여 조정한다.
_BATCH_CONCURRENCY = int(os.getenv("BATCH_CONCURRENCY", "5"))

_FAILURE_SENTINELS = {"Unknown", "분석 실패", ""}


def _is_failed_analysis(site: AISite) -> bool:
    """이전 분석이 실패 기본값인지 확인.

    title과 description 모두 sentinel일 때만 실패로 판단한다.
    둘 중 하나만 비어있는 경우는 정상 데이터로 간주한다.
    """
    return (
        (site.title or "") in _FAILURE_SENTINELS
        and (site.description or "") in _FAILURE_SENTINELS
    )


# 전역 task_autoretry_for 미설정 — 재시도는 각 태스크가 명시적으로 관리한다.
@app.task(bind=True, max_retries=3, autoretry_for=(), time_limit=300, soft_time_limit=240)
def analyze_website(self, job_id: str, url: str) -> dict[str, Any]:
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
        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if not job:
            logger.error(f"Job을 찾을 수 없음: {job_id}")
            return {"error": "Job not found"}

        job.status = JobStatus.PROCESSING
        job.started_at = utc_now()
        db.commit()
        logger.info(f"Job 상태 업데이트 (processing): {job_id}")

        existing = db.query(AISite).filter(AISite.url == url).first()
        if existing and job.request_source != "force":
            if _is_failed_analysis(existing):
                logger.warning(
                    f"이전 분석이 실패 상태입니다. 재분석합니다: {url} "
                    f"(title={existing.title!r}, description={existing.description!r})"
                )
            else:
                logger.info(f"캐시에 결과가 있어 결과 파일 쓰기를 건너뜁니다: {url}")
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

        detector = AIDetector(db)
        result = detector.detect_and_save(url)

        if not result:
            raise AnalysisError("분석 실패")

        job.status = JobStatus.SUCCESS
        job.completed_at = utc_now()
        job.site_id = result.get("site_id")
        db.commit()
        logger.info(f"분석 완료: {job_id} -> {result}")

        return {
            "job_id": str(job_id),
            "status": JobStatus.SUCCESS,
            "site_id": result.get("site_id"),
            "is_ai_tool": result.get("is_ai_tool"),
        }

    except Exception as e:
        logger.error(f"분석 작업 실패: {e}")
        db.rollback()
        db.expire_all()  # rollback 후 stale 객체 제거

        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if job:
            job.retry_count = self.request.retries
            job.error_message = str(e)

            if self.request.retries < self.max_retries:
                job.status = JobStatus.PENDING
                logger.info(f"재시도 대기: {job_id} (시도: {self.request.retries + 1}/{self.max_retries})")
            else:
                job.status = JobStatus.FAILED
                job.completed_at = utc_now()
                logger.error(f"최종 실패: {job_id}")

            db.commit()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=Exception(str(e)), countdown=60 * (self.request.retries + 1))

        return {"job_id": str(job_id), "status": JobStatus.FAILED, "error": str(e)}

    finally:
        db.close()


def _load_ai_tools_urls(limit: Optional[int] = None) -> list[str]:
    """ai-tools.json에서 URL 목록을 읽는다. limit 미지정 시 전체 반환."""
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data",
        "ai-tools.json",
    )
    if not os.path.isfile(json_path):
        logger.error(f"ai-tools.json 파일 없음: {json_path}")
        return []

    with open(json_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    urls = [item["link"] for item in items if isinstance(item, dict) and item.get("link")]
    if limit is not None:
        urls = urls[:limit]
    return urls


def _analyze_one(url: str, job_id: UUID) -> tuple[str, UUID, dict[str, Any] | None, str | None]:
    """
    URL 하나를 독립 DB 세션으로 분석한다. ThreadPoolExecutor 워커에서 호출된다.

    Returns:
        (url, job_id, result_or_None, error_or_None)
    """
    db = SessionLocal()
    try:
        detector = AIDetector(db)
        result = detector.detect_and_save(url)
        if not result:
            return url, job_id, None, "분석 실패"
        return url, job_id, result, None
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
def analyze_ai_tools_batch(limit: Optional[int], force_reanalyze: bool) -> dict[str, Any]:
    """
    ai-tools.json 전체(또는 일부)를 병렬 분석하고 결과를 파일 한 개에 저장한다.

    LLM API 호출은 ThreadPoolExecutor로 병렬 실행되고,
    DB 쓰기는 각 워커의 독립 세션에서 처리된다.
    모든 URL 처리가 끝난 뒤 write_batch()를 한 번만 호출한다.

    Args:
        limit: 분석할 최대 항목 수. None이면 전체.
        force_reanalyze: True면 이미 분석된 URL도 재분석.

    Returns:
        analyzed/skipped/failed/output_path 정보 딕셔너리
    """
    urls = _load_ai_tools_urls(limit)
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
                if ex and not _is_failed_analysis(ex):
                    skipped += 1
                    logger.debug(f"분석 스킵 (기존 데이터): {url}")
                else:
                    if ex:
                        logger.warning(
                            f"이전 분석이 실패 상태입니다. 재분석합니다: {url} "
                            f"(title={ex.title!r}, description={ex.description!r})"
                        )
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

    if not pending_urls:
        logger.info(f"배치 완료: 분석 0건, 스킵 {skipped}건, 실패 0건")
        return {"analyzed": 0, "skipped": skipped, "failed": 0, "output_path": None}

    # 2. 병렬 LLM 분석 (각 워커는 독립 DB 세션 사용)
    batch_results: list[tuple[str, dict[str, Any]]] = []
    success_map: dict[UUID, int | None] = {}
    failure_map: dict[UUID, str] = {}

    with ThreadPoolExecutor(max_workers=_BATCH_CONCURRENCY) as executor:
        futures = {
            executor.submit(_analyze_one, url, job_id_map[url]): url
            for url in pending_urls
        }

        for future in as_completed(futures):
            url, job_id, result, error = future.result()
            if error:
                logger.error(f"배치 항목 분석 실패: {url} ({error})")
                failure_map[job_id] = error
            else:
                if result is None:
                    raise AnalysisError(f"배치 분석 결과가 None입니다: {url}")
                batch_results.append((url, result))
                success_map[job_id] = result.get("site_id")
                logger.info(f"배치 분석 완료: {url}")

    # 3. Job 상태 일괄 업데이트 (세션 1개)
    _update_job_statuses(success_map, failure_map)

    # 4. 이번 배치 전체 결과를 파일 한 개에 저장
    output_path = write_batch(batch_results, checked_at=checked_at)

    failed = len(failure_map)
    logger.info(
        f"배치 완료: 분석 {len(batch_results)}건, 스킵 {skipped}건, "
        f"실패 {failed}건, 출력 파일: {output_path}"
    )

    return {
        "analyzed": len(batch_results),
        "skipped": skipped,
        "failed": failed,
        "output_path": output_path,
    }
