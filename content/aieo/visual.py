"""The visual audit: a screenshot of a page in a headless browser, for the evaluator to see beside the text.

Off unless `AIEO_VISUAL_AUDIT` is set, and Playwright is an optional install (`pip install playwright && playwright
install chromium`); without either an audit says so and scores the text. The browser never reaches the network
itself: every request it makes is routed through `research.fetch.get` (`through_guard`), so the page, its styles
and its images pass the same SSRF guard, redirect checks and size and time limits as everything else the platform
fetches, and anything but a GET is aborted. It runs only in a worker, inside an audit's run. A 1280×800 viewport,
as AIEO captured it.
"""

import base64
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

from research import fetch

VIEWPORT = {"width": 1280, "height": 800}
DROPPED = {"content-encoding", "content-length", "transfer-encoding", "connection"}


class Unavailable(Exception):
    """The visual audit cannot run here; the message says why."""


def _get(url: str):
    # fetch.get runs its own event loop; Playwright's sync API has one running in this thread, so fetch from another.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fetch.get, url).result()


def through_guard(route) -> None:
    """Answer one of the browser's requests through the guarded fetcher, or abort it."""
    request = route.request
    if request.method != "GET":
        route.abort()
        return
    try:
        got = _get(request.url)
    except fetch.FetchError:
        route.abort()
        return
    headers = {k: v for k, v in got.headers.items() if k.lower() not in DROPPED}
    route.fulfill(status=got.status, headers=headers, body=got.body)


def capture(url: str) -> bytes:
    """A PNG of the page's first screen."""
    if not settings.AIEO_VISUAL_AUDIT:
        raise Unavailable("the visual audit is off (AIEO_VISUAL_AUDIT)")
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as e:
        raise Unavailable("Playwright is not installed: pip install playwright && playwright install chromium") from e
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport=VIEWPORT, user_agent=settings.RESEARCH_USER_AGENT)
                page.route("**/*", through_guard)
                page.goto(url, wait_until="load", timeout=int(settings.RESEARCH_FETCH_TIMEOUT * 1000))
                return page.screenshot(full_page=False, type="png")
            finally:
                browser.close()
    except Error as e:
        raise Unavailable(f"the page could not be captured: {e}") from e


def image_part(png: bytes) -> dict:
    """The screenshot as a message part a provider that can see images reads (ai/providers)."""
    return {"type": "image", "media_type": "image/png", "data": base64.b64encode(png).decode()}
