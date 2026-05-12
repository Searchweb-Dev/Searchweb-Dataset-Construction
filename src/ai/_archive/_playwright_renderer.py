"""Playwright 기반 웹사이트 렌더링 (보존용).

url_context 방식으로 전환 후 비활성화된 코드입니다.
SPA/JS 렌더링이 필요하거나 스크린샷 기반 시각 분석이 필요한 경우
이 모듈을 다시 활성화하세요.

활성화 방법:
  1. requirements.txt 에서 playwright, pyee 주석 해제
  2. Dockerfile.worker 에 playwright install chromium 복원
  3. detector.py 에서 이 모듈의 render_website_sync 를 임포트하여 사용
"""

import asyncio
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def render_website(url: str, timeout: int = 30000) -> dict[str, str]:
    """Playwright를 사용하여 웹사이트 렌더링 및 컨텐츠 추출."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1920, "height": 1080})

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)

                text_content = await page.evaluate(
                    """() => {
                        const text = document.body.innerText;
                        return text.substring(0, 8000);
                    }"""
                )

                screenshot = await page.screenshot()
                screenshot_base64 = base64.b64encode(screenshot).decode("utf-8")

                title = await page.title()
                description = await page.evaluate(
                    """() => {
                        const meta = document.querySelector('meta[name="description"]');
                        return meta ? meta.getAttribute('content') : '';
                    }"""
                )

                return {
                    "url": url,
                    "title": title,
                    "description": description or "",
                    "text_content": text_content,
                    "screenshot_base64": screenshot_base64,
                }

            finally:
                await browser.close()

    except Exception as e:
        logger.error(f"웹사이트 렌더링 실패 ({url}): {e}")
        return {
            "url": url,
            "title": "",
            "description": "",
            "text_content": "",
            "screenshot_base64": "",
            "error": str(e),
        }


def render_website_sync(url: str, timeout: int = 30000) -> dict[str, str]:
    """동기 버전의 웹사이트 렌더링."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(render_website(url, timeout))
    finally:
        loop.close()
