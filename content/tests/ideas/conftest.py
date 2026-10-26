"""Fixtures for the ideas tests: the AI layer's people, scripted provider,
worker and API client (tests/ai/conftest.py), and a brainstorm reply as the
Brainstormer's schema has it. Nothing reaches a network or a model."""

import json

import pytest

from tests.ai.conftest import alice, api, bob, fake, staff, worker  # noqa: F401 — shared fixtures

IDEAS = {
    "ideas": [
        {"title": "Backups in five minutes a night", "notes": "For people who never set one up.", "kind": "angle"},
        {"title": "Your site will break. Will you notice?", "notes": "A wake-up headline.", "kind": "headline"},
        {"title": "Backups, a plan", "notes": "- Why\n- How\n- Testing restores", "kind": "outline"},
    ]
}


@pytest.fixture
def brainstormed():
    """The scripted reply to one brainstorm."""
    return {"text": json.dumps(IDEAS), "tokens_in": 200, "tokens_out": 120}
