"""The studio: a local web app for writing and managing the library.

Standard-library HTTP server, no framework and no build step. It binds to the
loopback interface only -- this is a single-user tool that edits files on the
machine it runs on, not something to expose.

The API is small and file-backed: every read goes to disk and every write lands
in the markdown, so the editor and a text editor can be used interchangeably.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import ai, build, editor, frontmatter, scaffold
from .library import Library, LibraryError
from .models import Book, Chapter
from .validate import validate_all, validate_book

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ApiError(Exception):
    """A request that should become a 4xx with a readable message."""

    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


class Studio:
    """Request handling, independent of the HTTP plumbing.

    Kept separate from the handler so every endpoint is callable from a test
    without opening a socket.
    """

    def __init__(self, root: Path, assistant: ai.Studio | None = None):
        self.root = root
        self.assistant = assistant or ai.Studio()
        self._lock = threading.Lock()

    # -- helpers ----------------------------------------------------------
    def library(self) -> Library:
        return Library.load(self.root)

    def _book(self, slug: str) -> Book:
        if not slug or not SLUG.match(slug):
            raise ApiError(f"invalid book slug {slug!r}")
        try:
            return self.library().get(slug)
        except LibraryError as exc:
            raise ApiError(str(exc), HTTPStatus.NOT_FOUND) from exc

    @staticmethod
    def _chapter(book: Book, number: Any) -> Chapter:
        try:
            index = int(number)
        except (TypeError, ValueError) as exc:
            raise ApiError(f"invalid chapter number {number!r}") from exc
        chapter = book.chapter(index)
        if chapter is None:
            raise ApiError(f"{book.slug} has no chapter {index}", HTTPStatus.NOT_FOUND)
        return chapter

    # -- read -------------------------------------------------------------
    def get_library(self) -> dict[str, Any]:
        library = self.library()
        issues = validate_all(library.books)
        return {
            "books": [build.book_to_dict(book, library.root) for book in library.books],
            "issues": [self._issue(issue, library.root) for issue in issues],
            "tasks": [
                {"key": task.key, "label": task.label, "description": task.description}
                for task in ai.TASKS.values()
            ],
        }

    def get_chapter(self, slug: str, number: Any) -> dict[str, Any]:
        book = self._book(slug)
        chapter = self._chapter(book, number)
        return {
            "slug": book.slug,
            "number": chapter.number,
            "meta": chapter.meta,
            "body": chapter.body,
            "word_count": chapter.word_count,
            "path": str(chapter.path.relative_to(self.root)),
        }

    def get_issues(self, slug: str) -> dict[str, Any]:
        book = self._book(slug)
        return {"issues": [self._issue(issue, self.root) for issue in validate_book(book)]}

    @staticmethod
    def _issue(issue, root: Path) -> dict[str, Any]:
        data = asdict(issue)
        try:
            data["path"] = str(issue.path.relative_to(root))
        except ValueError:
            data["path"] = str(issue.path)
        return data

    # -- write ------------------------------------------------------------
    def save_chapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        book = self._book(payload.get("slug", ""))
        chapter = self._chapter(book, payload.get("number"))
        body = payload.get("body")
        if not isinstance(body, str):
            raise ApiError("body must be a string")
        meta = payload.get("meta")
        if meta is not None and not isinstance(meta, dict):
            raise ApiError("meta must be an object")

        with self._lock:
            chapter.path.write_text(
                frontmatter.render(meta if meta is not None else chapter.meta, body),
                encoding="utf-8",
            )
        return self.get_chapter(book.slug, chapter.number)

    def create_book(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ApiError("a title is required")
        slug = str(payload.get("slug") or "").strip() or scaffold.slugify(title)
        library = self.library()
        try:
            with self._lock:
                scaffold.new_book(
                    library.library_dir,
                    slug=slug,
                    title=title,
                    template_dir=library.template_dir,
                    logline=str(payload.get("logline") or ""),
                    genre=str(payload.get("genre") or ""),
                )
        except scaffold.ScaffoldError as exc:
            raise ApiError(str(exc), HTTPStatus.CONFLICT) from exc
        return build.book_to_dict(self.library().get(slug), self.root)

    def create_chapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        book = self._book(payload.get("slug", ""))
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ApiError("a title is required")
        try:
            with self._lock:
                scaffold.new_chapter(book, title=title, number=payload.get("number"))
        except scaffold.ScaffoldError as exc:
            raise ApiError(str(exc), HTTPStatus.CONFLICT) from exc
        refreshed = self.library().get(book.slug)
        return build.book_to_dict(refreshed, self.root)

    # -- assistant --------------------------------------------------------
    def _ai_context(self, payload: dict[str, Any]) -> tuple[ai.BookContext, ai.Task, str]:
        book = self._book(payload.get("slug", ""))
        key = str(payload.get("task") or "")
        task = ai.TASKS.get(key)
        if task is None:
            raise ApiError(f"unknown task {key!r}; expected one of {', '.join(ai.TASKS)}")

        chapter: Chapter | None = None
        if payload.get("number") not in (None, ""):
            chapter = self._chapter(book, payload["number"])

        extra = str(payload.get("instruction") or "")
        selection = str(payload.get("selection") or "")
        if selection:
            extra = f"SELECTION:\n\n{selection}\n\n{extra}".strip()
        if task.key == "revise" and not selection:
            raise ApiError("revise needs a selection")
        return ai.context_for(book, chapter), task, extra

    def stream_ai(self, payload: dict[str, Any]):
        context, task, extra = self._ai_context(payload)
        if task.schema is not None:
            raise ApiError(f"task {task.key!r} returns structured output; use /api/ai/structured")
        return self.assistant.stream(context, task, extra)

    def structured_ai(self, payload: dict[str, Any]) -> dict[str, Any]:
        context, task, extra = self._ai_context(payload)
        if task.schema is None:
            raise ApiError(f"task {task.key!r} streams text; use /api/ai")
        return self.assistant.run_structured(context, task, extra)


# -- HTTP -----------------------------------------------------------------
def make_handler(studio: Studio) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "bookshelf-studio"
        protocol_version = "HTTP/1.1"

        # -- plumbing -----------------------------------------------------
        def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover - noise
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > 8 * 1024 * 1024:
                raise ApiError("request body too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError(f"invalid JSON body: {exc}") from exc
            if not isinstance(payload, dict):
                raise ApiError("request body must be a JSON object")
            return payload

        def _guard(self) -> None:
            """Reject cross-origin requests.

            A page on another site can POST to localhost without reading the
            response; these endpoints write files, so the write must not happen
            at all. Same-origin requests from the editor send no Origin header
            on GET and the server's own origin on fetch.
            """
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
                raise ApiError("cross-origin requests are not allowed", HTTPStatus.FORBIDDEN)

        def _dispatch(self, routes: dict[str, Callable[[], None]]) -> None:
            path = urlparse(self.path).path.rstrip("/") or "/"
            handler = routes.get(path)
            if handler is None:
                self._json({"error": f"no route for {path}"}, HTTPStatus.NOT_FOUND)
                return
            try:
                self._guard()
                handler()
            except ApiError as exc:
                self._json({"error": str(exc)}, exc.status)
            except ai.AIError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            except LibraryError as exc:
                self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            except BrokenPipeError:  # pragma: no cover - client navigated away
                pass
            except Exception as exc:  # pragma: no cover - unexpected
                self._json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        @property
        def _query(self) -> dict[str, str]:
            raw = parse_qs(urlparse(self.path).query)
            return {key: values[0] for key, values in raw.items() if values}

        # -- routes -------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            self._dispatch(
                {
                    "/": lambda: self._send(
                        HTTPStatus.OK, editor.page().encode("utf-8"), "text/html; charset=utf-8"
                    ),
                    "/favicon.ico": lambda: self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon"),
                    "/api/library": lambda: self._json(studio.get_library()),
                    "/api/chapter": lambda: self._json(
                        studio.get_chapter(self._query.get("slug", ""), self._query.get("number"))
                    ),
                    "/api/issues": lambda: self._json(studio.get_issues(self._query.get("slug", ""))),
                }
            )

        def do_PUT(self) -> None:  # noqa: N802 - http.server API
            self._dispatch({"/api/chapter": lambda: self._json(studio.save_chapter(self._read_json()))})

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            self._dispatch(
                {
                    "/api/book": lambda: self._json(studio.create_book(self._read_json())),
                    "/api/chapter": lambda: self._json(studio.create_chapter(self._read_json())),
                    "/api/ai": self._stream_ai,
                    "/api/ai/structured": lambda: self._json(studio.structured_ai(self._read_json())),
                }
            )

        def _stream_ai(self) -> None:
            """Server-sent events, so prose appears while the model is writing."""
            payload = self._read_json()
            chunks = studio.stream_ai(payload)  # may raise before any output

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            def event(name: str, data: Any) -> None:
                self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()

            try:
                for chunk in chunks:
                    event("text", chunk)
                event("done", {})
            except ai.AIError as exc:
                event("error", {"message": str(exc)})
            except BrokenPipeError:  # pragma: no cover - client navigated away
                pass
            except Exception as exc:  # pragma: no cover - unexpected
                event("error", {"message": f"{type(exc).__name__}: {exc}"})

    return Handler


def serve(root: Path, host: str = "127.0.0.1", port: int = 8000, assistant: ai.Studio | None = None):
    """Create the server. The caller owns ``serve_forever`` and shutdown."""
    handler = make_handler(Studio(root, assistant))
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
