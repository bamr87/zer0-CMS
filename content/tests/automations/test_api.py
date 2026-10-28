"""The automations API (`/api/v2/automations/`, PLAN G16): an automation is made paused and its secret is shown in the
answer that made it alone; it is enabled, tested and changed by its owner only — staff may pause it —, seen by whom
its visibility says, and never by an agent's token; it exports to YAML and a YAML document imports as a new, paused
automation, the round trip unchanged; a test fires a real run and a dry run does nothing; runs are listed by cursor.
Nothing reaches a model or a network."""

import io
import time
import uuid

import pytest
import yaml
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import override_settings

from agents.models import AgentToken
from ai.models import ProviderConfig, Visibility
from automations.models import Automation, AutomationRun
from ideas.models import Idea
from research import services as research

HOOK = {"kind": "hook", "hook": "act"}
IDEA = {"kind": "idea", "title": "About {{ data.topic }}"}
URL = "/api/v2/automations/"


def body(**fields):
    return {"name": "Act on it", "trigger": HOOK, "actions": [IDEA], **fields}


@pytest.mark.django_db
def test_a_new_automation_is_paused_and_its_secret_is_shown_once(alice, api):
    made = api(alice).post(URL, body(enabled=True), format="json")
    assert made.status_code == 201, made.content
    data = made.json()
    assert data["enabled"] is False and data["owner"] == "alice" and data["can_edit"] is True
    assert isinstance(data["secret"], str) and len(data["secret"]) > 30 and data["webhook_url"] is None
    automation = Automation.objects.get(public_id=data["id"])
    assert automation.get_secret() == data["secret"] and data["secret"] not in automation.secret_encrypted
    again = api(alice).get(f"{URL}{data['id']}/").json()
    assert again["secret"] is None and again["last_run"] is None

    hook = api(alice).post(URL, body(trigger={"kind": "webhook"}), format="json").json()
    assert hook["webhook_url"] == f"http://testserver{URL}{hook['id']}/webhook/"


@pytest.mark.django_db
def test_secrets_are_kept_under_the_credential_keys_and_move_with_the_one_rotation(alice, api):
    """`rotate_ai_credentials` — the documented rotation — moves the automations' secrets with the providers'
    credentials, in one transaction: drop the old key afterwards and nothing is left behind under it."""
    made = api(alice).post(URL, body(trigger={"kind": "webhook"}), format="json").json()
    provider = ProviderConfig.objects.get(slug="openai")
    provider.set_credential("sk-openai")
    provider.save()
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    out = io.StringIO()
    with override_settings(AI_CREDENTIAL_KEYS=[old]):
        call_command("rotate_ai_credentials", stdout=out)
    assert out.getvalue().startswith("2 credential(s)")  # the provider's and the automation's
    with override_settings(AI_CREDENTIAL_KEYS=[new, old]):
        call_command("rotate_ai_credentials", stdout=out)
    with override_settings(AI_CREDENTIAL_KEYS=[new], SECRET_KEY="a-new-secret"):
        assert Automation.objects.get(public_id=made["id"]).get_secret() == made["secret"]
        assert ProviderConfig.objects.get(pk=provider.pk).get_credential() == "sk-openai"
    # A secret under a key that is gone stops the rotation, named, and the credentials it had moved stay as they were.
    lost, newer = Fernet.generate_key(), Fernet.generate_key().decode()
    Automation.objects.filter(public_id=made["id"]).update(secret_encrypted=Fernet(lost).encrypt(b"x").decode())
    before = ProviderConfig.objects.get(pk=provider.pk).credential_encrypted
    with override_settings(AI_CREDENTIAL_KEYS=[newer, new]):
        with pytest.raises(CommandError, match="a key that is gone"):
            call_command("rotate_ai_credentials", stdout=out)
        assert ProviderConfig.objects.get(pk=provider.pk).credential_encrypted == before  # all of it, or none
        refused = api().post(
            f"{URL}{made['id']}/webhook/",
            data=b"{}",
            content_type="application/json",
            HTTP_X_ZER0_SIGNATURE_256="sha256=0",
        )
        assert refused.status_code == 401 and refused.json()["error"]["code"] == "webhook.signature"


@pytest.mark.django_db
def test_enabling_checks_it_again_and_pausing_is_its_owners_or_staffs(alice, bob, api):
    empty = api(alice).post(URL, body(actions=[]), format="json").json()
    assert api(alice).post(f"{URL}{empty['id']}/enable/").status_code == 422  # nothing to do yet
    made = api(alice).post(URL, body(visibility="shared"), format="json").json()
    path = f"{URL}{made['id']}"
    assert api(bob).post(f"{path}/enable/").status_code == 403
    enabled = api(alice).post(f"{path}/enable/")
    assert enabled.status_code == 200 and enabled.json()["enabled"] is True
    assert api(bob).post(f"{path}/disable/").status_code == 403
    staff = get_user_model().objects.create_user("ops", password="pw", is_staff=True)
    assert api(staff).post(f"{path}/disable/").json()["enabled"] is False  # staff stop anyone's
    assert api(staff).post(f"{path}/enable/").status_code == 403  # but it runs as alice: only she starts it


@pytest.mark.django_db
def test_who_sees_an_automation_and_who_changes_it(alice, bob, api, worker):
    private = api(alice).post(URL, body(name="Mine"), format="json").json()
    shared = api(alice).post(URL, body(name="Ours", visibility=Visibility.SHARED), format="json").json()
    assert api(bob).get(f"{URL}{private['id']}/").status_code == 404
    assert [a["name"] for a in api(bob).get(URL).json()["results"]] == ["Ours"]
    seen = api(bob).get(f"{URL}{shared['id']}/").json()
    assert seen["can_edit"] is False and seen["secret"] is None
    path = f"{URL}{shared['id']}"
    for method, suffix in (("patch", "/"), ("post", "/test/"), ("post", "/dry-run/"), ("post", "/rotate-secret/")):
        assert getattr(api(bob), method)(f"{path}{suffix}", {"name": "Taken"}, format="json").status_code == 403
    assert api(bob).delete(f"{path}/").status_code == 403
    assert api(bob).get(f"{path}/export/").status_code == 200  # what it does is no secret

    worker(api(alice).post, f"{path}/test/", {"payload": {"data": {"topic": "x"}}}, format="json")
    worker(api(alice).post, f"{URL}{private['id']}/test/", {"payload": {}}, format="json")
    # What it does is shared; what it heard and did, as alice, is hers — and staff's.
    assert api(bob).get(f"{URL}runs/").json()["results"] == []
    assert api(bob).get(f"{path}/").json()["last_run"] is None
    assert api(alice).get(f"{path}/").json()["last_run"]["status"] == "succeeded"
    assert len(api(alice).get(f"{URL}runs/").json()["results"]) == 2
    staff = get_user_model().objects.create_user("ops", password="pw", is_staff=True)
    assert len(api(staff).get(f"{URL}runs/").json()["results"]) == 2

    agent = get_user_model().objects.get(username="agent:drafter")
    raw = AgentToken.issue(agent, name="test")[1]
    from rest_framework.test import APIClient

    assert APIClient().get(URL, HTTP_AUTHORIZATION=f"Bearer {raw}").status_code == 403  # people only


@pytest.mark.django_db
def test_sharing_an_automation_never_shares_what_it_heard(alice, bob, api, worker):
    """alice's private note fires her shared automation: bob reads what the automation does, never the note — not in
    its runs, not in its last run, not in a brief it writes."""
    actions = [{"kind": "idea", "title": "{{ source.title }}"}, {"kind": "brief", "prompt": "{{ source.text }}"}]
    shared = (
        api(alice)
        .post(URL, body(trigger={"kind": "source"}, actions=actions, visibility=Visibility.SHARED), format="json")
        .json()
    )
    api(alice).post(f"{URL}{shared['id']}/enable/")
    worker(research.add_note, alice, "Mine alone\nSECRET-PRIVATE-TEXT")
    [run] = api(alice).get(f"{URL}runs/").json()["results"]
    assert "SECRET-PRIVATE-TEXT" in str(run["payload"]) and run["status"] == "succeeded", run
    for path in (f"{URL}runs/", f"{URL}{shared['id']}/", f"{URL}", "/api/v2/ai/briefs/"):
        answer = api(bob).get(path)
        assert answer.status_code == 200 and "SECRET-PRIVATE-TEXT" not in answer.content.decode(), path
    assert api(bob).get(f"{URL}runs/{run['id']}/").status_code == 404


@pytest.mark.django_db
def test_an_automation_changes_through_the_models_checks(alice, api):
    made = api(alice).post(URL, body(), format="json").json()
    path = f"{URL}{made['id']}/"
    bad = api(alice).patch(path, {"trigger": {"kind": "schedule", "cron": "every morning"}}, format="json")
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "trigger"
    unknown = api(alice).patch(path, {"actions": [{"kind": "publish", "page": "1"}]}, format="json")
    assert unknown.status_code == 422 and unknown.json()["error"]["details"][0]["field"] == "actions"
    changed = api(alice).patch(path, {"name": "Renamed", "enabled": True, "max_runs_per_hour": 5}, format="json")
    assert changed.status_code == 200 and changed.json()["name"] == "Renamed" and changed.json()["enabled"] is False
    assert api(alice).patch(path, {"max_runs_per_hour": 0}, format="json").status_code == 422


@pytest.mark.django_db
def test_an_automation_exports_to_yaml_and_imports_as_a_new_paused_one(alice, bob, api):
    original = (
        api(alice)
        .post(
            URL,
            body(
                name="Wire to ideas",
                description="Every wire item, kept as an idea.",
                trigger={"kind": "source"},
                condition="source.kind == 'feed'",
                actions=[{"kind": "idea", "title": "{{ source.title }}", "tags": ["wire"]}],
                on_error="continue",
                max_runs_per_hour=30,
            ),
            format="json",
        )
        .json()
    )
    api(alice).post(f"{URL}{original['id']}/enable/")
    exported = api(alice).get(f"{URL}{original['id']}/export/").json()
    document = yaml.safe_load(exported["yaml"])
    assert exported["name"] == "Wire to ideas" and list(document) == [
        "name",
        "description",
        "trigger",
        "condition",
        "actions",
        "on_error",
        "max_runs_per_hour",
    ]
    assert "secret" not in exported["yaml"] and "alice" not in exported["yaml"]

    imported = api(bob).post(f"{URL}import/", {"yaml": exported["yaml"]}, format="json")
    assert imported.status_code == 201, imported.content
    copy = imported.json()
    assert (copy["owner"], copy["enabled"], copy["visibility"]) == ("bob", False, "private")
    assert copy["id"] != original["id"] and copy["secret"] and copy["secret"] != original["secret"]
    again = api(bob).get(f"{URL}{copy['id']}/export/").json()["yaml"]
    assert again == exported["yaml"]  # the round trip changes nothing

    for text, why in (
        ("name: [unclosed", "not a YAML document"),
        ("- a list", "a mapping with a name"),
        ("name: [a, list]", "a mapping with a name"),
        (exported["yaml"] + "owner: alice\n", "has no owner"),
        (exported["yaml"].replace("kind: source", "kind: rss"), "kind is one of"),
    ):
        refused = api(bob).post(f"{URL}import/", {"yaml": text}, format="json")
        assert refused.status_code == 422 and why in str(refused.json()), refused.json()


@pytest.mark.django_db
def test_an_import_that_would_expand_or_nest_without_end_is_refused_at_once(alice, api):
    """Ten levels of aliases, each naming the one before ten times, are under a kilobyte of YAML and ten billion values
    once read: refused before anything is expanded, as is nesting deeper than any automation needs."""
    levels = ["a0: &a0 [x, x, x, x, x, x, x, x, x, x]"]
    levels += [f"a{n}: &a{n} [{', '.join([f'*a{n - 1}'] * 10)}]" for n in range(1, 10)]
    bomb = "\n".join(levels) + "\nname: Bomb\ndescription: *a9\n"  # each anchor before the aliases that name it
    deep = "name: Deep\ncondition: " + "[" * 5000 + "]" * 5000
    for text, why in ((bomb, "no aliases"), (deep, "nests at most")):
        started = time.monotonic()
        refused = api(alice).post(f"{URL}import/", {"yaml": text}, format="json")
        assert refused.status_code == 422 and why in refused.json()["error"]["message"], refused.content[:300]
        assert time.monotonic() - started < 2 and len(refused.content) < 2000
    assert not Automation.objects.exists()


@pytest.mark.django_db
def test_a_test_fires_a_real_run_and_a_dry_run_does_nothing(alice, api, worker):
    made = api(alice).post(URL, body(condition="data.topic != 'skip'"), format="json").json()
    path = f"{URL}{made['id']}"
    dry = api(alice).post(f"{path}/dry-run/", {"payload": {"data": {"topic": "tides"}}}, format="json").json()
    assert dry["matched"] is True and dry["actions"] == [
        {"index": 0, "kind": "idea", "input": {"title": "About tides"}}
    ]
    assert not AutomationRun.objects.exists() and not Idea.objects.exists()

    key = {"HTTP_IDEMPOTENCY_KEY": str(uuid.uuid4())}
    tested = worker(api(alice).post, f"{path}/test/", {"payload": {"data": {"topic": "tides"}}}, format="json", **key)
    assert tested.status_code == 202, tested.content  # paused, and tested all the same
    run = AutomationRun.objects.get(public_id=tested.json()["id"])
    assert (run.trigger, run.status) == ("test", AutomationRun.SUCCEEDED)
    assert Idea.objects.get().title == "About tides"
    replayed = api(alice).post(f"{path}/test/", {"payload": {"data": {"topic": "tides"}}}, format="json", **key)
    assert replayed.json()["id"] == str(run.public_id) and AutomationRun.objects.count() == 1

    shown = api(alice).get(f"{URL}runs/{run.public_id}/").json()
    assert shown["outcomes"][0]["status"] == "succeeded" and shown["payload"] == {"data": {"topic": "tides"}}
    assert api(alice).get(f"{path}/").json()["last_run"]["id"] == str(run.public_id)


@pytest.mark.django_db
def test_runs_are_listed_newest_first_by_cursor_and_filtered(alice, api, worker):
    one = api(alice).post(URL, body(name="One"), format="json").json()
    two = api(alice).post(URL, body(name="Two", condition="data.go"), format="json").json()
    for automation in (one, one, two):
        worker(api(alice).post, f"{URL}{automation['id']}/test/", {"payload": {"data": {}}}, format="json")
    first = api(alice).get(f"{URL}runs/", {"page_size": 2}).json()
    assert len(first["results"]) == 2 and first["next"]
    rest = api(alice).get(first["next"]).json()
    assert len(rest["results"]) == 1 and rest["next"] is None
    names = [r["automation_name"] for r in first["results"] + rest["results"]]
    assert names == ["Two", "One", "One"]  # newest first
    assert len(api(alice).get(f"{URL}runs/", {"automation": one["id"]}).json()["results"]) == 2
    skipped = api(alice).get(f"{URL}runs/", {"status": "skipped"}).json()["results"]
    assert [r["automation_name"] for r in skipped] == ["Two"]  # its condition wanted data.go


@pytest.mark.django_db
def test_options_list_what_to_pick_and_a_sample_payload_per_trigger(alice, api):
    options = api(alice).get(f"{URL}options/").json()
    assert options["events"] == ["content.page.published", "content.suggestion.created", "agent.run.completed"]
    assert options["stages"] == ["assigned", "drafting", "editing", "copy"]
    assert "seo" in [a["slug"] for a in options["agents"]]
    samples = options["samples"]
    assert set(samples) == {"event", "schedule", "webhook", "source", "hook"}
    assert samples["event"]["content.page.published"]["type"] == "content.page.published"
