"""Studio API behaviour, exercised through the handler layer and over HTTP."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from bookshelf import ai, server
from bookshelf.library import Library
from test_ai import FakeClient


@pytest.fixture
def studio(repo: Path) -> server.Studio:
    assistant = ai.Studio()
    assistant._client = FakeClient(chunks=("drafted ", "prose"))
    return server.Studio(repo, assistant)


# -- read -----------------------------------------------------------------
def test_library_payload_has_books_issues_and_tasks(studio: server.Studio):
    payload = studio.get_library()
    assert [book["slug"] for book in payload["books"]] == ["sample"]
    assert payload["issues"] == []
    assert {task["key"] for task in payload["tasks"]} == set(ai.TASKS)


def test_get_chapter_returns_meta_and_body(studio: server.Studio):
    chapter = studio.get_chapter("sample", 1)
    assert chapter["meta"]["title"] == "Chapter 1"
    assert "empty chairs" in chapter["body"]
    assert chapter["path"].startswith("library/sample/chapters/")


def test_unknown_book_is_a_404(studio: server.Studio):
    with pytest.raises(server.ApiError) as caught:
        studio.get_chapter("nope", 1)
    assert caught.value.status == 404


def test_a_slug_cannot_escape_the_library(studio: server.Studio):
    for slug in ("../../etc", "..", "a/b", "sample/../..", ""):
        with pytest.raises(server.ApiError, match="invalid book slug"):
            studio.get_chapter(slug, 1)


def test_a_missing_chapter_is_a_404(studio: server.Studio):
    with pytest.raises(server.ApiError) as caught:
        studio.get_chapter("sample", 99)
    assert caught.value.status == 404


# -- write ----------------------------------------------------------------
def test_saving_writes_body_and_meta_to_disk(studio: server.Studio, repo: Path):
    meta = dict(studio.get_chapter("sample", 1)["meta"])
    meta["status"] = "revised"
    studio.save_chapter({"slug": "sample", "number": 1, "meta": meta, "body": "\n## Chapter Body\n\nNew words.\n"})

    reloaded = Library.load(repo).get("sample").chapter(1)
    assert reloaded.status == "revised"
    assert "New words." in reloaded.body
    assert reloaded.path.read_text(encoding="utf-8").startswith("---\n")


def test_saving_keeps_existing_meta_when_none_is_sent(studio: server.Studio, repo: Path):
    studio.save_chapter({"slug": "sample", "number": 1, "body": "\n## Chapter Body\n\nJust the body.\n"})
    reloaded = Library.load(repo).get("sample").chapter(1)
    assert reloaded.title == "Chapter 1"
    assert "Just the body." in reloaded.body


def test_saving_rejects_a_non_string_body(studio: server.Studio):
    with pytest.raises(server.ApiError, match="body must be a string"):
        studio.save_chapter({"slug": "sample", "number": 1, "body": {"nope": True}})


def test_creating_a_book_and_a_chapter(studio: server.Studio, repo: Path):
    book = studio.create_book({"title": "Second Book", "logline": "A pitch."})
    assert book["slug"] == "second-book"
    studio.create_chapter({"slug": "second-book", "title": "Opening"})

    reloaded = Library.load(repo).get("second-book")
    assert [chapter.title for chapter in reloaded.chapters] == ["Opening"]


def test_creating_a_duplicate_book_is_a_conflict(studio: server.Studio):
    with pytest.raises(server.ApiError) as caught:
        studio.create_book({"title": "Sample", "slug": "sample"})
    assert caught.value.status == 409


def test_creating_a_book_without_a_title_is_rejected(studio: server.Studio):
    with pytest.raises(server.ApiError, match="title is required"):
        studio.create_book({"logline": "no title"})


# -- assistant ------------------------------------------------------------
def test_streaming_a_task(studio: server.Studio):
    chunks = list(studio.stream_ai({"slug": "sample", "number": 1, "task": "draft"}))
    assert "".join(chunks) == "drafted prose"


def test_unknown_task_is_rejected(studio: server.Studio):
    with pytest.raises(server.ApiError, match="unknown task"):
        studio.stream_ai({"slug": "sample", "number": 1, "task": "hallucinate"})


def test_revise_requires_a_selection(studio: server.Studio):
    with pytest.raises(server.ApiError, match="needs a selection"):
        studio.stream_ai({"slug": "sample", "number": 1, "task": "revise"})


def test_structured_and_streaming_endpoints_do_not_cross_over(studio: server.Studio):
    with pytest.raises(server.ApiError, match="structured output"):
        studio.stream_ai({"slug": "sample", "number": 1, "task": "check"})
    with pytest.raises(server.ApiError, match="streams text"):
        studio.structured_ai({"slug": "sample", "number": 1, "task": "draft"})


def test_a_task_can_run_without_a_chapter(studio: server.Studio):
    assert "".join(studio.stream_ai({"slug": "sample", "task": "outline"})) == "drafted prose"


# -- over the wire --------------------------------------------------------
@pytest.fixture
def live(repo: Path):
    assistant = ai.Studio()
    assistant._client = FakeClient(chunks=("one ", "two"))
    httpd = server.serve(repo, host="127.0.0.1", port=0, assistant=assistant)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def fetch(url: str, method: str = "GET", payload: dict | None = None, headers: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read().decode()


def test_index_serves_the_editor(live: str):
    status, body = fetch(live + "/")
    assert status == 200
    assert "<title>Bookshelf Studio</title>" in body
    for external in ("http://", "https://", "cdn."):
        assert external not in body, f"the editor must not reference {external}"


def test_library_endpoint_over_http(live: str):
    status, body = fetch(live + "/api/library")
    assert status == 200
    assert json.loads(body)["books"][0]["slug"] == "sample"


def test_unknown_route_is_a_404(live: str):
    with pytest.raises(urllib.error.HTTPError) as caught:
        fetch(live + "/api/nope")
    assert caught.value.code == 404


def test_cross_origin_writes_are_refused(live: str):
    """A page on another origin must not be able to write files on localhost."""
    with pytest.raises(urllib.error.HTTPError) as caught:
        fetch(
            live + "/api/book",
            method="POST",
            payload={"title": "Injected"},
            headers={"Origin": "https://evil.example"},
        )
    assert caught.value.code == 403


def test_same_origin_writes_are_allowed(live: str):
    status, _ = fetch(
        live + "/api/book",
        method="POST",
        payload={"title": "From The Editor"},
        headers={"Origin": live},
    )
    assert status == 200


def test_ai_endpoint_streams_server_sent_events(live: str):
    request = urllib.request.Request(
        live + "/api/ai",
        data=json.dumps({"slug": "sample", "number": 1, "task": "draft"}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers["Content-Type"].startswith("text/event-stream")
        body = response.read().decode()
    assert 'event: text\ndata: "one "' in body
    assert "event: done" in body


def test_malformed_json_is_a_400(live: str):
    request = urllib.request.Request(
        live + "/api/chapter", data=b"{not json", method="PUT", headers={"Content-Type": "application/json"}
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    assert caught.value.code == 400
