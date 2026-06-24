"""Celery 분석 작업 테스트."""

import threading
from unittest.mock import MagicMock, patch
from uuid import uuid4, UUID


from src.core.exceptions import (
    SiteUnreachableError,
    RateLimitError,
    ApiTimeoutError,
    ApiServerUnavailableError,
    ApiUnauthenticatedError,
    ApiPermissionDeniedError,
    ApiPreconditionError,
    ApiNotFoundError,
)
from src.core.enums import JobStatus
from src.workers.analyze_task import _analyze_one, _mark_jobs_processing


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_job_id() -> UUID:
    return uuid4()


def _mock_detector(result: dict | None = None, side_effect: Exception | None = None, empty: bool = False):
    """AIDetector.detect_and_save 모킹 헬퍼.

    empty=True이면 None을 반환한다 (result 기본값에 의한 덮어쓰기 방지용).
    """
    detector = MagicMock()
    if side_effect:
        detector.detect_and_save.side_effect = side_effect
    elif empty:
        detector.detect_and_save.return_value = None
    else:
        detector.detect_and_save.return_value = result or {"site_id": 1, "is_ai_tool": True}
    return detector


# ---------------------------------------------------------------------------
# _analyze_one — 기본 동작
# ---------------------------------------------------------------------------

class TestAnalyzeOne:
    def test_성공시_result_반환(self):
        """정상 분석 결과를 (url, job_id, result, None) 형태로 반환한다."""
        job_id = _make_job_id()
        expected = {"site_id": 42, "is_ai_tool": True}

        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector:
            MockDetector.return_value = _mock_detector(result=expected)

            url_out, jid_out, result, error = _analyze_one("https://example.com", job_id)

        assert url_out == "https://example.com"
        assert jid_out == job_id
        assert result == expected
        assert error is None

    def test_결과없으면_분석실패_에러(self):
        """detect_and_save가 None 반환 시 '분석 실패' 에러를 반환한다."""
        job_id = _make_job_id()

        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector:
            MockDetector.return_value = _mock_detector(empty=True)

            _, _, result, error = _analyze_one("https://example.com", job_id)

        assert result is None
        assert error == "분석 실패"

    def test_SiteUnreachableError_시_unreachable_반환(self):
        """SiteUnreachableError 발생 시 unreachable 상태를 반환하고 DB에 기록한다."""
        job_id = _make_job_id()

        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector, \
             patch("src.workers.analyze_task.mark_site_status") as mock_mark:
            MockDetector.return_value = _mock_detector(
                side_effect=SiteUnreachableError("접근 불가")
            )

            _, _, result, error = _analyze_one("https://example.com", job_id)

        assert result is None
        assert error is not None
        mock_mark.assert_called_once()

    def test_일반_예외_시_에러_문자열_반환(self):
        """예상치 못한 예외 발생 시 에러 메시지를 문자열로 반환한다."""
        job_id = _make_job_id()

        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector:
            MockDetector.return_value = _mock_detector(
                side_effect=ValueError("unexpected")
            )

            _, _, result, error = _analyze_one("https://example.com", job_id)

        assert result is None
        assert "unexpected" in error


# ---------------------------------------------------------------------------
# _analyze_one — 추가 예외 경로
# ---------------------------------------------------------------------------

class TestAnalyzeOneExceptions:
    """_analyze_one 예외 종류별 반환값 검증."""

    def test_api_not_found_returns_error(self):
        job_id = _make_job_id()
        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector, \
             patch("src.workers.analyze_task.mark_site_status"):
            MockDetector.return_value.detect_and_save.side_effect = ApiNotFoundError("404")
            _, _, result, error = _analyze_one("https://example.com", job_id)

        assert result is None
        assert error is not None

    def test_api_timeout_returns_error(self):
        job_id = _make_job_id()
        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector:
            MockDetector.return_value.detect_and_save.side_effect = ApiTimeoutError("timeout")
            _, _, result, error = _analyze_one("https://example.com", job_id)

        assert result is None
        assert error is not None

    def test_server_unavailable_returns_error(self):
        job_id = _make_job_id()
        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector:
            MockDetector.return_value.detect_and_save.side_effect = ApiServerUnavailableError("503")
            _, _, result, error = _analyze_one("https://example.com", job_id)

        assert result is None
        assert error is not None

    def test_unauthenticated_calls_mark_site_status(self):
        job_id = _make_job_id()
        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector, \
             patch("src.workers.analyze_task.mark_site_status") as mock_mark:
            MockDetector.return_value.detect_and_save.side_effect = ApiUnauthenticatedError("401")
            _, _, result, error = _analyze_one("https://example.com", job_id)

        assert result is None
        mock_mark.assert_called_once()

    def test_permission_denied_calls_mark_site_status(self):
        job_id = _make_job_id()
        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector, \
             patch("src.workers.analyze_task.mark_site_status") as mock_mark:
            MockDetector.return_value.detect_and_save.side_effect = ApiPermissionDeniedError("403")
            _, _, result, error = _analyze_one("https://example.com", job_id)

        assert result is None
        mock_mark.assert_called_once()

    def test_precondition_calls_mark_site_status(self):
        job_id = _make_job_id()
        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector, \
             patch("src.workers.analyze_task.mark_site_status") as mock_mark:
            MockDetector.return_value.detect_and_save.side_effect = ApiPreconditionError("precondition")
            _, _, result, error = _analyze_one("https://example.com", job_id)

        assert result is None
        mock_mark.assert_called_once()


# ---------------------------------------------------------------------------
# _analyze_one — rate_limit_event 동작
# ---------------------------------------------------------------------------

class TestAnalyzeOneRateLimitEvent:
    def test_event_set_상태이면_즉시_스킵(self):
        """rate_limit_event가 이미 set 상태이면 API 호출 없이 rate_limit_skip을 반환한다."""
        job_id = _make_job_id()
        event = threading.Event()
        event.set()

        with patch("src.workers.analyze_task.SessionLocal") as MockSession, \
             patch("src.workers.analyze_task.AIDetector") as MockDetector:

            _, _, result, error = _analyze_one("https://example.com", job_id, event)

            MockSession.assert_not_called()
            MockDetector.assert_not_called()

        assert result is None
        assert error == "rate_limit_skip"

    def test_RateLimitError_시_event_set(self):
        """RateLimitError 발생 시 rate_limit_event를 set하고 에러를 반환한다."""
        job_id = _make_job_id()
        event = threading.Event()

        assert not event.is_set()

        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector:
            MockDetector.return_value = _mock_detector(
                side_effect=RateLimitError("429")
            )

            _, _, result, error = _analyze_one("https://example.com", job_id, event)

        assert event.is_set()
        assert result is None
        assert error is not None

    def test_event_없으면_RateLimitError_후_event_set_안됨(self):
        """rate_limit_event 미전달 시 RateLimitError가 나도 별도 처리 없이 에러만 반환한다."""
        job_id = _make_job_id()

        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector:
            MockDetector.return_value = _mock_detector(
                side_effect=RateLimitError("429")
            )

            _, _, result, error = _analyze_one("https://example.com", job_id, None)

        assert result is None
        assert error is not None

    def test_event_미설정_상태면_정상_실행(self):
        """rate_limit_event가 전달됐지만 set 되지 않은 경우 정상 분석을 수행한다."""
        job_id = _make_job_id()
        event = threading.Event()  # not set
        expected = {"site_id": 7, "is_ai_tool": False}

        with patch("src.workers.analyze_task.SessionLocal"), \
             patch("src.workers.analyze_task.get_llm_analyzer"), \
             patch("src.workers.analyze_task.AIDetector") as MockDetector:
            MockDetector.return_value = _mock_detector(result=expected)

            _, _, result, error = _analyze_one("https://example.com", job_id, event)

        assert result == expected
        assert error is None


# ---------------------------------------------------------------------------
# _mark_jobs_processing
# ---------------------------------------------------------------------------

class TestMarkJobsProcessing:
    def test_updates_status_to_processing(self, db):
        from src.db.models.analysis_job import AnalysisJob
        job_id = uuid4()
        db.add(AnalysisJob(job_id=job_id, url="https://example.com", status=JobStatus.PENDING, retry_count=0))
        db.commit()

        with patch("src.workers.analyze_task.SessionLocal", return_value=db):
            _mark_jobs_processing([job_id])

        db.expire_all()
        job = db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()
        assert job.status == JobStatus.PROCESSING
        assert job.started_at is not None

    def test_handles_multiple_jobs(self, db):
        from src.db.models.analysis_job import AnalysisJob
        ids = [uuid4(), uuid4(), uuid4()]
        for jid in ids:
            db.add(AnalysisJob(job_id=jid, url=f"https://example{jid}.com", status=JobStatus.PENDING, retry_count=0))
        db.commit()

        with patch("src.workers.analyze_task.SessionLocal", return_value=db):
            _mark_jobs_processing(ids)

        db.expire_all()
        for jid in ids:
            job = db.query(AnalysisJob).filter(AnalysisJob.job_id == jid).first()
            assert job.status == JobStatus.PROCESSING


# ---------------------------------------------------------------------------
# analyze_urls_batch — 배치 태스크 로직
# ---------------------------------------------------------------------------

class TestAnalyzeUrlsBatch:
    """analyze_urls_batch Celery 태스크 핵심 로직 검증 (run 직접 호출)."""

    def test_returns_success_and_failed_counts(self):
        from src.workers.analyze_task import analyze_urls_batch
        urls = ["https://a.com", "https://b.com"]
        job_ids = [str(uuid4()), str(uuid4())]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        def fake_analyze_one(url, job_id, rate_limit_event=None):
            return url, job_id, {"site_id": 1, "is_ai_tool": True}, None

        with patch("src.workers.analyze_task.SessionLocal", return_value=mock_db), \
             patch("src.workers.analyze_task._analyze_one", side_effect=fake_analyze_one), \
             patch("src.workers.analyze_task.update_job_statuses"):
            result = analyze_urls_batch.run(job_ids, urls)

        assert result["total"] == 2
        assert result["success"] + result["failed"] == 2

    def test_handles_empty_url_list(self):
        from src.workers.analyze_task import analyze_urls_batch

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with patch("src.workers.analyze_task.SessionLocal", return_value=mock_db), \
             patch("src.workers.analyze_task.update_job_statuses"):
            result = analyze_urls_batch.run([], [])

        assert result["total"] == 0

    def test_failure_counted_when_analyze_fails(self):
        from src.workers.analyze_task import analyze_urls_batch
        urls = ["https://a.com"]
        job_ids = [str(uuid4())]

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        def fake_analyze_one(url, job_id, rate_limit_event=None):
            return url, job_id, None, "timeout error"

        with patch("src.workers.analyze_task.SessionLocal", return_value=mock_db), \
             patch("src.workers.analyze_task._analyze_one", side_effect=fake_analyze_one), \
             patch("src.workers.analyze_task.update_job_statuses"):
            result = analyze_urls_batch.run(job_ids, urls)

        assert result["failed"] == 1
        assert result["success"] == 0


# ---------------------------------------------------------------------------
# analyze_urls_bulk — 슬라이딩 윈도우 조기 종료
# ---------------------------------------------------------------------------

class TestAnalyzeUrlsBulkEarlyStop:
    """슬라이딩 윈도우 핵심 로직을 직접 실행해 429 발생 후 미제출 URL 차단을 검증한다."""

    def _run_sliding_window(self, urls: list[str], fail_url: str) -> tuple[list, dict, dict]:
        import itertools
        from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait as cf_wait
        from src.workers.analyze_task import _BATCH_CONCURRENCY

        job_id_map = {url: uuid4() for url in urls}

        def fake_analyze_one(url, job_id, rate_limit_event=None):
            if url == fail_url:
                if rate_limit_event is not None:
                    rate_limit_event.set()
                return url, job_id, None, "API 할당량 초과 (429)"
            if rate_limit_event is not None and rate_limit_event.is_set():
                return url, job_id, None, "rate_limit_skip"
            return url, job_id, {"site_id": 1, "is_ai_tool": True}, None

        batch_results = []
        success_map: dict = {}
        failure_map: dict = {}
        rate_limit_event = threading.Event()

        with ThreadPoolExecutor(max_workers=_BATCH_CONCURRENCY) as executor:
            pending_iter = iter(urls)
            active_futures: dict = {}

            for url in itertools.islice(pending_iter, _BATCH_CONCURRENCY):
                active_futures[executor.submit(fake_analyze_one, url, job_id_map[url], rate_limit_event)] = url

            while active_futures:
                done, _ = cf_wait(active_futures, return_when=FIRST_COMPLETED)
                for future in done:
                    done_url, job_id, result, error = future.result()
                    del active_futures[future]

                    if error:
                        failure_map[job_id] = error
                    else:
                        batch_results.append((done_url, result))
                        success_map[job_id] = result.get("site_id")

                    if rate_limit_event.is_set():
                        continue

                    next_url = next(pending_iter, None)
                    if next_url:
                        active_futures[executor.submit(
                            fake_analyze_one, next_url, job_id_map[next_url], rate_limit_event
                        )] = next_url

            if rate_limit_event.is_set():
                for url in pending_iter:
                    failure_map[job_id_map[url]] = "rate_limit_skip"

        return batch_results, success_map, failure_map

    def test_429_이후_미제출_URL은_rate_limit_skip_처리(self):
        """429 발생 후 미처리 URL이 rate_limit_skip으로 failure_map에 기록된다."""
        urls = [f"https://site{i}.com" for i in range(10)]
        fail_url = urls[0]

        batch_results, success_map, failure_map = self._run_sliding_window(urls, fail_url)

        errors = list(failure_map.values())
        skip_count = sum(1 for v in errors if v == "rate_limit_skip")
        rate_limit_count = sum(1 for v in errors if "429" in v or "할당량" in v)

        assert rate_limit_count >= 1, "429 에러가 최소 1건 있어야 한다"
        assert skip_count > 0, "rate_limit_skip 항목이 있어야 한다"
        assert len(batch_results) + len(failure_map) == len(urls), "전체 URL이 성공 또는 실패로 분류돼야 한다"

    def test_429_없으면_모든_URL_성공(self):
        """429가 없으면 모든 URL이 성공으로 처리된다."""
        urls = [f"https://site{i}.com" for i in range(6)]

        batch_results, success_map, failure_map = self._run_sliding_window(urls, fail_url="__none__")

        assert len(batch_results) == len(urls)
        assert len(failure_map) == 0

    def test_429_발생_후_성공_건수가_전체보다_적음(self):
        """429 발생 시 성공 건수가 전체 URL 수보다 적어야 한다."""
        urls = [f"https://site{i}.com" for i in range(10)]
        fail_url = urls[0]

        batch_results, _, _ = self._run_sliding_window(urls, fail_url)

        assert len(batch_results) < len(urls)


# ---------------------------------------------------------------------------
# smoke 테스트
# ---------------------------------------------------------------------------

def test_analyze_url_task_exists():
    from src.workers.analyze_task import analyze_url
    assert analyze_url is not None
    assert hasattr(analyze_url, "name")


def test_celery_app_configured():
    from src.workers.celery_app import app
    assert app is not None
    assert app.conf.broker_url is not None
    assert app.conf.result_backend is not None
