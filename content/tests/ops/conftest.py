"""Fixtures for the ops tests: the failing views' URLconf, and a client that
hands back a 500 instead of re-raising it."""

import pytest
from django.test import Client


@pytest.fixture
def api_urls(settings):
    settings.ROOT_URLCONF = "tests.ops.urls"


@pytest.fixture
def raw_client():
    return Client(raise_request_exception=False)
