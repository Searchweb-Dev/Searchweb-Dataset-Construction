"""비동기 URL 분석 요청 API 라우트."""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from src.api.deps import verify_api_key
from src.core.batch_file import extract_urls_from_bytes, extract_urls_from_path
from src.core.enums import JobStatus
from src.core.url import normalize_url
from src.db.models import AISite, AnalysisJob
from src.db.session import get_db
from src.schemas import (
    AnalysisJobRequest,
    AnalysisJobResponse,
    BatchAnalysisResponse,
    BatchFilePathRequest,
)
from src.workers.analyze_task import analyze_urls_batch, analyze_urls_bulk

logger = logging.getLogger(__name__)

router = APIRouter()


def _try_cache_hit(
    url: str,
    existing_map: dict,
    db: Session,
    force_reanalyze: bool,
) -> AnalysisJobResponse | None:
    """캐시 히트 시 AnalysisJobResponse를 반환하고, 아니면 None을 반환한다."""
    if force_reanalyze:
        return None

    existing = existing_map.get(url)
    if existing is None:
        return None

    # LLM으로 분석된 URL만 캐시 히트 — rule 분석 결과는 LLM으로 재분석
    if existing.analyzer not in (None, "rule"):
        job = (
            db.query(AnalysisJob)
            .filter(
                AnalysisJob.site_id == existing.site_id,
                AnalysisJob.status == JobStatus.SUCCESS,
            )
            .order_by(AnalysisJob.completed_at.desc())
            .first()
        )
        if job:
            logger.info("[analyze] 캐시 히트 (analyzer=%s): %s", existing.analyzer, url)
            return AnalysisJobResponse(
                job_id=job.job_id,
                url=job.url,
                status=job.status,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                retry_count=job.retry_count,
                error_message=job.error_message,
            )

    if existing.analyzer in (None, "rule"):
        logger.info("[analyze] rule 분석 결과 → LLM 재분석 대상: %s", url)

    return None


@router.post("", status_code=202, response_model=list[AnalysisJobResponse])
def analyze(
    request: AnalysisJobRequest,
    api_key: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """URL 목록을 비동기로 LLM 분석한다 (최대 5개).

    LLM으로 이미 분석된 URL은 캐시 결과를 즉시 반환한다.
    rule 분석 URL 또는 미분석 URL은 LLM 배치 분석 대상이 된다.
    LLM 대상 URL 전체를 단일 Celery task로 묶어 LLM 호출을 최소화한다.
    force_reanalyze=true이면 모든 URL을 새로 분석한다.
    작업 결과는 GET /jobs/{job_id}로 폴링해 확인한다.

    Args:
        request: 분류할 URL 목록(최대 5개)과 재분류 강제 여부.
        api_key: API 키 검증 의존성.
        db: DB 세션 의존성.

    Returns:
        URL별 분류 작업 정보 리스트.

    Raises:
        HTTPException 422: URL 형식 오류.
    """
    input_urls = [normalize_url(str(u)) for u in request.urls]
    logger.info(
        "[analyze] 요청 수신: %d개 URL %s (force_reanalyze=%s)",
        len(input_urls), input_urls, request.force_reanalyze,
    )

    responses: list[AnalysisJobResponse] = []
    pending_job_ids: list[str] = []
    pending_urls: list[str] = []

    existing_map: dict[str, AISite] = {}
    if not request.force_reanalyze:
        existing_map = {
            s.url: s
            for s in db.query(AISite).filter(AISite.url.in_(input_urls)).all()
        }

    for url in input_urls:
        cached_response = _try_cache_hit(url, existing_map, db, request.force_reanalyze)
        if cached_response is not None:
            responses.append(cached_response)
            continue

        job = AnalysisJob(
            job_id=uuid4(),
            url=url,
            status=JobStatus.PENDING,
            retry_count=0,
            request_source="api",
        )
        db.add(job)
        db.flush()
        responses.append(AnalysisJobResponse(
            job_id=job.job_id,
            url=job.url,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            retry_count=job.retry_count,
            error_message=job.error_message,
        ))
        pending_job_ids.append(str(job.job_id))
        pending_urls.append(url)

    db.commit()

    if pending_urls:
        logger.info("[analyze] LLM 배치 분석 디스패치: %d개 URL %s", len(pending_urls), pending_urls)
        analyze_urls_batch.delay(pending_job_ids, pending_urls)
    else:
        logger.info("[analyze] 모든 URL 캐시 히트 — LLM 호출 없음")

    logger.info(
        "[analyze] 응답 반환: 캐시=%d건 LLM대기=%d건",
        len(responses) - len(pending_urls), len(pending_urls),
    )
    return responses


@router.post("/batch/upload", status_code=202, response_model=BatchAnalysisResponse)
async def analyze_batch_upload(
    file: UploadFile = File(..., description="URL 목록 파일 (JSON 또는 텍스트, 최대 500개)"),
    force_reanalyze: bool = Form(False),
    api_key: str = Depends(verify_api_key),
):
    """업로드된 파일에서 URL을 추출해 일괄 비동기 분류한다.

    JSON 파일: 문자열 배열 ["url1", ...] 또는 객체 배열 [{"link": "url1"}, ...] 지원.
    텍스트 파일: 한 줄에 URL 하나.
    최대 500개까지 처리하며 초과분은 잘라냅니다.

    Args:
        file: 업로드할 URL 목록 파일.
        force_reanalyze: 기존 분류 결과 무시 여부.
        api_key: API 키 검증 의존성.

    Returns:
        전체 URL 수, 접수된 URL 수, 작업 접수 안내 메시지.

    Raises:
        HTTPException 400: 파일에서 URL을 추출할 수 없는 경우.
    """
    content = await file.read()
    try:
        urls = extract_urls_from_bytes(content, filename=file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("[batch/upload] %d개 URL 접수 (파일: %s)", len(urls), file.filename)
    analyze_urls_bulk.delay(urls, force_reanalyze, file.filename)

    return BatchAnalysisResponse(
        total=len(urls),
        accepted=len(urls),
        message=f"{len(urls)}건 분류를 백그라운드에서 시작했습니다. 완료 후 data/ 디렉토리에 결과 파일이 생성됩니다.",
    )


@router.post("/batch/file", status_code=202, response_model=BatchAnalysisResponse)
def analyze_batch_file(
    request: BatchFilePathRequest,
    api_key: str = Depends(verify_api_key),
):
    """서버 경로의 파일에서 URL을 추출해 일괄 비동기 분류한다.

    JSON 파일: 문자열 배열 ["url1", ...] 또는 객체 배열 [{"link": "url1"}, ...] 지원.
    텍스트 파일: 한 줄에 URL 하나.
    최대 500개까지 처리하며 초과분은 잘라냅니다.

    Args:
        request: 서버 내 파일 경로와 재분류 강제 여부.
        api_key: API 키 검증 의존성.

    Returns:
        전체 URL 수, 접수된 URL 수, 작업 접수 안내 메시지.

    Raises:
        HTTPException 404: 지정한 경로에 파일이 없는 경우.
        HTTPException 400: 파일에서 URL을 추출할 수 없는 경우.
    """
    try:
        urls = extract_urls_from_path(request.file_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("[batch/file] %d개 URL 접수 (경로: %s)", len(urls), request.file_path)
    analyze_urls_bulk.delay(urls, request.force_reanalyze, request.file_path)

    return BatchAnalysisResponse(
        total=len(urls),
        accepted=len(urls),
        message=f"{len(urls)}건 분류를 백그라운드에서 시작했습니다. 완료 후 data/ 디렉토리에 결과 파일이 생성됩니다.",
    )
