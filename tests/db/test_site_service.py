"""src/db/site_service.py — AIDetector 단위 테스트."""

import pytest
from unittest.mock import MagicMock, patch
from src.db.site_service import AIDetector
from src.core.exceptions import SiteUnreachableError, RateLimitError


def _make_analysis(
    is_ai_tool: bool = True,
    title: str = "TestAI",
    description: str = "AI 도구",
    confidence: float = 0.9,
    categories: list | None = None,
    tags: list | None = None,
    scores: dict | None = None,
    analyzer: str = "gemini",
) -> dict:
    return {
        "is_ai_tool": is_ai_tool,
        "title": title,
        "description": description,
        "confidence": confidence,
        "categories": categories or [{"level_1": "AI", "level_2": "Chat", "is_primary": True}],
        "tags": tags or ["chatbot"],
        "scores": scores or {"utility": 8, "trust": 7, "originality": 6},
        "analyzer": analyzer,
    }


class TestAIDetectorValidation:
    """_validate_analysis 검증 로직 테스트."""

    def setup_method(self):
        self.detector = AIDetector(db=MagicMock(), analyzer=MagicMock())

    def test_valid_analysis_passes(self):
        assert self.detector._validate_analysis(_make_analysis()) is True

    def test_missing_required_field_fails(self):
        analysis = _make_analysis()
        del analysis["is_ai_tool"]
        assert self.detector._validate_analysis(analysis) is False

    def test_missing_title_fails(self):
        analysis = _make_analysis()
        del analysis["title"]
        assert self.detector._validate_analysis(analysis) is False

    def test_confidence_out_of_range_fails(self):
        analysis = _make_analysis(confidence=1.5)
        assert self.detector._validate_analysis(analysis) is False

    def test_negative_confidence_fails(self):
        analysis = _make_analysis(confidence=-0.1)
        assert self.detector._validate_analysis(analysis) is False

    def test_zero_confidence_passes(self):
        assert self.detector._validate_analysis(_make_analysis(confidence=0.0)) is True

    def test_one_confidence_passes(self):
        assert self.detector._validate_analysis(_make_analysis(confidence=1.0)) is True


class TestAIDetectorSaveSite:
    """_save_site DB 저장 로직 테스트."""

    def test_creates_new_site_when_not_exists(self, db):
        # SQLite는 BigInteger PK autoincrement 미지원 — mock DB로 신규 생성 로직 검증
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        detector = AIDetector(db=mock_db, analyzer=MagicMock())
        analysis = _make_analysis()

        detector._save_site("https://example.com", analysis)

        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.url == "https://example.com"
        assert added_obj.is_ai_tool is True
        assert added_obj.title == "TestAI"

    def test_updates_existing_site(self, db):
        from sqlalchemy import text
        db.execute(text(
            "INSERT INTO ai_site (site_id, url, is_ai_tool, status) "
            "VALUES (1, 'https://example.com', 0, 'ok')"
        ))
        db.commit()

        analyzer_mock = MagicMock()
        detector = AIDetector(db=db, analyzer=analyzer_mock)
        analysis = _make_analysis(is_ai_tool=True, title="Updated")

        site = detector._save_site("https://example.com", analysis)

        assert site.is_ai_tool is True
        assert site.title == "Updated"

    def test_unreachable_since_cleared_on_save(self, db):
        from sqlalchemy import text
        from src.core.util import utc_now
        db.execute(text(
            "INSERT INTO ai_site (site_id, url, is_ai_tool, status, unreachable_since) "
            "VALUES (1, 'https://example.com', 0, 'unreachable', :ts)"
        ), {"ts": utc_now()})
        db.commit()

        analyzer_mock = MagicMock()
        detector = AIDetector(db=db, analyzer=analyzer_mock)
        site = detector._save_site("https://example.com", _make_analysis())

        assert site.unreachable_since is None


class TestAIDetectorSaveCategoriesAndTags:
    """_save_categories_and_tags 카테고리·태그 저장 테스트 (mock DB)."""

    def test_saves_categories(self):
        mock_db = MagicMock()
        detector = AIDetector(db=mock_db, analyzer=MagicMock())
        categories = [
            {"level_1": "AI", "level_2": "Chat", "is_primary": True},
            {"level_1": "AI", "level_2": "Tools", "is_primary": False},
        ]
        detector._save_categories_and_tags(1, categories, [])

        # AICategory 2개 + AITag 0개 = add 2번 호출
        assert mock_db.add.call_count == 2

    def test_saves_tags(self):
        mock_db = MagicMock()
        detector = AIDetector(db=mock_db, analyzer=MagicMock())
        detector._save_categories_and_tags(1, [], ["chatbot", "nlp", "ai"])

        assert mock_db.add.call_count == 3

    def test_deletes_before_inserting(self):
        mock_db = MagicMock()
        detector = AIDetector(db=mock_db, analyzer=MagicMock())
        detector._save_categories_and_tags(1, [{"level_1": "A", "level_2": "B", "is_primary": True}], ["tag1"])

        # delete가 2번(category, tag) 호출되었는지 확인
        assert mock_db.query.call_count >= 2

    def test_deletes_then_reinserts(self):
        # 두 번 호출 시 delete 후 재삽입이 발생하는지 mock으로 확인
        mock_db = MagicMock()
        detector = AIDetector(db=mock_db, analyzer=MagicMock())
        detector._save_categories_and_tags(1, [{"level_1": "Old", "level_2": "Cat", "is_primary": True}], [])
        detector._save_categories_and_tags(1, [{"level_1": "New", "level_2": "Cat2", "is_primary": True}], [])

        # delete()가 각 호출에서 2번씩 총 4번 이상 호출됨
        assert mock_db.query.call_count >= 4


class TestAIDetectorDetectAndSave:
    """detect_and_save 전체 흐름 테스트."""

    def test_returns_result_on_success(self):
        # SQLite BigInteger PK 제약으로 mock DB 사용
        analysis = _make_analysis()
        analyzer_mock = MagicMock()
        analyzer_mock.analyze_website.return_value = analysis

        mock_db = MagicMock()
        fake_site = MagicMock()
        fake_site.site_id = 42
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add.return_value = None
        mock_db.flush.return_value = None

        with patch.object(AIDetector, "_save_site", return_value=fake_site), \
             patch.object(AIDetector, "_save_categories_and_tags", return_value=None):
            detector = AIDetector(db=mock_db, analyzer=analyzer_mock)
            result = detector.detect_and_save("https://example.com")

        assert result is not None
        assert result["is_ai_tool"] is True
        assert result["title"] == "TestAI"

    def test_returns_none_on_validation_failure(self):
        analyzer_mock = MagicMock()
        analyzer_mock.analyze_website.return_value = {"bad": "data"}

        detector = AIDetector(db=MagicMock(), analyzer=analyzer_mock)
        result = detector.detect_and_save("https://example.com")

        assert result is None

    def test_raises_site_unreachable(self):
        analyzer_mock = MagicMock()
        analyzer_mock.analyze_website.side_effect = SiteUnreachableError("접근 불가")

        mock_db = MagicMock()
        detector = AIDetector(db=mock_db, analyzer=analyzer_mock)
        with pytest.raises(SiteUnreachableError):
            detector.detect_and_save("https://example.com")

    def test_raises_rate_limit(self):
        analyzer_mock = MagicMock()
        analyzer_mock.analyze_website.side_effect = RateLimitError("429")

        mock_db = MagicMock()
        detector = AIDetector(db=mock_db, analyzer=analyzer_mock)
        with pytest.raises(RateLimitError):
            detector.detect_and_save("https://example.com")

    def test_returns_none_on_generic_exception(self):
        analyzer_mock = MagicMock()
        analyzer_mock.analyze_website.side_effect = RuntimeError("unexpected")

        detector = AIDetector(db=MagicMock(), analyzer=analyzer_mock)
        result = detector.detect_and_save("https://example.com")

        assert result is None
