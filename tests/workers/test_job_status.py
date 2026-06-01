"""src/workers/job_status.py — job 상태 갱신 단위 테스트."""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch
from src.workers.job_status import is_failed_analysis, mark_site_status, update_job_statuses
from src.db.models.ai_site import SITE_STATUS_OK, SITE_STATUS_UNREACHABLE, SITE_STATUS_BLOCKED, SITE_STATUS_FAILURE
from src.core.enums import JobStatus


class TestIsFailedAnalysis:
    """is_failed_analysis 실패 상태 판별 검증."""

    def _make_site(self, status: str) -> MagicMock:
        site = MagicMock()
        site.status = status
        return site

    def test_failure_status_is_failed(self):
        assert is_failed_analysis(self._make_site(SITE_STATUS_FAILURE)) is True

    def test_blocked_status_is_failed(self):
        assert is_failed_analysis(self._make_site(SITE_STATUS_BLOCKED)) is True

    def test_unreachable_not_failed(self):
        assert is_failed_analysis(self._make_site(SITE_STATUS_UNREACHABLE)) is False

    def test_success_not_failed(self):
        assert is_failed_analysis(self._make_site("curated")) is False


class TestMarkSiteStatus:
    """mark_site_status DB 갱신 검증."""

    _site_id_counter = 0

    def _insert_site(self, db, url: str, status: str, unreachable_since=None):
        """SQLite BigInteger PK는 autoincrement 미지원이므로 site_id를 명시한다."""
        from sqlalchemy import text
        TestMarkSiteStatus._site_id_counter += 1
        db.execute(text(
            "INSERT INTO ai_site (site_id, url, is_ai_tool, status, unreachable_since) "
            "VALUES (:sid, :url, 0, :status, :ts)"
        ), {"sid": TestMarkSiteStatus._site_id_counter, "url": url, "status": status, "ts": unreachable_since})
        db.commit()

    def test_updates_existing_site_status(self, db):
        from src.db.models.ai_site import AISite
        self._insert_site(db, "https://example.com", SITE_STATUS_OK)

        with patch("src.workers.job_status.SessionLocal", return_value=db):
            mark_site_status("https://example.com", SITE_STATUS_BLOCKED)

        site = db.query(AISite).filter(AISite.url == "https://example.com").first()
        assert site.status == SITE_STATUS_BLOCKED

    def test_creates_new_site_when_not_exists(self, db):
        # SQLite는 BigInteger PK autoincrement 미지원 — 신규 생성 로직은 PostgreSQL 환경에서 검증
        # 여기서는 실제 구현이 신규 AISite 생성을 시도함을 확인한다
        from src.db.models.ai_site import AISite
        from unittest.mock import MagicMock, call
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        with patch("src.workers.job_status.SessionLocal", return_value=mock_db):
            mark_site_status("https://newsite.com", SITE_STATUS_FAILURE)
        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert isinstance(added_obj, AISite)
        assert added_obj.status == SITE_STATUS_FAILURE

    def test_sets_unreachable_since_on_first_unreachable(self, db):
        from src.db.models.ai_site import AISite
        self._insert_site(db, "https://example.com", SITE_STATUS_OK)

        with patch("src.workers.job_status.SessionLocal", return_value=db):
            mark_site_status("https://example.com", SITE_STATUS_UNREACHABLE)

        site = db.query(AISite).filter(AISite.url == "https://example.com").first()
        assert site.unreachable_since is not None

    def test_preserves_existing_unreachable_since(self, db):
        from src.db.models.ai_site import AISite
        from src.core.util import utc_now
        original_ts = utc_now()
        self._insert_site(db, "https://example.com", SITE_STATUS_UNREACHABLE, unreachable_since=original_ts)

        with patch("src.workers.job_status.SessionLocal", return_value=db):
            mark_site_status("https://example.com", SITE_STATUS_UNREACHABLE)

        site = db.query(AISite).filter(AISite.url == "https://example.com").first()
        assert site.unreachable_since == original_ts


class TestUpdateJobStatuses:
    """update_job_statuses 일괄 상태 갱신 검증."""

    def _add_job(self, db, job_id, url: str) -> None:
        from src.db.models.analysis_job import AnalysisJob
        job = AnalysisJob(job_id=job_id, url=url, status=JobStatus.PROCESSING, retry_count=0)
        db.add(job)
        db.commit()

    def _get_job(self, db, job_id):
        from src.db.models.analysis_job import AnalysisJob
        db.expire_all()
        return db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()

    def test_marks_success_jobs(self, db):
        job_id = uuid4()
        self._add_job(db, job_id, "https://a.com")

        with patch("src.workers.job_status.SessionLocal", return_value=db):
            update_job_statuses({job_id: 42}, {})

        job = self._get_job(db, job_id)
        assert job.status == JobStatus.SUCCESS
        assert job.site_id == 42
        assert job.completed_at is not None

    def test_marks_failed_jobs(self, db):
        job_id = uuid4()
        self._add_job(db, job_id, "https://b.com")

        with patch("src.workers.job_status.SessionLocal", return_value=db):
            update_job_statuses({}, {job_id: "timeout error"})

        job = self._get_job(db, job_id)
        assert job.status == JobStatus.FAILED
        assert job.error_message == "timeout error"
        assert job.completed_at is not None

    def test_handles_mixed_success_and_failure(self, db):
        success_id = uuid4()
        fail_id = uuid4()
        self._add_job(db, success_id, "https://a.com")
        self._add_job(db, fail_id, "https://b.com")

        with patch("src.workers.job_status.SessionLocal", return_value=db):
            update_job_statuses({success_id: 1}, {fail_id: "err"})

        assert self._get_job(db, success_id).status == JobStatus.SUCCESS
        assert self._get_job(db, fail_id).status == JobStatus.FAILED
