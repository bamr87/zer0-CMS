"""Fixtures for distribution's tests: the fixture site (`fixtures/site`, the
Ruby lane's test site, which the recording in `golden/ruby-lane.json` was made
over) copied into a temporary directory per test, recorded HTTP (respx — a
request no route answers fails the test), and the AI layer's people and API
client, and the newsroom's desk and people (for email). Nothing reaches LinkedIn, WordPress, GitHub or a mail server."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx

from tests.ai.conftest import alice, api, bob, staff, worker  # noqa: F401 — shared fixtures
from tests.newsroom.conftest import advance, copyeditor, desk, ed, reporter, section, site  # noqa: F401 — a newsroom

FIXTURE = Path(__file__).parent / "fixtures" / "site"
GOLDEN = json.loads((Path(__file__).parent / "golden" / "ruby-lane.json").read_text())
NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
AUTHOR = "urn:li:organization:64517157"
TOKEN = "tok-SECRET-123456"
MCP_POST = "pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md"
MCP_URL = "https://example.test/posts/2026/07/06/mcp-for-the-back-office/"
BLOCK = {
    "author": AUTHOR,
    "queue": "drafts/linkedin",
    "ledger": ".github/linkedin-log.json",
    "acceptStatuses": ["approved"],
    "sources": ["posts"],
}


@pytest.fixture
def make_checkout(tmp_path):
    """`make_checkout(linkedin={...} | zer0={...})` → the root of a fresh copy of the fixture site."""
    count = 0

    def make(linkedin=None, zer0=None):
        nonlocal count
        count += 1
        root = tmp_path / f"site{count}"
        shutil.copytree(FIXTURE, root)
        block = {**BLOCK, **(linkedin or {})}
        (root / "zer0.json").write_text(json.dumps(zer0 if zer0 is not None else {"distribution": {"linkedin": block}}))
        return root.resolve()

    return make


@pytest.fixture
def checkout(make_checkout):
    return make_checkout()


@pytest.fixture
def web():
    with respx.mock(assert_all_called=False) as router:
        yield router


def tree(root: Path) -> list:
    """Every file under `root` with its bytes: a preview or a rehearsal must leave it as it was."""
    return sorted((p.relative_to(root).as_posix(), p.read_bytes()) for p in root.rglob("*") if p.is_file())
