"""Fixtures for the outbox desk's tests: a belt and an arena directory of each test's own, people who hold the
desk's permissions and one who holds none, the API client and worker from the AI layer's tests, and a claim set
whose sources moved after the draft was written. The harness runs its offline policy agents; nothing reaches a
network or a model."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from wagtail.models import GroupPagePermission, Page

from tests.ai.conftest import api, worker  # noqa: F401 — shared fixtures

DESK = ("view_belt", "send_handoff", "deliver_belt")
RUNS = ("view_trial", "add_trial", "view_claimcheck", "add_claimcheck", "change_claimcheck")

CLAIMS = [
    {
        "id": "hydra-status",
        "question": "What status does hydra report?",
        "answer": "amber",
        "sources": ["probe"],
        "confidence": 0.8,
    },
    {
        "id": "hydra-region",
        "question": "Which region serves hydra?",
        "answer": "eu-west",
        "sources": ["runbook"],
        "confidence": 0.9,
    },
]
TIMELINE = [
    {"tick": 0, "source": "probe", "says": "amber", "fact": "probe returns amber"},
    {"tick": 0, "source": "runbook", "says": "eu-west", "fact": "runbook names eu-west"},
    {
        "tick": 4,
        "source": "probe",
        "says": "green",
        "fact": "hydra flipped to green after failover",
        "note": "after the draft",
    },
]
CARD = {
    "id": "T-stale-fact",
    "family": "stale_fact",
    "question": "What is the live status code for service hydra?",
    "expected_answer": "green",
    "closes_at_tick": 8,
    "deadline_ping_tick": 7,
    "lag_b": 2,
    "max_env_lag": 0,
    "inversion_confidence": 0.75,
    "a_sticky": False,
    "env_schedule": [
        {
            "tick": 0,
            "env_seq": 1,
            "fact": "hydra status probe returns amber",
            "answer_hint": "amber",
            "note": "initial",
        },
        {
            "tick": 4,
            "env_seq": 2,
            "fact": "hydra flipped to green after failover",
            "answer_hint": "green",
            "note": "moved",
        },
    ],
}


@pytest.fixture(autouse=True)
def desk_dirs(settings, tmp_path):
    """Each test's own belt and arenas."""
    settings.OUTBOX_OUT_DIR = tmp_path / "outbox"
    settings.OUTBOX_BELT_ROOT = tmp_path / "outbox" / "belt"
    return settings.OUTBOX_OUT_DIR


def person(username, *codenames, pages=False):
    user = get_user_model().objects.create_user(username, password="pw")
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="outboxdesk", codename__in=codenames))
    if pages:
        group, _ = Group.objects.get_or_create(name="Desk test editors")
        GroupPagePermission.objects.get_or_create(
            group=group,
            page=Page.get_first_root_node(),
            permission=Permission.objects.get(content_type__app_label="wagtailcore", codename="change_page"),
        )
        user.groups.add(group)
    return user


@pytest.fixture
def ed(db):
    """A person who holds every permission of the desk, and edits every page."""
    return person("ed", *DESK, *RUNS, pages=True)


@pytest.fixture
def reader(db):
    """A person who may read the belt, trials and checks, and do nothing else."""
    return person("reader", "view_belt", "view_trial", "view_claimcheck")


@pytest.fixture
def nobody(db):
    """A person who holds none of the desk's permissions."""
    return person("nobody")
