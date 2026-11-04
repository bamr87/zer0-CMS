"""Fixtures for the site registry's tests: the AI layer's people, scripted provider and worker (tests/ai/conftest.py),
which the directives tests (test_directives.py) use — a pulled directive is a brief, owned by a person who edits the
site. The registry's own tests keep their `admin` and `api` fixtures in test_sites.py."""

from tests.ai.conftest import alice, bob, fake, worker  # noqa: F401 — shared fixtures
