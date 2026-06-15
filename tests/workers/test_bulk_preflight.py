"""src/workers/bulk_preflight.py — bulk preflight 단위 테스트."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from src.workers.bulk_preflight import _is_unreachable_blocked, prepare_bulk_urls
from src.db.models.ai_site import SITE_STATUS_OK, SITE_STATUS_UNREACHABLE


class TestIsUnreachableBlocked:
    """_is_unreachable_blocked TTL 이내 차단 판별 검증."""

    def _make_site(self, status: str, unreachable_since=None) -> MagicMock:
        site = MagicMock()
        site.status = status
        site.unreachable_since = unreachable_since
        return site

    def test_not_blocked_when_status_is_not_unreachable(self):
        site = self._make_site("curated")
        assert _is_unreachable_blocked(site) is False

    def test_not_blocked_when_unreachable_since_is_none(self):
        site = self._make_site(SITE_STATUS_UNREACHABLE, unreachable_since=None)
        assert _is_unreachable_blocked(site) is False

    def test_blocked_within_ttl(self):
        recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
        site = self._make_site(SITE_STATUS_UNREACHABLE, unreachable_since=recent)
        with patch("src.workers.bulk_preflight.get_unreachable_ttl_seconds", return_value=3600):
            assert _is_unreachable_blocked(site) is True

    def test_not_blocked_after_ttl_expired(self):
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25)
        site = self._make_site(SITE_STATUS_UNREACHABLE, unreachable_since=old)
        with patch("src.workers.bulk_preflight.get_unreachable_ttl_seconds", return_value=3600):
            assert _is_unreachable_blocked(site) is False


class TestPrepareBulkUrls:
    """prepare_bulk_urls 분석 대상 URL 필터링 검증."""

    def test_force_reanalyze_returns_all_urls(self, db):
        with patch("src.workers.bulk_preflight.SessionLocal", return_value=db):
            pending, skipped, job_id_map = prepare_bulk_urls(
                ["https://a.com", "https://b.com"],
                force_reanalyze=True,
            )
        assert len(pending) == 2
        assert skipped == 0

    def test_skips_unreachable_within_ttl(self, db):
        from sqlalchemy import text
        recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
        from src.core.url import normalize_url
        url = normalize_url("https://blocked.com")
        db.execute(text(
            "INSERT INTO ai_site (site_id, url, is_ai_tool, status, unreachable_since) "
            "VALUES (1, :url, 0, :status, :ts)"
        ), {"url": url, "status": SITE_STATUS_UNREACHABLE, "ts": recent})
        db.commit()

        with patch("src.workers.bulk_preflight.SessionLocal", return_value=db), \
             patch("src.workers.bulk_preflight.get_unreachable_ttl_seconds", return_value=3600):
            pending, skipped, _ = prepare_bulk_urls(["https://blocked.com"], force_reanalyze=False)

        assert skipped == 1
        assert len(pending) == 0

    def test_includes_new_url(self, db):
        with patch("src.workers.bulk_preflight.SessionLocal", return_value=db):
            pending, skipped, job_id_map = prepare_bulk_urls(
                ["https://brand-new.com"],
                force_reanalyze=False,
            )
        assert len(pending) == 1
        assert skipped == 0
        assert "https://brand-new.com" in job_id_map

    def test_job_id_map_contains_all_pending(self, db):
        with patch("src.workers.bulk_preflight.SessionLocal", return_value=db):
            pending, _, job_id_map = prepare_bulk_urls(
                ["https://a.com", "https://b.com"],
                force_reanalyze=True,
            )
        assert len(job_id_map) == len(pending)

    def test_reanalyzes_rule_analyzer_sites(self, db):
        from sqlalchemy import text
        from src.core.url import normalize_url
        url = normalize_url("https://rule-only.com")
        db.execute(text(
            "INSERT INTO ai_site (site_id, url, is_ai_tool, status, analyzer) "
            "VALUES (2, :url, 1, :status, 'rule')"
        ), {"url": url, "status": SITE_STATUS_OK})
        db.commit()

        with patch("src.workers.bulk_preflight.SessionLocal", return_value=db):
            pending, skipped, _ = prepare_bulk_urls(["https://rule-only.com"], force_reanalyze=False)

        assert len(pending) == 1
        assert skipped == 0

    def test_skips_llm_analyzed_sites(self, db):
        from sqlalchemy import text
        from src.core.url import normalize_url
        url = normalize_url("https://gemini-done.com")
        db.execute(text(
            "INSERT INTO ai_site (site_id, url, is_ai_tool, status, analyzer) "
            "VALUES (3, :url, 1, :status, 'gemini')"
        ), {"url": url, "status": SITE_STATUS_OK})
        db.commit()

        with patch("src.workers.bulk_preflight.SessionLocal", return_value=db):
            pending, skipped, _ = prepare_bulk_urls(["https://gemini-done.com"], force_reanalyze=False)

        assert skipped == 1
        assert len(pending) == 0
