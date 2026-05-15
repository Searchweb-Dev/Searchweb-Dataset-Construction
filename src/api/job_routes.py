"""분석 작업 조회 API 라우트."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import verify_api_key
from src.core.enums import JobStatus
from src.db.models import AICategory, AISite, AITag, AnalysisJob
from src.db.session import get_db
from src.schemas import AnalysisJobResponse, AISiteResponse, CategoryResponse, ScoreResponse

router = APIRouter()


@router.get("/{job_id}", response_model=AnalysisJobResponse)
def get_job_status(
    job_id: UUID,
    api_key: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """분석 작업의 현재 상태와 결과를 조회한다.

    작업이 완료(status=success)된 경우 분석 결과(AISite 정보)를 함께 반환한다.
    완료 전이면 result 필드는 null이다.

    Args:
        job_id: 조회할 작업의 UUID.
        api_key: API 키 검증 의존성.
        db: DB 세션 의존성.

    Returns:
        작업 상태 및 완료 시 분석 결과(site 정보, 카테고리, 태그, 점수).

    Raises:
        HTTPException 422: job_id가 유효한 UUID 형식이 아닌 경우.
        HTTPException 404: 해당 job_id의 작업이 존재하지 않는 경우.
    """
    job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = None
    if job.status == JobStatus.SUCCESS and job.site_id:
        site = db.query(AISite).filter(AISite.site_id == job.site_id).first()
        if site:
            categories = db.query(AICategory).filter(AICategory.site_id == site.site_id).all()
            tags = db.query(AITag).filter(AITag.site_id == site.site_id).all()

            result = AISiteResponse(
                site_id=site.site_id,
                url=site.url,
                is_ai_tool=site.is_ai_tool,
                title=site.title,
                description=site.description,
                categories=[
                    CategoryResponse(
                        level_1=c.level_1,
                        level_2=c.level_2,
                        level_3=c.level_3,
                        is_primary=c.is_primary,
                    )
                    for c in categories
                ],
                tags=[t.tag_name for t in tags],
                scores=ScoreResponse(
                    utility=site.score_utility,
                    trust=site.score_trust,
                    originality=site.score_originality,
                ),
                last_analyzed_at=site.last_analyzed_at,
            )

    return AnalysisJobResponse(
        job_id=job.job_id,
        url=job.url,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        retry_count=job.retry_count,
        error_message=job.error_message,
        result=result,
    )
