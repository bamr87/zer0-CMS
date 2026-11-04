"""The `directives` action (automations/spec.py, services.py `_directives`): a schedule pulls a managed site's open
editorial directives into briefs as the automation's owner, who must edit the site — checked when it is saved and
again when it runs — and optionally starts writing them; it never applies a brief or publishes. The schema is the
OpenAPI document's (`ACTIONS_SCHEMA`). PyGithub's HTTP is recorded (`responses`); nothing reaches GitHub or a model."""

import pytest
import responses
from django.core.exceptions import ValidationError

from ai.models import Assistant, Brief
from automations import spec
from automations.models import AutomationRun
from tests.sites.test_directives import REPO, github

from .test_actions import fired

pytestmark = pytest.mark.django_db
HOOK = {"kind": "hook", "hook": "act"}


@pytest.fixture
def managed(site_root):
    from wagtail.models import Site

    from distribution.models import Channel
    from sites.models import ManagedSite

    made = ManagedSite.objects.create(site=Site.objects.get(root_page=site_root), key="bash-365", checkout="sites/x")
    channel = Channel.objects.create(site=made.site, kind="github_pr", name="GitHub", settings={"repo": REPO})
    channel.set_credentials({"token": "ghp_test_token"})
    channel.save()
    return made


def test_the_action_is_in_the_schema_the_openapi_document_describes():
    kinds = [one["properties"]["kind"]["const"] for one in spec.ACTIONS_SCHEMA["items"]["oneOf"]]
    assert "directives" in kinds
    assert spec._action({"kind": "directives", "site": "bash-365", "generate": True}) == ""
    assert "site" in spec._action({"kind": "directives"})  # the site is required
    assert spec._action({"kind": "directives", "site": "a/b"}) != ""  # a key, never a path


def test_a_schedule_pulls_the_directives_into_briefs_as_its_owner(alice, make, worker, managed, fake):
    writer = Assistant.objects.create(owner=alice, name="Writer")
    action = {"kind": "directives", "site": "bash-365", "assistant": str(writer.public_id), "generate": True}
    make(alice, HOOK, [action])
    with responses.RequestsMock() as rsps:
        github(rsps)
        [run] = fired(worker, {})
    assert run.status == AutomationRun.SUCCEEDED, run.outcomes
    result = run.outcomes[0]["result"]
    assert (len(result["briefs"]), result["skipped"], result["ignored"], len(result["runs"])) == (2, 0, 2, 2)
    briefs = Brief.objects.filter(metadata__has_key="directive")
    assert briefs.count() == 2 and all(b.owner == alice and b.assistant == writer for b in briefs)
    assert not briefs.filter(status=Brief.APPLIED).exists() and not briefs.exclude(page=None).exists()

    with responses.RequestsMock() as rsps:  # the next tick: nothing new
        github(rsps)
        [again] = fired(worker, {})
    assert again.outcomes[0]["result"]["briefs"] == [] and again.outcomes[0]["result"]["skipped"] == 2


def test_a_site_its_owner_does_not_edit_is_refused_when_saved_and_when_it_runs(alice, bob, make, worker, managed):
    with pytest.raises(ValidationError) as refused:
        make(bob, HOOK, [{"kind": "directives", "site": "bash-365"}])
    assert "not a site its owner edits" in refused.value.message_dict["actions"][0]
    with pytest.raises(ValidationError) as unknown:
        make(alice, HOOK, [{"kind": "directives", "site": "nowhere"}])
    assert "no managed site" in unknown.value.message_dict["actions"][0]

    make(alice, HOOK, [{"kind": "directives", "site": "bash-365"}])
    alice.groups.clear()  # alice no longer edits the site
    with responses.RequestsMock() as rsps:
        [run] = fired(worker, {})
        assert not rsps.calls, "nothing is asked of GitHub for a site its owner may not use"
    assert run.status == AutomationRun.FAILED and "not a site its owner edits" in run.outcomes[0]["error"]
