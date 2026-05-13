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
from src.workers.analyze_task import analyze_ai_tools_batch, analyze_website

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", status_code=202, response_model=list[AnalysisJobResponse])
def analyze(
    request: AnalysisJobRequest,
    api_key: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """URL 목록을 비동기로 분석하는 작업을 생성한다 (단건·다건 모두 지원).

    이미 LLM으로 분석된 URL은 기존 성공 job을 즉시 반환한다.
    rule로 분석된 URL은 LLM으로 재분석한다.
    force_reanalyze=true이면 모든 URL을 새로 분석한다.
    작업 결과는 GET /jobs/{job_id}로 폴링해 확인한다.

    Args:
        request: 분석할 URL 목록(최대 100개)과 재분석 강제 여부.
        api_key: API 키 검증 의존성.
        db: DB 세션 의존성.

    Returns:
        URL별 분석 작업 정보 리스트.

    Raises:
        HTTPException 422: URL 형식 오류.
    """
    responses: list[AnalysisJobResponse] = []

    for raw_url in request.urls:
        url = normalize_url(str(raw_url))

        if not request.force_reanalyze:
            existing = db.query(AISite).filter(AISite.url == url).first()
            # rule로 분석된 사이트는 LLM으로 재분석이 필요하므로 캐시 히트로 보지 않는다
            if existing and existing.analyzer != "rule":
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
        analyze_website.delay(str(job.job_id), url)

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

    db.commit()
    return responses


@router.post("/batch/upload", status_code=202, response_model=BatchAnalysisResponse)
async def analyze_batch_upload(
    file: UploadFile = File(..., description="URL 목록 파일 (JSON 또는 텍스트, 최대 500개)"),
    force_reanalyze: bool = Form(False),
    api_key: str = Depends(verify_api_key),
):
    """업로드된 파일에서 URL을 추출해 일괄 비동기 분석한다.

    JSON 파일: 문자열 배열 ["url1", ...] 또는 객체 배열 [{"link": "url1"}, ...] 지원.
    텍스트 파일: 한 줄에 URL 하나.
    최대 500개까지 처리하며 초과분은 잘라냅니다.

    Args:
        file: 업로드할 URL 목록 파일.
        force_reanalyze: 기존 분석 결과 무시 여부.
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
    analyze_ai_tools_batch.delay(urls, force_reanalyze)

    return BatchAnalysisResponse(
        total=len(urls),
        accepted=len(urls),
        message=f"{len(urls)}건 분석을 백그라운드에서 시작했습니다. 완료 후 data/ 디렉토리에 결과 파일이 생성됩니다.",
    )


@router.post("/batch/file", status_code=202, response_model=BatchAnalysisResponse)
def analyze_batch_file(
    request: BatchFilePathRequest,
    api_key: str = Depends(verify_api_key),
):
    """서버 경로의 파일에서 URL을 추출해 일괄 비동기 분석한다.

    JSON 파일: 문자열 배열 ["url1", ...] 또는 객체 배열 [{"link": "url1"}, ...] 지원.
    텍스트 파일: 한 줄에 URL 하나.
    최대 500개까지 처리하며 초과분은 잘라냅니다.

    Args:
        request: 서버 내 파일 경로와 재분석 강제 여부.
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
    analyze_ai_tools_batch.delay(urls, request.force_reanalyze)

    return BatchAnalysisResponse(
        total=len(urls),
        accepted=len(urls),
        message=f"{len(urls)}건 분석을 백그라운드에서 시작했습니다. 완료 후 data/ 디렉토리에 결과 파일이 생성됩니다.",
    )
