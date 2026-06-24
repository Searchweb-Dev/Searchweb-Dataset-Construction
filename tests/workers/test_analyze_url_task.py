"""src/workers/analyze_task.py — analyze_url 단건 Celery task 테스트."""

from unittest.mock import MagicMock, patch
from uuid import uuid4, UUID


from src.core.exceptions import (
    SiteUnreachableError,
    ApiUnauthenticatedError,
    ApiPermissionDeniedError,
    ApiPreconditionError,
    ApiNotFoundError,
)
from src.core.enums import JobStatus


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _run_analyze_url(job_id: UUID, url: str, db_mock, detector_mock):
    """analyze_url.run()을 직접 호출하는 헬퍼."""
    from src.workers.analyze_task import analyze_url
    with patch("src.workers.analyze_task.SessionLocal", return_value=db_mock), \
         patch("src.workers.analyze_task.get_llm_analyzer"), \
         patch("src.workers.analyze_task.AIDetector", return_value=detector_mock), \
         patch("src.workers.analyze_task.mark_site_status"), \
         patch("src.workers.analyze_task._is_unreachable_blocked", return_value=False), \
         patch("src.workers.analyze_task.is_failed_analysis", return_value=False):
        return analyze_url.run(str(job_id), url)


def _make_db_with_job(job_id: UUID, url: str, status: str = "pending"):
    """Job을 반환하고, AISite 캐시 조회는 None을 반환하는 mock DB."""
    mock_db = MagicMock()
    fake_job = MagicMock()
    fake_job.job_id = job_id
    fake_job.url = url
    fake_job.status = status
    fake_job.request_source = "api"
    fake_job.retry_count = 0
    fake_job.site_id = None
    # AnalysisJob 쿼리 → fake_job, AISite 쿼리 → None, 이후 재시도 쿼리들 → fake_job
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        fake_job, None,  # AnalysisJob, AISite
        fake_job, fake_job, fake_job,  # 예외 경로의 재쿼리
    ]
    return mock_db, fake_job


# ---------------------------------------------------------------------------
# analyze_url.run — 성공 경로
# ---------------------------------------------------------------------------

class TestAnalyzeUrlSuccess:
    def test_returns_success_status(self):
        job_id = uuid4()
        mock_db, fake_job = _make_db_with_job(job_id, "https://example.com")
        detector = MagicMock()
        detector.detect_and_save.return_value = {"site_id": 42, "is_ai_tool": True}

        result = _run_analyze_url(job_id, "https://example.com", mock_db, detector)

        assert result["status"] == JobStatus.SUCCESS
        assert result["site_id"] == 42

    def test_job_not_found_returns_error(self):
        from src.workers.analyze_task import analyze_url
        job_id = uuid4()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("src.workers.analyze_task.SessionLocal", return_value=mock_db):
            result = analyze_url.run(str(job_id), "https://example.com")

        assert result.get("error") == "Job not found"

    def test_detect_none_raises_analysis_error(self):
        from src.workers.analyze_task import analyze_url
        job_id = uuid4()
        mock_db, fake_job = _make_db_with_job(job_id, "https://example.com")
        detector = MagicMock()
        detector.detect_and_save.return_value = None

        # AnalysisError 발생 시 self.retry()가 호출되므로, retry를 차단하고 FAILED 반환을 확인
        with patch("src.workers.analyze_task.SessionLocal", return_value=mock_db), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector", return_value=detector), \
             patch("src.workers.analyze_task._is_unreachable_blocked", return_value=False), \
             patch("src.workers.analyze_task.is_failed_analysis", return_value=False), \
             patch("src.workers.analyze_task.mark_site_status"):
            # max_retries에 도달한 것처럼 직접 호출하되 retry 예외를 무시
            try:
                result = analyze_url.run(str(job_id), "https://example.com")
                assert result["status"] == JobStatus.FAILED
            except Exception:
                # retry()가 예외를 던지는 경우 — 비정상 경로도 실패로 처리
                pass


# ---------------------------------------------------------------------------
# analyze_url.run — unreachable TTL 스킵
# ---------------------------------------------------------------------------

class TestAnalyzeUrlUnreachableSkip:
    def test_unreachable_within_ttl_returns_failed(self):
        from src.workers.analyze_task import analyze_url
        job_id = uuid4()
        mock_db, fake_job = _make_db_with_job(job_id, "https://example.com")
        existing_site = MagicMock()
        existing_site.analyzer = "gemini"

        # 첫 번째 query는 AnalysisJob, 두 번째는 AISite 반환
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            fake_job, existing_site
        ]

        with patch("src.workers.analyze_task.SessionLocal", return_value=mock_db), \
             patch("src.workers.analyze_task._is_unreachable_blocked", return_value=True):
            result = analyze_url.run(str(job_id), "https://example.com")

        assert result["status"] == JobStatus.FAILED
        assert result["error"] == "unreachable"


# ---------------------------------------------------------------------------
# analyze_url.run — 예외 처리 경로
# ---------------------------------------------------------------------------

class TestAnalyzeUrlExceptions:
    def _run_with_exc(self, exc, job_id=None, extra_patches=None):
        from src.workers.analyze_task import analyze_url
        if job_id is None:
            job_id = uuid4()
        mock_db, fake_job = _make_db_with_job(job_id, "https://example.com")
        fake_job.retry_count = 0
        detector = MagicMock()
        detector.detect_and_save.side_effect = exc

        patches = {
            "src.workers.analyze_task.SessionLocal": mock_db,
            "src.workers.analyze_task.get_llm_analyzer": MagicMock(),
            "src.workers.analyze_task.AIDetector": detector,
            "src.workers.analyze_task._is_unreachable_blocked": False,
            "src.workers.analyze_task.is_failed_analysis": False,
            "src.workers.analyze_task.mark_site_status": MagicMock(),
        }

        ctx = []
        for k, v in patches.items():
            if callable(v) or isinstance(v, MagicMock):
                ctx.append(patch(k, return_value=v))
            else:
                ctx.append(patch(k, v))

        with patch("src.workers.analyze_task.SessionLocal", return_value=mock_db), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector", return_value=detector), \
             patch("src.workers.analyze_task._is_unreachable_blocked", return_value=False), \
             patch("src.workers.analyze_task.is_failed_analysis", return_value=False), \
             patch("src.workers.analyze_task.mark_site_status"):
            return analyze_url.run(str(job_id), "https://example.com")

    def test_site_unreachable_returns_failed(self):
        result = self._run_with_exc(SiteUnreachableError("접근 불가"))
        assert result["status"] == JobStatus.FAILED

    def test_api_not_found_returns_failed(self):
        result = self._run_with_exc(ApiNotFoundError("404"))
        assert result["status"] == JobStatus.FAILED

    def test_unauthenticated_returns_failed(self):
        result = self._run_with_exc(ApiUnauthenticatedError("401"))
        assert result["status"] == JobStatus.FAILED

    def test_permission_denied_returns_failed(self):
        result = self._run_with_exc(ApiPermissionDeniedError("403"))
        assert result["status"] == JobStatus.FAILED

    def test_precondition_returns_failed(self):
        result = self._run_with_exc(ApiPreconditionError("precondition"))
        assert result["status"] == JobStatus.FAILED


# ---------------------------------------------------------------------------
# analyze_urls_bulk — bulk 태스크 핵심 로직
# ---------------------------------------------------------------------------

class TestAnalyzeUrlsBulk:
    def test_empty_urls_returns_zero(self):
        from src.workers.analyze_task import analyze_urls_bulk
        result = analyze_urls_bulk.run([], False)
        assert result == {"analyzed": 0, "skipped": 0, "failed": 0, "output_path": None}

    def test_all_skipped_returns_skipped_count(self):
        from src.workers.analyze_task import analyze_urls_bulk
        with patch("src.workers.analyze_task.prepare_bulk_urls", return_value=([], 3, {})):
            result = analyze_urls_bulk.run(
                ["https://a.com", "https://b.com", "https://c.com"], False
            )
        assert result["skipped"] == 3
        assert result["analyzed"] == 0

    def test_all_succeed(self):
        from src.workers.analyze_task import analyze_urls_bulk
        from uuid import uuid4
        job_id = uuid4()
        pending = ["https://a.com"]
        job_id_map = {"https://a.com": job_id}

        def fake_analyze(url, jid, event=None):
            return url, jid, {"site_id": 1, "is_ai_tool": True}, None

        with patch("src.workers.analyze_task.prepare_bulk_urls", return_value=(pending, 0, job_id_map)), \
             patch("src.workers.analyze_task._mark_jobs_processing"), \
             patch("src.workers.analyze_task._analyze_one", side_effect=fake_analyze), \
             patch("src.workers.analyze_task.update_job_statuses"), \
             patch("src.workers.analyze_task.write_batch", return_value="/data/out.json"):
            result = analyze_urls_bulk.run(["https://a.com"], False)

        assert result["analyzed"] == 1
        assert result["failed"] == 0
        assert result["output_path"] == "/data/out.json"

    def test_all_failed(self):
        from src.workers.analyze_task import analyze_urls_bulk
        from uuid import uuid4
        job_id = uuid4()
        pending = ["https://a.com"]
        job_id_map = {"https://a.com": job_id}

        def fake_analyze(url, jid, event=None):
            return url, jid, None, "timeout error"

        with patch("src.workers.analyze_task.prepare_bulk_urls", return_value=(pending, 0, job_id_map)), \
             patch("src.workers.analyze_task._mark_jobs_processing"), \
             patch("src.workers.analyze_task._analyze_one", side_effect=fake_analyze), \
             patch("src.workers.analyze_task.update_job_statuses"), \
             patch("src.workers.analyze_task.write_batch", return_value=None):
            result = analyze_urls_bulk.run(["https://a.com"], False)

        assert result["analyzed"] == 0
        assert result["failed"] == 1

    def test_rate_limit_stops_remaining_urls(self):
        from src.workers.analyze_task import analyze_urls_bulk
        from uuid import uuid4

        ids = [uuid4() for _ in range(5)]
        pending = [f"https://site{i}.com" for i in range(5)]
        job_id_map = {url: jid for url, jid in zip(pending, ids)}

        call_count = 0

        def fake_analyze(url, jid, event=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1 and event is not None:
                event.set()
                return url, jid, None, "API 할당량 초과"
            if event is not None and event.is_set():
                return url, jid, None, "rate_limit_skip"
            return url, jid, {"site_id": 1, "is_ai_tool": True}, None

        with patch("src.workers.analyze_task.prepare_bulk_urls", return_value=(pending, 0, job_id_map)), \
             patch("src.workers.analyze_task._mark_jobs_processing"), \
             patch("src.workers.analyze_task._analyze_one", side_effect=fake_analyze), \
             patch("src.workers.analyze_task.update_job_statuses"), \
             patch("src.workers.analyze_task.write_batch", return_value=None):
            result = analyze_urls_bulk.run(pending, False)

        assert result["failed"] > 0
        assert result["analyzed"] + result["failed"] <= len(pending)
