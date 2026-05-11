"""AI 웹사이트 판별 및 분석 결과 저장 로직."""

import logging
from datetime import datetime
from typing import Optional, Any
from sqlalchemy.orm import Session

from src.db.models import AISite, AICategory, AITag
from src.ai.analyzer import get_analyzer
from src.core.config import get_llm_provider
from src.core.url import normalize_url

logger = logging.getLogger(__name__)


class AIDetector:
    """웹사이트 AI 판별 및 분석."""

    def __init__(self, db: Session):
        """AI 판별기 초기화."""
        self.db = db
        self.analyzer = get_analyzer()

    def detect_and_save(self, url: str) -> Optional[dict[str, Any]]:
        """웹사이트를 분석하고 결과를 DB에 저장."""
        try:
            url = normalize_url(url)
            # 1. LLM 분석 (url_context 방식: Gemini가 직접 fetch)
            logger.info(f"{get_llm_provider()} 분석 시작: {url}")
            analysis_result = self.analyzer.analyze_website(url=url)

            # 2. 결과 검증
            if not self._validate_analysis(analysis_result):
                logger.error(f"분석 결과 검증 실패: {url}")
                return None

            # 3. DB 저장
            ai_site = self._save_site(
                url=url,
                analysis=analysis_result,
            )

            if ai_site:
                self._save_categories_and_tags(
                    ai_site.site_id,
                    analysis_result["categories"],
                    analysis_result["tags"],
                )

            self.db.commit()
            logger.info(f"분석 결과 저장 완료: {url}")

            return {
                "site_id": ai_site.site_id if ai_site else None,
                "is_ai_tool": analysis_result["is_ai_tool"],
                "title": analysis_result["title"],
                "description": analysis_result.get("description", ""),
                "categories": analysis_result.get("categories", []),
                "tags": analysis_result.get("tags", []),
                "scores": analysis_result.get("scores", {}),
                "confidence": analysis_result.get("confidence", 0),
            }

        except Exception as e:
            logger.error(f"AI 판별 중 오류: {e}")
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

    def _save_site(
        self,
        url: str,
        analysis: dict[str, Any],
    ) -> Optional[AISite]:
        """AI 사이트 정보 저장."""
        try:
            # 기존 데이터 확인
            existing = self.db.query(AISite).filter(AISite.url == url).first()
            if existing:
                # 기존 데이터 업데이트
                existing.is_ai_tool = analysis["is_ai_tool"]
                existing.title = analysis.get("title", "")
                existing.description = analysis.get("description", "")
                existing.score_utility = analysis.get("scores", {}).get("utility", 0)
                existing.score_trust = analysis.get("scores", {}).get("trust", 0)
                existing.score_originality = analysis.get("scores", {}).get("originality", 0)
                existing.last_analyzed_at = datetime.utcnow()
                self.db.add(existing)
                return existing

            # 새로운 사이트 추가
            site = AISite(
                url=url,
                is_ai_tool=analysis["is_ai_tool"],
                title=analysis.get("title", ""),
                description=analysis.get("description", ""),
                score_utility=analysis.get("scores", {}).get("utility", 0),
                score_trust=analysis.get("scores", {}).get("trust", 0),
                score_originality=analysis.get("scores", {}).get("originality", 0),
                last_analyzed_at=datetime.utcnow(),
            )
            self.db.add(site)
            self.db.flush()  # ID 생성
            return site

        except Exception as e:
            logger.error(f"사이트 저장 실패: {e}")
            return None

    def _save_categories_and_tags(
        self,
        site_id: int,
        categories: list[dict[str, Any]],
        tags: list[str],
    ) -> None:
        """카테고리·태그 일괄 삭제 후 재저장 (flush 1회)."""
        try:
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

        except Exception as e:
            logger.error(f"카테고리/태그 저장 실패: {e}")
