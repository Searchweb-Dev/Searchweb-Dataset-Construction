"""AI 웹사이트 판별 및 분석 결과 저장 로직."""

import logging
from typing import Any
from sqlalchemy.orm import Session

from src.db.models import AISite, AICategory, AITag
from src.db.models.ai_site import SITE_STATUS_OK
from src.ai.analyzer import get_analyzer
from src.core.config import get_llm_provider
from src.core.exceptions import SiteUnreachableError
from src.core.url import normalize_url
from src.core.util import utc_now

logger = logging.getLogger(__name__)


class AIDetector:
    """웹사이트 AI 판별 및 분석."""

    def __init__(self, db: Session, analyzer: Any = None):
        """AI 판별기 초기화.

        Args:
            db: DB 세션.
            analyzer: 분석기 인스턴스. None이면 get_analyzer()로 자동 선택한다.
        """
        self.db = db
        self.analyzer = analyzer if analyzer is not None else get_analyzer()

    def detect_and_save(self, url: str) -> dict[str, Any] | None:
        """웹사이트를 분석하고 결과를 DB에 저장."""
        try:
            url = normalize_url(url)
            logger.info("%s 분석 시작: %s", get_llm_provider(), url)
            analysis_result = self.analyzer.analyze_website(url=url)

            if not self._validate_analysis(analysis_result):
                logger.error("분석 결과 검증 실패: %s", url)
                return None

            ai_site = self._save_site(url=url, analysis=analysis_result)

            if ai_site:
                # 예외 전파 — 카테고리/태그 저장 실패 시 상위에서 rollback
                self._save_categories_and_tags(
                    ai_site.site_id,
                    analysis_result["categories"],
                    analysis_result["tags"],
                )

            self.db.commit()
            logger.info("분석 결과 저장 완료: %s", url)

            return {
                "site_id": ai_site.site_id if ai_site else None,
                "is_ai_tool": analysis_result["is_ai_tool"],
                "title": analysis_result["title"],
                "description": analysis_result.get("description", ""),
                "categories": analysis_result.get("categories", []),
                "tags": analysis_result.get("tags", []),
                "scores": analysis_result.get("scores", {}),
                "confidence": analysis_result.get("confidence", 0),
                "analyzer": analysis_result.get("analyzer"),
            }

        except SiteUnreachableError:
            self.db.rollback()
            raise
        except Exception as e:
            logger.error("AI 판별 중 오류: %s", e, exc_info=True)
            self.db.rollback()
            return None

    def _validate_analysis(self, analysis: dict[str, Any]) -> bool:
        """분석 결과 유효성 검증."""
        required_fields = ["is_ai_tool", "title", "description", "confidence"]
        for field in required_fields:
            if field not in analysis:
                logger.warning(f"필수 필드 누락: {field}")
                return False

        if not isinstance(analysis["confidence"], (int, float)) or not 0 <= analysis["confidence"] <= 1:
            logger.warning("신뢰도 범위 오류")
            return False

        return True

    def _save_site(self, url: str, analysis: dict[str, Any]) -> AISite | None:
        """AI 사이트 정보 저장."""
        scores = analysis.get("scores", {})
        now = utc_now()

        existing = self.db.query(AISite).filter(AISite.url == url).first()
        if existing:
            existing.is_ai_tool = analysis["is_ai_tool"]
            existing.title = analysis.get("title", "")
            existing.description = analysis.get("description", "")
            existing.score_utility = scores.get("utility", 0)
            existing.score_trust = scores.get("trust", 0)
            existing.score_originality = scores.get("originality", 0)
            existing.analyzer = analysis.get("analyzer")
            existing.hard_pass = analysis.get("hard_pass")
            existing.total_score = analysis.get("total_score")
            existing.review_required = analysis.get("review_required")
            existing.last_analyzed_at = now
            existing.status = SITE_STATUS_OK
            existing.unreachable_since = None
            self.db.add(existing)
            return existing

        site = AISite(
            url=url,
            is_ai_tool=analysis["is_ai_tool"],
            title=analysis.get("title", ""),
            description=analysis.get("description", ""),
            score_utility=scores.get("utility", 0),
            score_trust=scores.get("trust", 0),
            score_originality=scores.get("originality", 0),
            analyzer=analysis.get("analyzer"),
            hard_pass=analysis.get("hard_pass"),
            total_score=analysis.get("total_score"),
            review_required=analysis.get("review_required"),
            last_analyzed_at=now,
            status=SITE_STATUS_OK,
        )
        self.db.add(site)
        self.db.flush()
        return site

    def _save_categories_and_tags(
        self,
        site_id: int,
        categories: list[dict[str, Any]],
        tags: list[str],
    ) -> None:
        """카테고리·태그 일괄 삭제 후 재저장 (flush 1회). 예외는 호출자로 전파."""
        self.db.query(AICategory).filter(AICategory.site_id == site_id).delete(synchronize_session=False)
        self.db.query(AITag).filter(AITag.site_id == site_id).delete(synchronize_session=False)
        self.db.flush()

        for cat in categories:
            self.db.add(AICategory(
                site_id=site_id,
                level_1=cat.get("level_1", ""),
                level_2=cat.get("level_2", ""),
                level_3=cat.get("level_3", ""),
                is_primary=cat.get("is_primary", False),
            ))

        for tag_name in tags:
            self.db.add(AITag(site_id=site_id, tag_name=tag_name))
