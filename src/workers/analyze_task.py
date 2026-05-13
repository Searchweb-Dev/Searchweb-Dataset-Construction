"""웹사이트 AI 판별 비동기 작업."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional, Any
from uuid import UUID, uuid4

from src.db.models import AnalysisJob, AISite
from src.db.session import SessionLocal
from src.ai.analyzer import get_llm_analyzer
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
@app.task(bind=True, max_retries=3, autoretry_for=(), time_limit=600, soft_time_limit=540)
def analyze_website_batch(self, job_ids: list[str], urls: list[str]) -> dict[str, Any]:
    """URL 목록을 LLM 1회 호출로 배치 분석한다.

    Args:
        job_ids: 분석 작업 ID 목록 (urls와 동일 순서).
        urls: 분석 대상 URL 목록 (최대 5개).

    Returns:
        성공/실패 건수 요약 딕셔너리.
    """
    from src.ai.gemini_analyzer import GeminiAnalyzer
    from src.ai.analyzer import get_llm_analyzer

    logger.info(
        "배치 분석 task 시작: %d개 URL %s",
        len(urls),
        urls,
    )
    db = SessionLocal()
    now = utc_now()

    try:
        # Job 상태를 PROCESSING으로 일괄 업데이트
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

        analyzer = get_llm_analyzer()
        analyzer_name = type(analyzer).__name__

        # 배치 분석 지원 여부에 따라 분기
        if hasattr(analyzer, "analyze_websites_batch"):
            logger.info("[%s] 배치 LLM 호출 시작 (URL %d개 → 호출 1회)", analyzer_name, len(urls))
            results = analyzer.analyze_websites_batch(urls)
            logger.info("[%s] 배치 LLM 호출 완료", analyzer_name)
        else:
            logger.info("[%s] 개별 LLM 호출 시작 (URL %d개)", analyzer_name, len(urls))
            results = [analyzer.analyze_website(url) for url in urls]
            logger.info("[%s] 개별 LLM 호출 완료", analyzer_name)

        success, failed = 0, 0
        detector = AIDetector(db, analyzer=analyzer)

        for job_id_str, url, analysis in zip(job_ids, urls, results):
            job = jobs.get(job_id_str)
            if not job:
                logger.error("Job을 찾을 수 없음: %s", job_id_str)
                failed += 1
                continue
            try:
                if not detector._validate_analysis(analysis):
                    raise AnalysisError(f"분류 결과 검증 실패: {url}")

                ai_site = detector._save_site(url=url, analysis=analysis)
                if ai_site:
                    detector._save_categories_and_tags(
                        ai_site.site_id,
                        analysis.get("categories", []),
                        analysis.get("tags", []),
                    )
                db.commit()

                job.status = JobStatus.SUCCESS
                job.completed_at = utc_now()
                job.site_id = ai_site.site_id if ai_site else None
                db.commit()
                success += 1
                logger.info(
                    "항목 분류 완료: %s | is_ai_tool=%s confidence=%.2f title=%r",
                    url,
                    analysis.get("is_ai_tool"),
                    analysis.get("confidence", 0),
                    analysis.get("title", ""),
                )
            except Exception as e:
                logger.error("항목 저장 실패: %s (%s)", url, e)
                db.rollback()
                job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id_str).first()
                if job:
                    job.status = JobStatus.FAILED
                    job.error_message = str(e)
                    job.completed_at = utc_now()
                    db.commit()
                failed += 1

        logger.info(
            "배치 분류 task 완료: 성공=%d 실패=%d 전체=%d",
            success, failed, len(urls),
        )
        return {"success": success, "failed": failed, "total": len(urls)}

    except Exception as e:
        logger.error(f"배치 분석 작업 실패: {e}")
        db.rollback()

        # 전체 job을 FAILED 처리
        for job_id_str in job_ids:
            job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id_str).first()
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                job.completed_at = utc_now()
                job.retry_count = self.request.retries
        db.commit()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=Exception(str(e)), countdown=60 * (self.request.retries + 1))

        return {"success": 0, "failed": len(urls), "total": len(urls)}

    finally:
        db.close()


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
            elif existing.analyzer == "rule":
                # rule 분류 결과는 LLM으로 재분석해 upsert
                logger.info(f"rule 분류 결과를 LLM으로 재분석합니다: {url}")
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

        # CLASSIFIER_MODE 무관하게 항상 LLM으로 분석
        detector = AIDetector(db, analyzer=get_llm_analyzer())
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
def analyze_ai_tools_batch(urls: list[str], force_reanalyze: bool) -> dict[str, Any]:
    """
    URL 목록을 병렬 분석하고 결과를 파일 한 개에 저장한다.

    LLM API 호출은 ThreadPoolExecutor로 병렬 실행되고,
    DB 쓰기는 각 워커의 독립 세션에서 처리된다.
    모든 URL 처리가 끝난 뒤 write_batch()를 한 번만 호출한다.

    Args:
        urls: 분석할 URL 문자열 목록.
        force_reanalyze: True면 이미 분석된 URL도 재분석.

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
