"""웹사이트 AI 판별 비동기 작업."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Any
from uuid import uuid4

from src.db.models import AnalysisJob, AISite
from src.db.session import SessionLocal
from src.ai.detector import AIDetector
from src.workers.celery_app import app
from src.core.result_writer import write_batch
from src.core.url import normalize_url

logger = logging.getLogger(__name__)

_FAILURE_SENTINELS = {"Unknown", "분석 실패", ""}


def _is_failed_analysis(site: AISite) -> bool:
    """이전 분석이 실패 기본값인지 확인."""
    return (
        (site.title or "") in _FAILURE_SENTINELS
        or (site.description or "") in _FAILURE_SENTINELS
        or (site.summary_ko or "") in _FAILURE_SENTINELS
    )


@app.task(bind=True, max_retries=3)
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
        # 1. Job 상태 업데이트 (processing)
        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if not job:
            logger.error(f"Job을 찾을 수 없음: {job_id}")
            return {"error": "Job not found"}

        job.status = "processing"
        job.started_at = datetime.utcnow()
        db.commit()
        logger.info(f"Job 상태 업데이트 (processing): {job_id}")

        # 2. 캐시(기존 분석 결과) 확인
        existing = db.query(AISite).filter(AISite.url == url).first()
        if existing and job.request_source != "force":
            if _is_failed_analysis(existing):
                logger.warning(
                    f"이전 분석이 실패 상태입니다. 재분석합니다: {url} "
                    f"(title={existing.title!r}, description={existing.description!r}, "
                    f"summary_ko={existing.summary_ko!r})"
                )
            else:
                logger.info(f"캐시에 결과가 있어 결과 파일 쓰기를 건너뜁니다: {url}")
                job.status = "success"
                job.completed_at = datetime.utcnow()
                job.site_id = existing.site_id
                db.commit()
                return {
                    "job_id": str(job_id),
                    "status": "success",
                    "site_id": existing.site_id,
                    "is_ai_tool": existing.is_ai_tool,
                }

        # 3. AI 판별 실행
        detector = AIDetector(db)
        result = detector.detect_and_save(url)

        if not result:
            raise Exception("분석 실패")

        # 4. 결과 파일 저장
        checked_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        write_batch([(url, result)], checked_at=checked_at)

        # 5. Job 상태 업데이트 (success)
        job.status = "success"
        job.completed_at = datetime.utcnow()
        job.site_id = result.get("site_id")
        db.commit()
        logger.info(f"분석 완료: {job_id} -> {result}")

        return {
            "job_id": str(job_id),
            "status": "success",
            "site_id": result.get("site_id"),
            "is_ai_tool": result.get("is_ai_tool"),
        }

    except Exception as e:
        logger.error(f"분석 작업 실패: {e}")
        db.rollback()

        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        if job:
            job.retry_count = self.request.retries
            job.error_message = str(e)

            if self.request.retries < self.max_retries:
                job.status = "pending"
                logger.info(f"재시도 대기: {job_id} (시도: {self.request.retries + 1}/{self.max_retries})")
            else:
                job.status = "failed"
                job.completed_at = datetime.utcnow()
                logger.error(f"최종 실패: {job_id}")

            db.commit()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=Exception(str(e)), countdown=60 * (self.request.retries + 1))

        return {
            "job_id": str(job_id),
            "status": "failed",
            "error": str(e),
        }

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


@app.task
def analyze_ai_tools_batch(limit: Optional[int], force_reanalyze: bool) -> dict[str, Any]:
    """
    ai-tools.json 전체(또는 일부)를 순차 분석하고 결과를 파일 한 개에 저장한다.

    analyze_website와 달리 이 태스크는 분석을 직접 실행하며,
    배치 내 모든 URL 처리가 끝난 뒤 write_batch()를 한 번만 호출한다.

    Args:
        limit: 분석할 최대 항목 수. None이면 전체.
        force_reanalyze: True면 이미 분석된 URL도 재분석.

    Returns:
        queued/skipped/failed/output_path 정보 딕셔너리
    """
    urls = _load_ai_tools_urls(limit)
    if not urls:
        return {"analyzed": 0, "skipped": 0, "failed": 0, "output_path": None}

    checked_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    db = SessionLocal()

    batch_results: list[tuple[str, dict[str, Any]]] = []
    skipped = failed = 0

    try:
        for url in urls:
            url = normalize_url(url)
            # 기존 분석 결과 스킵 (실패 데이터는 재분석)
            if not force_reanalyze:
                existing = db.query(AISite).filter(AISite.url == url).first()
                if existing:
                    if _is_failed_analysis(existing):
                        logger.warning(
                            f"이전 분석이 실패 상태입니다. 재분석합니다: {url} "
                            f"(title={existing.title!r}, description={existing.description!r}, "
                            f"summary_ko={existing.summary_ko!r})"
                        )
                    else:
                        skipped += 1
                        logger.debug(f"분석 스킵 (기존 데이터): {url}")
                        continue

            # Job 생성
            job = AnalysisJob(
                job_id=uuid4(),
                url=url,
                status="processing",
                started_at=datetime.utcnow(),
                retry_count=0,
                request_source="batch_ai_tools",
            )
            db.add(job)
            db.flush()

            # 분석 실행 (직접 호출 — 배치 결과를 모으기 위해 delay 미사용)
            try:
                detector = AIDetector(db)
                result = detector.detect_and_save(url)

                if not result:
                    raise Exception("분석 실패")

                job.status = "success"
                job.completed_at = datetime.utcnow()
                job.site_id = result.get("site_id")
                db.commit()

                batch_results.append((url, result))
                logger.info(f"배치 분석 완료: {url}")

            except Exception as e:
                logger.error(f"배치 항목 분석 실패: {url} ({e})")
                db.rollback()
                job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job.job_id).first()
                if job:
                    job.status = "failed"
                    job.completed_at = datetime.utcnow()
                    job.error_message = str(e)
                    db.commit()
                failed += 1

    finally:
        db.close()

    # 이번 배치 전체 결과를 파일 한 개에 저장
    output_path = write_batch(batch_results, checked_at=checked_at)

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
