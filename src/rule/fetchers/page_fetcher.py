"""
requests/playwright 기반 웹페이지 수집(fetch) 기능을 제공하는 모듈.
"""

from __future__ import annotations

import threading
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.rule.config import EvalConfig
from src.rule.models import FetchResult
from src.rule.utils import lower, normalize_url, squash_ws

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    sync_playwright = None  # type: ignore[assignment]
    PlaywrightTimeoutError = TimeoutError  # type: ignore[assignment]


class PageFetcher:
    """requests/playwright를 조합해 웹페이지를 수집하는 fetcher."""

    def __init__(self, config: EvalConfig):
        """네트워크 세션과 브라우저 수집 옵션을 초기화한다."""
        self.config = config
        self.playwright_enabled = bool(self.config.use_playwright and sync_playwright is not None)
        self.playwright_disabled_reason: str | None = None
        if self.config.use_playwright and sync_playwright is None:
            self.playwright_disabled_reason = (
                "playwright_unavailable: playwright 패키지가 설치되지 않았습니다. "
                "pip install playwright 를 실행하세요."
            )
        self._thread_local = threading.local()
        self._playwright_resources_lock = threading.Lock()
        self._playwright_resources: list[dict[str, Any]] = []
        self._sessions_lock = threading.Lock()
        self._sessions: list[requests.Session] = []

    def fetch(self, url: str, lightweight: bool = False) -> FetchResult:
        """URL을 수집하고 requests/playwright 중 더 나은 결과를 반환한다."""
        normalized = normalize_url(url)
        req_result = self._fetch_with_requests(normalized)

        if not self.playwright_enabled:
            return req_result

        if self._needs_playwright(req_result, lightweight=lightweight):
            mode = "lightweight" if lightweight else "standard"
            logger.info("[%s] Playwright 수집 전환 (%s mode)", normalized, mode)
            pw_result = self._fetch_with_playwright(normalized, lightweight=lightweight)

            if self._is_playwright_unavailable_error(pw_result.error):
                logger.error("[%s] Playwright 실행 불가로 requests 결과 사용", normalized)
                return req_result

            better = self._choose_better_result(req_result, pw_result)
            if better is pw_result:
                logger.info("[%s] Playwright 결과 선택 (richness 점수 우세)", normalized)
            else:
                logger.info("[%s] Requests 결과 유지 (Playwright 결과 빈약)", normalized)
            return better

        return req_result

    def fetch_many(self, urls: list[str], max_workers: int = 4, lightweight: bool = False) -> dict[str, FetchResult]:
        """여러 URL을 병렬로 수집한다."""
        if not urls:
            return {}
        if max_workers <= 1 or len(urls) == 1:
            return {u: self.fetch(u, lightweight=lightweight) for u in urls}

        results: dict[str, FetchResult] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(self.fetch, u, lightweight): u for u in urls}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    results[url] = future.result()
                except Exception as e:
                    logger.error("[%s] fetch_many 도중 예외 발생: %s", url, e)
                    normalized = normalize_url(url)
                    results[url] = FetchResult(
                        url=normalized,
                        final_url=normalized,
                        status_code=0,
                        ok=False,
                        html="",
                        text="",
                        title="",
                        meta_description="",
                        links=[],
                        error=f"fetch_many_error: {e}",
                        fetched_by="requests",
                    )
        return results

    def _create_session(self) -> requests.Session:
        """thread-safe 병렬 수집을 위해 스레드별 requests session을 생성한다."""
        session = requests.Session()
        self._configure_session(session)
        return session

    def _configure_session(self, session: requests.Session) -> None:
        """요청 재시도/헤더 정책을 session에 공통 적용한다."""
        retries = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.4,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0 Safari/537.36"
                )
            }
        )

    def _register_session(self, session: requests.Session) -> None:
        """생성된 session을 종료 시 정리할 수 있도록 등록한다."""
        with self._sessions_lock:
            if session not in self._sessions:
                self._sessions.append(session)

    def _get_session(self) -> requests.Session:
        """현재 스레드에 연결된 requests session을 반환한다."""
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = self._create_session()
            self._thread_local.session = session
            self._register_session(session)
        return session

    def _fetch_with_requests(self, url: str) -> FetchResult:
        """requests 기반 정적 수집을 수행한다."""
        try:
            resp = self._get_session().get(url, timeout=self.config.timeout_sec, allow_redirects=True)
            ok = 200 <= resp.status_code < 400
            error = None if ok else f"http_error: {resp.status_code}"
            return self._build_fetch_result(
                requested_url=url,
                final_url=resp.url,
                status_code=resp.status_code,
                html=resp.text or "",
                ok=ok,
                error=error,
                fetched_by="requests",
            )
        except Exception as e:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=0,
                ok=False,
                html="",
                text="",
                title="",
                meta_description="",
                links=[],
                error=str(e),
                fetched_by="requests",
            )

    def _fetch_with_playwright(self, url: str, lightweight: bool = False) -> FetchResult:
        """playwright 기반 동적 렌더링 수집을 수행한다."""
        if not self.playwright_enabled:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=0,
                ok=False,
                html="",
                text="",
                title="",
                meta_description="",
                links=[],
                error=self.playwright_disabled_reason or "playwright_unavailable",
                fetched_by="playwright",
            )
        resource = self._get_or_create_playwright_resource()
        if resource is None:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=0,
                ok=False,
                html="",
                text="",
                title="",
                meta_description="",
                links=[],
                error=self.playwright_disabled_reason or "playwright_unavailable",
                fetched_by="playwright",
            )

        page = None
        try:
            context = resource["context"]
            page = context.new_page()
            page.set_default_timeout(self.config.playwright_timeout_ms)
            response = page.goto(
                url,
                wait_until=self.config.playwright_wait_until,
                timeout=self.config.playwright_timeout_ms,
            )
            extra_wait_ms = self.config.playwright_extra_wait_ms
            challenge_wait_ms = self.config.playwright_challenge_wait_ms
            challenge_retries = self.config.playwright_challenge_retries
            if lightweight:
                extra_wait_ms = min(extra_wait_ms, 300)
                challenge_wait_ms = min(challenge_wait_ms, 2500)
                challenge_retries = 0

            if extra_wait_ms > 0:
                page.wait_for_timeout(extra_wait_ms)

            self._dismiss_common_banners(page)
            if not lightweight:
                self._safe_auto_scroll(page)
                page.wait_for_timeout(300)
            else:
                page.wait_for_timeout(120)

            challenge_ok = self._wait_until_non_challenge(page, challenge_wait_ms)
            retries_left = challenge_retries
            while not challenge_ok and retries_left > 0:
                reload_response = page.reload(
                    wait_until=self.config.playwright_wait_until,
                    timeout=self.config.playwright_timeout_ms,
                )
                if reload_response:
                    response = reload_response
                page.wait_for_timeout(600)
                challenge_ok = self._wait_until_non_challenge(page, challenge_wait_ms)
                retries_left -= 1

            status_code = response.status if response else 200
            result = self._build_fetch_result(
                requested_url=url,
                final_url=page.url,
                status_code=status_code,
                html=page.content(),
                ok=200 <= status_code < 400,
                error=None,
                fetched_by="playwright",
            )
            if self._is_challenge_result(result):
                result.ok = False
                result.error = "anti_bot_challenge_detected"
                return result
            if result.status_code >= 400 and len(result.text or "") >= self.config.min_text_len_for_static_success:
                result.ok = True
            return result
        except PlaywrightTimeoutError as e:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=0,
                ok=False,
                html="",
                text="",
                title="",
                meta_description="",
                links=[],
                error=f"playwright_timeout: {e}",
                fetched_by="playwright",
            )
        except Exception as e:
            error_text = f"playwright_error: {e}"
            if self._is_playwright_unavailable_error(error_text):
                self.playwright_enabled = False
                self.playwright_disabled_reason = (
                    "playwright_unavailable: 브라우저 실행 파일이 없습니다. "
                    "playwright install 로 브라우저를 설치하세요."
                )
                self._close_playwright_resources()
            else:
                self._close_playwright_resource(resource)
            return FetchResult(
                url=url,
                final_url=url,
                status_code=0,
                ok=False,
                html="",
                text="",
                title="",
                meta_description="",
                links=[],
                error=error_text,
                fetched_by="playwright",
            )
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def _register_playwright_resource(self, resource: dict[str, Any]) -> None:
        """생성된 Playwright 리소스를 종료 정리를 위해 등록한다."""
        with self._playwright_resources_lock:
            if resource not in self._playwright_resources:
                self._playwright_resources.append(resource)

    def _get_or_create_playwright_resource(self) -> dict[str, Any] | None:
        """현재 스레드의 Playwright 리소스를 반환하고 없으면 생성한다."""
        if not self.playwright_enabled:
            return None
        resource = getattr(self._thread_local, "playwright_resource", None)
        if resource is not None:
            context = resource.get("context")
            browser = resource.get("browser")
            pw = resource.get("pw")
            if context is not None and browser is not None and pw is not None:
                return resource

        try:
            manager = sync_playwright()
            pw = manager.start()
            browser_type = getattr(pw, self.config.playwright_browser)
            browser = browser_type.launch(
                headless=self.config.playwright_headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=self.config.playwright_user_agent,
                locale="en-US",
                viewport={"width": 1366, "height": 900},
            )
            context.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9,ko;q=0.8"})
            context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                """
            )
            resource = {
                "manager": manager,
                "pw": pw,
                "browser": browser,
                "context": context,
            }
            self._thread_local.playwright_resource = resource
            self._register_playwright_resource(resource)
            return resource
        except Exception as e:
            error_text = f"playwright_error: {e}"
            if self._is_playwright_unavailable_error(error_text):
                self.playwright_enabled = False
                self.playwright_disabled_reason = (
                    "playwright_unavailable: 브라우저 실행 파일이 없습니다. "
                    "playwright install 로 브라우저를 설치하세요."
                )
            self._close_playwright_resources()
            return None

    def _shutdown_playwright_resource(self, resource: dict[str, Any]) -> None:
        """단일 Playwright 리소스의 context/browser/manager를 순서대로 닫는다."""
        try:
            context = resource.get("context")
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            browser = resource.get("browser")
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            manager = resource.get("manager")
            if manager is not None:
                manager.stop()
        except Exception:
            pass
        resource["context"] = None
        resource["browser"] = None
        resource["pw"] = None
        resource["manager"] = None

    def _close_playwright_resource(self, resource: dict[str, Any]) -> None:
        """단일 Playwright 리소스를 등록 목록/스레드 로컬에서 제거하고 닫는다."""
        with self._playwright_resources_lock:
            self._playwright_resources = [r for r in self._playwright_resources if r is not resource]
        current = getattr(self._thread_local, "playwright_resource", None)
        if current is resource:
            self._thread_local.playwright_resource = None
        self._shutdown_playwright_resource(resource)

    def _close_playwright_resources(self) -> None:
        """보유 중인 모든 Playwright 리소스를 닫는다."""
        with self._playwright_resources_lock:
            resources = list(self._playwright_resources)
            self._playwright_resources.clear()
        for resource in resources:
            self._shutdown_playwright_resource(resource)
        self._thread_local.playwright_resource = None

    def close(self) -> None:
        """외부에서 fetcher 종료 시 리소스를 정리한다."""
        self._close_playwright_resources()
        with self._sessions_lock:
            sessions = list(self._sessions)
            self._sessions.clear()
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _is_playwright_unavailable_error(self, error: str | None) -> bool:
        """playwright 실행 불가 유형의 에러 문자열인지 판정한다."""
        if not error:
            return False
        text = error.lower()
        unavailable_signals = (
            "playwright_unavailable",
            "looks like playwright was just installed or updated",
            "please run the following command to download new browsers",
            "executable doesn't exist",
            "browser executable",
            "playwright install",
        )
        return any(sig in text for sig in unavailable_signals)

    def is_challenge_text(self, text: str) -> bool:
        """Cloudflare/captcha 등 anti-bot 챌린지 문구를 감지한다."""
        blob = lower(text or "")
        if re.search(r"verification successful\.\s*waiting for .* to respond", blob):
            return True
        challenge_markers = (
            "just a moment",
            "verification successful. waiting for",
            "checking your browser",
            "please wait while we verify",
            "attention required",
            "cf-ray",
            "cloudflare",
            "captcha",
            "/cdn-cgi/challenge-platform/",
            "__cf_chl",
        )
        return any(marker in blob for marker in challenge_markers)

    def _is_challenge_result(self, result: FetchResult) -> bool:
        """수집 결과 본문이 챌린지 페이지인지 판정한다."""
        return self.is_challenge_text(" ".join([result.final_url, result.title, result.text[:2500]]))

    def _wait_until_non_challenge(self, page: Any, timeout_ms: int) -> bool:
        """챌린지 화면이 해소될 때까지 제한 시간 내 대기한다."""
        waited = 0
        interval = 500
        while waited <= timeout_ms:
            try:
                title = squash_ws(page.title() or "")
            except Exception:
                title = ""
            try:
                body = squash_ws(page.locator("body").inner_text(timeout=1200) or "")
            except Exception:
                body = ""
            if not self.is_challenge_text(" ".join([page.url, title, body[:2500]])):
                return True
            page.wait_for_timeout(interval)
            waited += interval
        return False

    def _dismiss_common_banners(self, page: Any) -> None:
        """쿠키 배너/모달 등 일반 팝업을 닫아 본문 수집 정확도를 높인다."""
        selectors = [
            "button:has-text('Accept')",
            "button:has-text('I Agree')",
            "button:has-text('Agree')",
            "button:has-text('OK')",
            "button:has-text('Got it')",
            "button:has-text('Allow all')",
            "button:has-text('동의')",
            "button:has-text('확인')",
            "button:has-text('허용')",
            "[aria-label='Close']",
            "button[aria-label='Close']",
            "[data-testid='close']",
        ]
        for sel in selectors:
            try:
                locator = page.locator(sel).first
                if locator.is_visible(timeout=500):
                    locator.click(timeout=800)
                    page.wait_for_timeout(200)
            except Exception:
                pass

    def _safe_auto_scroll(self, page: Any) -> None:
        """지연 로딩 컨텐츠를 노출하기 위해 안전하게 자동 스크롤한다."""
        try:
            page.evaluate(
                """
                async () => {
                    await new Promise((resolve) => {
                        let total = 0;
                        const distance = 700;
                        const timer = setInterval(() => {
                            const scrollHeight = Math.max(
                                document.body.scrollHeight,
                                document.documentElement.scrollHeight
                            );
                            window.scrollBy(0, distance);
                            total += distance;
                            if (total >= scrollHeight) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 150);
                    });
                }
                """
            )
        except Exception:
            pass

    def _build_fetch_result(
        self,
        requested_url: str,
        final_url: str,
        status_code: int,
        html: str,
        ok: bool,
        error: str | None,
        fetched_by: str,
    ) -> FetchResult:
        """HTML을 파싱해 제목/메타/본문/링크를 포함한 FetchResult를 생성한다."""
        soup = BeautifulSoup(html, "html.parser")
        title = squash_ws(soup.title.get_text(" ", strip=True)) if soup.title else ""
        meta_description = ""
        meta_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        if meta_tag and meta_tag.get("content"):
            meta_description = squash_ws(str(meta_tag["content"]))

        for bad in soup(["script", "style", "noscript", "svg"]):
            bad.extract()

        body_text = squash_ws(soup.get_text(" ", strip=True))
        if len(body_text) > self.config.max_body_text_chars:
            body_text = body_text[: self.config.max_body_text_chars]

        links: list[tuple[str, str]] = []
        max_links = max(1, self.config.max_links_per_page)
        seen = set()
        for a in soup.find_all("a", href=True, limit=max_links * 3):
            href = a.get("href", "").strip()
            text = squash_ws(a.get_text(" ", strip=True))
            abs_url = urljoin(final_url, href)
            if not abs_url.startswith(("http://", "https://")):
                continue
            key = (text, abs_url)
            if key in seen:
                continue
            seen.add(key)
            links.append((text, abs_url))
            if len(links) >= max_links:
                break
        return FetchResult(
            url=requested_url,
            final_url=final_url,
            status_code=status_code,
            ok=ok,
            html=html,
            text=body_text,
            title=title,
            meta_description=meta_description,
            links=links,
            error=error,
            fetched_by=fetched_by,
        )

    def _needs_playwright(self, req_result: FetchResult, lightweight: bool = False) -> bool:
        """requests 결과만으로 부족한 경우 playwright 재수집 여부를 판정한다."""
        if not req_result.ok:
            return True
        if self._is_challenge_result(req_result):
            return True
        html_lower = lower(req_result.html[:20000])
        text_len = len(req_result.text or "")
        link_count = len(req_result.links or [])
        js_app_signals = [
            "__next", "id=\"__next\"", "id=\"root\"", "id=\"app\"",
            "data-reactroot", "window.__nuxt__", "webpack", "chunk.js", "hydration",
        ]

        has_js_app_signal = any(sig in html_lower for sig in js_app_signals)
        thin_text = text_len < self.config.min_text_len_for_static_success
        thin_links = link_count < self.config.min_links_for_static_success

        if lightweight:
            if has_js_app_signal and thin_text:
                return True
            return False

        if thin_text and thin_links:
            return True
        if has_js_app_signal and (thin_text or thin_links):
            return True
        return False

    def _choose_better_result(self, req_result: FetchResult, pw_result: FetchResult) -> FetchResult:
        """requests 결과와 playwright 결과 중 신뢰도 높은 쪽을 선택한다."""
        if not pw_result.ok and req_result.ok:
            return req_result
        if pw_result.ok and not req_result.ok:
            return pw_result
        req_is_challenge = self._is_challenge_result(req_result)
        pw_is_challenge = self._is_challenge_result(pw_result)
        if req_is_challenge and not pw_is_challenge:
            return pw_result
        if pw_is_challenge and not req_is_challenge:
            return req_result
        return pw_result if self._result_richness_score(pw_result) > self._result_richness_score(req_result) else req_result

    def _result_richness_score(self, result: FetchResult) -> int:
        """본문 길이/링크 수/메타 유무 기반의 결과 풍부도 점수를 계산한다."""
        score = 0
        score += min(len(result.text or ""), 5000) // 100
        score += min(len(result.links or []), 50) * 5
        score += 20 if result.title else 0
        score += 20 if result.meta_description else 0
        score += 10 if result.ok else 0
        return score
