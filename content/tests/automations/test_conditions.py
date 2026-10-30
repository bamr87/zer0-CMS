"""Conditions (PLAN G16): a JMESPath expression over the payload — the maintained library, not an evaluator of our
own — decides whether the actions run. True runs them, false records the run as skipped, an expression that does not
compile is refused when it is saved, and one that cannot be evaluated against a payload fails the run with the
reason. JMESPath's own idea of truth holds: 0 is true, an empty list is not."""

import pytest
from django.core.exceptions import ValidationError

from automations import services, spec
from automations.models import AutomationRun
from ideas.models import Idea

HOOK = {"kind": "hook", "hook": "monitor.finding"}
IDEA = {"kind": "idea", "title": "{{ data.url }}"}


def test_a_condition_is_judged_by_jmespath():
    finding = {"data": {"severity": "high", "count": 0, "tags": [], "pages": ["/a", "/b"]}}
    assert spec.matches("", finding) is True
    assert spec.matches("data.severity == 'high'", finding) is True
    assert spec.matches("data.severity == 'low'", finding) is False
    assert spec.matches("data.count", finding) is True  # 0 is true to JMESPath
    assert spec.matches("data.tags", finding) is False  # an empty list is not
    assert spec.matches("length(data.pages) > `1` && contains(data.pages, '/b')", finding) is True
    assert spec.matches("data.missing", finding) is False
    with pytest.raises(spec.ConditionError):
        spec.matches("length(data.count)", finding)  # a number has no length
    assert spec.evaluate("data.pages[0]", finding) == {"matched": True, "value": "/a", "error": ""}
    assert spec.evaluate("data.[", finding)["matched"] is None


@pytest.mark.django_db
def test_true_runs_the_actions_false_skips_them_and_an_error_fails_the_run(alice, make, worker):
    automation = make(alice, HOOK, [IDEA], condition="data.severity == 'high'")
    [high] = worker(services.fire_hook, "monitor.finding", {"severity": "high", "url": "https://example.com/a"})
    [low] = worker(services.fire_hook, "monitor.finding", {"severity": "low", "url": "https://example.com/b"})
    high.refresh_from_db()
    low.refresh_from_db()
    assert (high.status, high.matched) == (AutomationRun.SUCCEEDED, True)
    assert (low.status, low.matched, low.outcomes) == (AutomationRun.SKIPPED, False, [])
    assert list(Idea.objects.values_list("title", flat=True)) == ["https://example.com/a"]

    automation.condition = "length(data.severity) > `2`"
    automation.save(update_fields=["condition"])
    [odd] = worker(services.fire_hook, "monitor.finding", {"severity": 3})
    odd.refresh_from_db()
    assert odd.status == AutomationRun.FAILED and odd.matched is None
    assert odd.error.startswith("the condition could not be evaluated") and odd.outcomes == []


@pytest.mark.django_db
def test_a_condition_that_does_not_compile_is_refused_when_saved(alice, make, api):
    with pytest.raises(ValidationError) as refused:
        make(alice, HOOK, [IDEA], condition="data.[")
    assert "condition" in refused.value.message_dict
    body = {"name": "Broken", "trigger": HOOK, "actions": [IDEA], "condition": "data.severity =="}
    answer = api(alice).post("/api/v2/automations/", body, format="json")
    assert answer.status_code == 422
    assert [d["field"] for d in answer.json()["error"]["details"]] == ["condition"]


@pytest.mark.django_db
def test_a_condition_is_tried_against_a_sample_payload(alice, api):
    url = "/api/v2/automations/condition/"
    sample = {"data": {"severity": "high"}}
    tried = api(alice).post(url, {"condition": "data.severity == 'high'", "payload": sample}, format="json").json()
    assert tried == {"matched": True, "value": True, "error": ""}
    found = api(alice).post(url, {"condition": "data.severity", "payload": sample}, format="json").json()
    assert found == {"matched": True, "value": "high", "error": ""}
    broken = api(alice).post(url, {"condition": "data.[", "payload": sample}, format="json").json()
    assert broken["matched"] is None and "Invalid jmespath expression" in broken["error"]
