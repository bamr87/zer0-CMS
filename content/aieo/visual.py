"""The visual audit: a screenshot of a page in a headless browser, for the evaluator to see beside the text.

Off unless `AIEO_VISUAL_AUDIT` is set, and Playwright is an optional install (`pip install "playwright>=1.48" &&
playwright install chromium`); without either an audit says so and scores the text. It runs only in a worker, inside
an audit's run (on the research queue), at a 1280×800 viewport, as AIEO captured it.

The page is someone else's, so the browser gets no way out but the research library's guarded fetcher:

* every HTTP request of the browser context — the page, its styles, scripts and images, and any popup the page opens
  (routes on the context cover popups; a popup is also closed) — is answered by `through_guard`, which fetches it
  with `research.fetch.get` (the SSRF guard, redirect checks, size and time limits) or aborts it; anything but a GET
  is aborted;
* service workers are blocked (a request a service worker answers would never reach the route), downloads refused,
  and every WebSocket is routed to a handler that never connects it to its server (`route_web_socket`);
* behind that, the browser has no network of its own: its proxy is a closed local port (loopback included), every
  host name resolves to nothing, and WebRTC may not send UDP outside the proxy — so a request that escaped the routes
  still reaches nothing;
* Chromium runs with its sandbox, and with an environment of a few variables rather than the worker's, which holds
  the platform's secrets. A worker that cannot run the sandbox (Chromium as root in a container) cannot capture, and
  the audit says so.
"""

import base64
import os
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

from research import fetch

VIEWPORT = {"width": 1280, "height": 800}
DROPPED = {"content-encoding", "content-length", "transfer-encoding", "connection"}
# A closed port: the browser's own way to the network, which nothing should take.
DEAD_PROXY = {"server": "http://127.0.0.1:9", "bypass": "<-loopback>"}
ISOLATED = [
    "--host-resolver-rules=MAP * ~NOTFOUND",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
]
KEPT_ENV = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "FONTCONFIG_FILE", "FONTCONFIG_PATH")


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
        from playwright.sync_api import BrowserContext, Error, sync_playwright
    except ImportError as e:
        raise Unavailable('Playwright is not installed: pip install "playwright>=1.48", playwright install chromium') from e
    if not hasattr(BrowserContext, "route_web_socket"):
        raise Unavailable("the visual audit needs Playwright 1.48 or later, which can hold a page's WebSockets")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                chromium_sandbox=True,
                proxy=DEAD_PROXY,
                args=ISOLATED,
                env={name: os.environ[name] for name in KEPT_ENV if name in os.environ},
            )
            try:
                context = browser.new_context(
                    viewport=VIEWPORT,
                    user_agent=settings.RESEARCH_USER_AGENT,
                    service_workers="block",
                    accept_downloads=False,
                )
                context.route("**/*", through_guard)
                # A WebSocket whose handler never calls connect_to_server stays a mock with no server behind it. (The
                # handler runs inside Playwright's own loop, so it must not call the sync API, socket.close() included.)
                context.route_web_socket("**/*", lambda socket: None)
                page = context.new_page()
                page.on("popup", lambda popup: popup.close())
                page.goto(url, wait_until="load", timeout=int(settings.RESEARCH_FETCH_TIMEOUT * 1000))
                return page.screenshot(full_page=False, type="png")
            finally:
                browser.close()
    except Error as e:
        raise Unavailable(f"the page could not be captured: {e}") from e


def image_part(png: bytes) -> dict:
    """The screenshot as a message part a provider that can see images reads (ai/providers)."""
    return {"type": "image", "media_type": "image/png", "data": base64.b64encode(png).decode()}
