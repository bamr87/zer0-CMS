"""Fixtures for the automations' tests: the AI layer's people, scripted provider, worker and API client
(tests/ai/conftest.py) and the newsroom's desk and its people (tests/newsroom/conftest.py); `make`, which saves an
automation through the model's own checks and enables it as its owner would; the event consumer registered for a test
and removed after it (`consuming`), so no other consumer's test sees it; a resolver that answers from a table, so no
test touches DNS; and recorded HTTP (respx) around every test — a webhook an automation notifies is answered at the
address the guard pins, and a request nothing answers fails. Nothing reaches a network or a model."""

import pytest
import respx

from automations import consumers, services
from automations.models import Automation
from research import fetch
from tests.ai.conftest import alice, api, bob, fake, staff, worker  # noqa: F401 — shared fixtures
from tests.newsroom.conftest import copyeditor, desk, ed, outsider, reporter, section, site  # noqa: F401 — shared

PUBLIC = "93.184.216.34"
DNS = {"hooks.example.com": [PUBLIC], "news.example.com": [PUBLIC], "intranet.example.com": ["10.0.0.5"]}
IDEA = {"kind": "idea", "title": "Follow up: {{ data.url_path }}"}


@pytest.fixture(autouse=True)
def table_dns(monkeypatch):
    """Names resolve from `DNS`; an address written out resolves to itself; any other name does not resolve."""

    def resolve(host, port):
        if host in DNS:
            return DNS[host]
        try:
            fetch.ipaddress.ip_address(host)
        except ValueError:
            raise OSError(f"{host} does not resolve in the tests") from None
        return [host]

    monkeypatch.setattr(fetch, "resolve", resolve)


@pytest.fixture(autouse=True)
def web():
    """Recorded HTTP for every test: a route answers, and a request no route answers fails (respx's default)."""
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def make(db):
    """An automation of `owner`'s, saved through the model's checks and — unless `enabled=False` — enabled."""

    def automation(owner, trigger, actions=(IDEA,), *, enabled=True, **fields):
        row = Automation(owner=owner, name=fields.pop("name", "An automation"), trigger=trigger, actions=list(actions))
        for key, value in fields.items():
            setattr(row, key, value)
        row.full_clean(exclude=["owner", "last_run"])
        row.save()
        return services.enable(row, user=owner) if enabled else row

    return automation


@pytest.fixture
def consuming():
    consumers.register()
    yield
    consumers.unregister()
