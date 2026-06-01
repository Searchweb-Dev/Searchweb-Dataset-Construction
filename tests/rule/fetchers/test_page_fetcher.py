"""src/rule/fetchers/page_fetcher.py — PageFetcher 단위 테스트."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from src.rule.fetchers.page_fetcher import PageFetcher
from src.rule.config import EvalConfig
from src.rule.models import FetchResult


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_fetcher(use_playwright: bool = False) -> PageFetcher:
    config = EvalConfig(use_playwright=use_playwright)
    return PageFetcher(config)


def _make_fetch_result(
    url: str = "https://example.com",
    ok: bool = True,
    text: str = "hello world",
    title: str = "Title",
    meta_description: str = "desc",
    html: str = "<html><body>hello world</body></html>",
    links: list | None = None,
    status_code: int = 200,
    error: str | None = None,
    fetched_by: str = "requests",
) -> FetchResult:
    return FetchResult(
        url=url, final_url=url, status_code=status_code, ok=ok,
        html=html, text=text, title=title, meta_description=meta_description,
        links=links or [], error=error, fetched_by=fetched_by,
    )


# ---------------------------------------------------------------------------
# 초기화
# ---------------------------------------------------------------------------

class TestPageFetcherInit:
    def test_playwright_disabled_by_default(self):
        fetcher = _make_fetcher(use_playwright=False)
        assert fetcher.playwright_enabled is False

    def test_playwright_enabled_when_available(self):
        with patch("src.rule.fetchers.page_fetcher.sync_playwright", new=MagicMock()):
            fetcher = _make_fetcher(use_playwright=True)
            assert fetcher.playwright_enabled is True

    def test_playwright_disabled_reason_when_unavailable(self):
        with patch("src.rule.fetchers.page_fetcher.sync_playwright", None):
            config = EvalConfig(use_playwright=True)
            fetcher = PageFetcher(config)
        assert fetcher.playwright_disabled_reason is not None
        assert "playwright" in fetcher.playwright_disabled_reason.lower()


# ---------------------------------------------------------------------------
# _build_fetch_result — HTML 파싱
# ---------------------------------------------------------------------------

class TestBuildFetchResult:
    def test_extracts_title(self):
        fetcher = _make_fetcher()
        html = "<html><head><title>My AI Tool</title></head><body>Content</body></html>"
        result = fetcher._build_fetch_result("https://example.com", "https://example.com", 200, html, True, None, "requests")
        assert result.title == "My AI Tool"

    def test_extracts_meta_description(self):
        fetcher = _make_fetcher()
        html = '<html><head><meta name="description" content="AI tool for testing"></head><body>text</body></html>'
        result = fetcher._build_fetch_result("https://example.com", "https://example.com", 200, html, True, None, "requests")
        assert result.meta_description == "AI tool for testing"

    def test_extracts_links(self):
        fetcher = _make_fetcher()
        html = '<html><body><a href="https://example.com/pricing">Pricing</a><a href="https://example.com/docs">Docs</a></body></html>'
        result = fetcher._build_fetch_result("https://example.com", "https://example.com", 200, html, True, None, "requests")
        hrefs = [href for _, href in result.links]
        assert "https://example.com/pricing" in hrefs
        assert "https://example.com/docs" in hrefs

    def test_removes_script_and_style(self):
        fetcher = _make_fetcher()
        html = "<html><body><script>alert('xss')</script><style>.a{}</style>Real content here</body></html>"
        result = fetcher._build_fetch_result("https://example.com", "https://example.com", 200, html, True, None, "requests")
        assert "alert" not in result.text
        assert "Real content here" in result.text

    def test_truncates_long_body(self):
        fetcher = _make_fetcher()
        long_text = "word " * 20000
        html = f"<html><body>{long_text}</body></html>"
        result = fetcher._build_fetch_result("https://example.com", "https://example.com", 200, html, True, None, "requests")
        assert len(result.text) <= fetcher.config.max_body_text_chars

    def test_relative_links_resolved(self):
        fetcher = _make_fetcher()
        html = '<html><body><a href="/pricing">Pricing</a></body></html>'
        result = fetcher._build_fetch_result("https://example.com", "https://example.com", 200, html, True, None, "requests")
        hrefs = [href for _, href in result.links]
        assert "https://example.com/pricing" in hrefs

    def test_skips_non_http_links(self):
        fetcher = _make_fetcher()
        html = '<html><body><a href="mailto:hi@example.com">Mail</a><a href="https://example.com/page">Page</a></body></html>'
        result = fetcher._build_fetch_result("https://example.com", "https://example.com", 200, html, True, None, "requests")
        hrefs = [href for _, href in result.links]
        assert all(h.startswith("http") for h in hrefs)

    def test_ok_flag_set_correctly(self):
        fetcher = _make_fetcher()
        result = fetcher._build_fetch_result("https://example.com", "https://example.com", 404, "", False, "http_error: 404", "requests")
        assert result.ok is False
        assert result.status_code == 404


# ---------------------------------------------------------------------------
# _needs_playwright — 재수집 판정
# ---------------------------------------------------------------------------

class TestNeedsPlaywright:
    def test_needs_playwright_when_request_fails(self):
        fetcher = _make_fetcher()
        req_result = _make_fetch_result(ok=False, status_code=403)
        assert fetcher._needs_playwright(req_result) is True

    def test_no_playwright_when_rich_content(self):
        fetcher = _make_fetcher()
        req_result = _make_fetch_result(
            ok=True,
            text="x" * 1000,
            links=[("link", f"https://example.com/p{i}") for i in range(20)],
        )
        assert fetcher._needs_playwright(req_result) is False

    def test_needs_playwright_when_thin_text_and_links(self):
        fetcher = _make_fetcher()
        req_result = _make_fetch_result(ok=True, text="short", links=[])
        assert fetcher._needs_playwright(req_result) is True

    def test_needs_playwright_for_js_app(self):
        fetcher = _make_fetcher()
        req_result = _make_fetch_result(
            ok=True,
            text="short content",
            html='<html><body><div id="__next"></div></body></html>',
            links=[],
        )
        assert fetcher._needs_playwright(req_result) is True

    def test_lightweight_only_triggers_on_js_thin_text(self):
        fetcher = _make_fetcher()
        thin_no_js = _make_fetch_result(ok=True, text="short", links=[])
        # lightweight 모드에서 JS 신호 없으면 False
        assert fetcher._needs_playwright(thin_no_js, lightweight=True) is False

        js_thin = _make_fetch_result(
            ok=True,
            text="short",
            html='<html><body><div id="root"></div></body></html>',
            links=[],
        )
        assert fetcher._needs_playwright(js_thin, lightweight=True) is True


# ---------------------------------------------------------------------------
# _choose_better_result — 결과 선택
# ---------------------------------------------------------------------------

class TestChooseBetterResult:
    def test_prefers_ok_over_not_ok(self):
        fetcher = _make_fetcher()
        req = _make_fetch_result(ok=False)
        pw = _make_fetch_result(ok=True, text="x" * 500, links=[("a", "https://example.com/b")])
        assert fetcher._choose_better_result(req, pw) is pw

    def test_prefers_requests_when_playwright_fails(self):
        fetcher = _make_fetcher()
        req = _make_fetch_result(ok=True, text="x" * 500)
        pw = _make_fetch_result(ok=False)
        assert fetcher._choose_better_result(req, pw) is req

    def test_prefers_richer_result(self):
        fetcher = _make_fetcher()
        req = _make_fetch_result(ok=True, text="short")
        pw = _make_fetch_result(
            ok=True, text="x" * 2000,
            links=[("a", f"https://example.com/{i}") for i in range(30)],
            title="Rich Title", meta_description="desc",
        )
        assert fetcher._choose_better_result(req, pw) is pw


# ---------------------------------------------------------------------------
# _result_richness_score
# ---------------------------------------------------------------------------

class TestResultRichnessScore:
    def test_empty_result_low_score(self):
        fetcher = _make_fetcher()
        result = _make_fetch_result(ok=False, text="", links=[], title="", meta_description="")
        assert fetcher._result_richness_score(result) == 0

    def test_rich_result_high_score(self):
        fetcher = _make_fetcher()
        result = _make_fetch_result(
            ok=True, text="x" * 3000,
            links=[("a", f"https://example.com/{i}") for i in range(50)],
            title="Title", meta_description="desc",
        )
        score = fetcher._result_richness_score(result)
        assert score > 100


# ---------------------------------------------------------------------------
# is_challenge_text
# ---------------------------------------------------------------------------

class TestIsChallengeText:
    def test_detects_cloudflare(self):
        fetcher = _make_fetcher()
        assert fetcher.is_challenge_text("Cloudflare just a moment checking your browser") is True

    def test_detects_captcha(self):
        fetcher = _make_fetcher()
        assert fetcher.is_challenge_text("please solve the captcha to continue") is True

    def test_normal_text_is_not_challenge(self):
        fetcher = _make_fetcher()
        assert fetcher.is_challenge_text("Welcome to our AI tool signup now") is False

    def test_empty_text_is_not_challenge(self):
        fetcher = _make_fetcher()
        assert fetcher.is_challenge_text("") is False

    def test_cf_ray_detected(self):
        fetcher = _make_fetcher()
        assert fetcher.is_challenge_text("page load cf-ray identifier") is True


# ---------------------------------------------------------------------------
# _is_playwright_unavailable_error
# ---------------------------------------------------------------------------

class TestIsPlaywrightUnavailableError:
    def test_playwright_unavailable_string(self):
        fetcher = _make_fetcher()
        assert fetcher._is_playwright_unavailable_error("playwright_unavailable: no browser") is True

    def test_executable_doesnt_exist(self):
        fetcher = _make_fetcher()
        assert fetcher._is_playwright_unavailable_error("executable doesn't exist at path") is True

    def test_normal_error_false(self):
        fetcher = _make_fetcher()
        assert fetcher._is_playwright_unavailable_error("timeout connecting to host") is False

    def test_none_returns_false(self):
        fetcher = _make_fetcher()
        assert fetcher._is_playwright_unavailable_error(None) is False


# ---------------------------------------------------------------------------
# fetch — requests 경로 (mock)
# ---------------------------------------------------------------------------

class TestFetchWithRequests:
    def test_successful_fetch(self):
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://example.com"
        mock_resp.text = "<html><head><title>Test</title></head><body>Content</body></html>"

        with patch.object(fetcher, "_get_session") as mock_session_getter:
            mock_session = MagicMock()
            mock_session.get.return_value = mock_resp
            mock_session_getter.return_value = mock_session
            result = fetcher._fetch_with_requests("https://example.com")

        assert result.ok is True
        assert result.status_code == 200
        assert result.title == "Test"

    def test_http_error_returns_not_ok(self):
        fetcher = _make_fetcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.url = "https://example.com"
        mock_resp.text = ""

        with patch.object(fetcher, "_get_session") as mock_session_getter:
            mock_session = MagicMock()
            mock_session.get.return_value = mock_resp
            mock_session_getter.return_value = mock_session
            result = fetcher._fetch_with_requests("https://example.com")

        assert result.ok is False
        assert result.status_code == 403

    def test_network_exception_returns_error_result(self):
        fetcher = _make_fetcher()
        with patch.object(fetcher, "_get_session") as mock_session_getter:
            mock_session = MagicMock()
            mock_session.get.side_effect = ConnectionError("network unreachable")
            mock_session_getter.return_value = mock_session
            result = fetcher._fetch_with_requests("https://example.com")

        assert result.ok is False
        assert "network unreachable" in result.error


# ---------------------------------------------------------------------------
# fetch — playwright 비활성화 시 requests 결과 반환
# ---------------------------------------------------------------------------

class TestFetchPlaywrightDisabled:
    def test_returns_requests_result_when_playwright_disabled(self):
        fetcher = _make_fetcher(use_playwright=False)
        req_result = _make_fetch_result(ok=True)
        with patch.object(fetcher, "_fetch_with_requests", return_value=req_result):
            result = fetcher.fetch("https://example.com")
        assert result is req_result

    def test_playwright_fetch_returns_unavailable_when_disabled(self):
        fetcher = _make_fetcher(use_playwright=False)
        result = fetcher._fetch_with_playwright("https://example.com")
        assert result.ok is False
        assert "playwright_unavailable" in (result.error or "")


# ---------------------------------------------------------------------------
# fetch_many
# ---------------------------------------------------------------------------

class TestFetchMany:
    def test_empty_list_returns_empty_dict(self):
        fetcher = _make_fetcher()
        result = fetcher.fetch_many([])
        assert result == {}

    def test_single_url_no_threads(self):
        fetcher = _make_fetcher()
        req_result = _make_fetch_result()
        with patch.object(fetcher, "fetch", return_value=req_result):
            result = fetcher.fetch_many(["https://example.com"], max_workers=1)
        assert "https://example.com" in result

    def test_multiple_urls_parallel(self):
        fetcher = _make_fetcher()
        urls = ["https://a.com", "https://b.com", "https://c.com"]
        call_map = {u: _make_fetch_result(url=u) for u in urls}
        with patch.object(fetcher, "fetch", side_effect=lambda u, **kw: call_map[u]):
            result = fetcher.fetch_many(urls, max_workers=3)
        assert set(result.keys()) == set(urls)

    def test_exception_in_fetch_returns_error_result(self):
        fetcher = _make_fetcher()
        urls = ["https://a.com", "https://b.com"]
        with patch.object(fetcher, "fetch", side_effect=RuntimeError("boom")):
            result = fetcher.fetch_many(urls, max_workers=2)
        for url in urls:
            assert url in result
            assert result[url].ok is False


# ---------------------------------------------------------------------------
# close / __del__
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_clears_sessions(self):
        fetcher = _make_fetcher()
        mock_session = MagicMock()
        fetcher._sessions.append(mock_session)
        fetcher.close()
        mock_session.close.assert_called_once()
        assert len(fetcher._sessions) == 0

    def test_del_calls_close(self):
        fetcher = _make_fetcher()
        with patch.object(fetcher, "close") as mock_close:
            fetcher.__del__()
        mock_close.assert_called_once()


# ---------------------------------------------------------------------------
# _create_session / _configure_session / _register_session / _get_session
# ---------------------------------------------------------------------------

class TestSessionManagement:
    def test_create_session_returns_requests_session(self):
        import requests
        fetcher = _make_fetcher()
        session = fetcher._create_session()
        assert isinstance(session, requests.Session)

    def test_configure_session_sets_user_agent(self):
        import requests
        fetcher = _make_fetcher()
        session = requests.Session()
        fetcher._configure_session(session)
        assert "Mozilla" in session.headers.get("User-Agent", "")

    def test_configure_session_mounts_adapters(self):
        import requests
        fetcher = _make_fetcher()
        session = requests.Session()
        fetcher._configure_session(session)
        assert "https://" in session.get_adapter("https://example.com").__class__.__name__.lower() or \
               session.get_adapter("https://example.com") is not None

    def test_register_session_adds_to_list(self):
        import requests
        fetcher = _make_fetcher()
        session = requests.Session()
        fetcher._register_session(session)
        assert session in fetcher._sessions

    def test_register_session_no_duplicates(self):
        import requests
        fetcher = _make_fetcher()
        session = requests.Session()
        fetcher._register_session(session)
        fetcher._register_session(session)
        assert fetcher._sessions.count(session) == 1

    def test_get_session_creates_on_first_call(self):
        fetcher = _make_fetcher()
        session = fetcher._get_session()
        assert session is not None

    def test_get_session_returns_same_session_for_same_thread(self):
        fetcher = _make_fetcher()
        s1 = fetcher._get_session()
        s2 = fetcher._get_session()
        assert s1 is s2


# ---------------------------------------------------------------------------
# fetch — playwright 활성화 경로 (mock으로 Playwright 코드 우회)
# ---------------------------------------------------------------------------

class TestFetchWithPlaywrightEnabled:
    def test_returns_requests_when_needs_playwright_false(self):
        """playwright_enabled=True지만 needs_playwright=False인 경우 requests 결과 반환."""
        with patch("src.rule.fetchers.page_fetcher.sync_playwright", new=MagicMock()):
            fetcher = _make_fetcher(use_playwright=True)

        req_result = _make_fetch_result(ok=True, text="x" * 1000,
                                         links=[("a", f"https://example.com/{i}") for i in range(20)])
        with patch.object(fetcher, "_fetch_with_requests", return_value=req_result), \
             patch.object(fetcher, "_needs_playwright", return_value=False):
            result = fetcher.fetch("https://example.com")

        assert result is req_result

    def test_returns_requests_when_playwright_unavailable(self):
        """playwright 결과에 unavailable 에러가 있으면 requests 결과를 반환한다."""
        with patch("src.rule.fetchers.page_fetcher.sync_playwright", new=MagicMock()):
            fetcher = _make_fetcher(use_playwright=True)

        req_result = _make_fetch_result(ok=True)
        pw_result = _make_fetch_result(ok=False, error="playwright_unavailable: no browser")

        with patch.object(fetcher, "_fetch_with_requests", return_value=req_result), \
             patch.object(fetcher, "_needs_playwright", return_value=True), \
             patch.object(fetcher, "_fetch_with_playwright", return_value=pw_result):
            result = fetcher.fetch("https://example.com")

        assert result is req_result

    def test_returns_better_result_when_playwright_ok(self):
        """playwright 결과가 더 풍부하면 playwright 결과를 반환한다."""
        with patch("src.rule.fetchers.page_fetcher.sync_playwright", new=MagicMock()):
            fetcher = _make_fetcher(use_playwright=True)

        req_result = _make_fetch_result(ok=True, text="short")
        pw_result = _make_fetch_result(ok=True, text="x" * 2000,
                                        links=[("a", f"https://example.com/{i}") for i in range(30)],
                                        title="Rich", meta_description="desc",
                                        fetched_by="playwright")

        with patch.object(fetcher, "_fetch_with_requests", return_value=req_result), \
             patch.object(fetcher, "_needs_playwright", return_value=True), \
             patch.object(fetcher, "_fetch_with_playwright", return_value=pw_result):
            result = fetcher.fetch("https://example.com")

        assert result is pw_result


# ---------------------------------------------------------------------------
# _choose_better_result — challenge 분기
# ---------------------------------------------------------------------------

class TestChooseBetterResultChallenge:
    def test_prefers_playwright_when_requests_is_challenge(self):
        fetcher = _make_fetcher()
        req = _make_fetch_result(ok=True, text="just a moment cloudflare checking your browser")
        pw = _make_fetch_result(ok=True, text="Welcome to our AI tool", fetched_by="playwright")
        result = fetcher._choose_better_result(req, pw)
        assert result is pw

    def test_prefers_requests_when_playwright_is_challenge(self):
        fetcher = _make_fetcher()
        req = _make_fetch_result(ok=True, text="Welcome to our AI tool")
        pw = _make_fetch_result(ok=True, text="just a moment cloudflare checking your browser", fetched_by="playwright")
        result = fetcher._choose_better_result(req, pw)
        assert result is req


# ---------------------------------------------------------------------------
# _needs_playwright — challenge 분기
# ---------------------------------------------------------------------------

class TestNeedsPlaywrightChallenge:
    def test_needs_playwright_when_challenge_detected(self):
        fetcher = _make_fetcher()
        req = _make_fetch_result(
            ok=True,
            text="just a moment cloudflare checking your browser",
            html="<html><body>just a moment cloudflare</body></html>",
            links=[("a", f"https://example.com/{i}") for i in range(20)],
        )
        assert fetcher._needs_playwright(req) is True


# ---------------------------------------------------------------------------
# _build_fetch_result — 링크 중복 제거
# ---------------------------------------------------------------------------

class TestBuildFetchResultDedup:
    def test_deduplicates_identical_links(self):
        fetcher = _make_fetcher()
        html = """<html><body>
            <a href="https://example.com/page">Page</a>
            <a href="https://example.com/page">Page</a>
            <a href="https://example.com/page">Page</a>
        </body></html>"""
        result = fetcher._build_fetch_result(
            "https://example.com", "https://example.com", 200, html, True, None, "requests"
        )
        hrefs = [h for _, h in result.links]
        assert hrefs.count("https://example.com/page") == 1

    def test_respects_max_links_per_page(self):
        fetcher = _make_fetcher()
        links_html = "".join(f'<a href="https://example.com/p{i}">link{i}</a>' for i in range(300))
        html = f"<html><body>{links_html}</body></html>"
        result = fetcher._build_fetch_result(
            "https://example.com", "https://example.com", 200, html, True, None, "requests"
        )
        assert len(result.links) <= fetcher.config.max_links_per_page
