"""The publishing cadence (`distribution/cadence.py`, issue #89) and the lane's
release queue over it (`lane.pipeline.Pipeline.publish_queue`, `calendar`): when
an approved draft goes, never whether. The clock is the fixtures' `NOW`, a
Monday (2026-09-14 12:00 UTC); recorded HTTP only.
"""

import io
import json
import os
import subprocess
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from distribution import cadence
from distribution.lane import cli
from distribution.lane.pipeline import Pipeline
from distribution.lane.site import Config
from distribution.lane.x_site import XConfig

from .conftest import MCP_POST, NOW
from .test_lane import ARMED, approved_draft, credentials, nosleep, script_publish

UTC_TWICE = {"timezone": "UTC", "slots": ["mon 11:00", "wed 11:00"], "grace": "6h"}


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def lane(root, *, when=NOW, env=None):
    return Pipeline(Config(root, env=env or {}), sleeper=nosleep, clock=lambda: when, credentials=credentials())


def note(pipe, slug):
    draft = pipe.compose_update(f"A short note about {slug}.", slug=slug)
    assert pipe.approve(draft).state == "approved"
    return pipe.draft(draft.id)


def pin(draft, value):
    text = draft.path.read_text()
    draft.path.write_text(text.replace("status: approved\n", f"status: approved\npublish_at: {value}\n", 1))


# ── reading a cadence ───────────────────────────────────────────────────────


def test_no_cadence_is_none_and_the_defaults_are_one_a_day_six_hours_grace():
    assert cadence.parse(None) is None and cadence.parse({}) is None
    c = cadence.parse({"slots": ["tue 09:00"]})
    assert (c.timezone, c.per_day, c.per_week, c.min_gap, c.after_page, c.grace) == (
        "UTC",
        1,
        None,
        timedelta(0),
        timedelta(0),
        timedelta(hours=6),
    )


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        ("mon", (0,)),
        ("mon,wed,fri", (0, 2, 4)),
        ("mon-fri", (0, 1, 2, 3, 4)),
        ("fri-mon", (0, 4, 5, 6)),
        ("daily", tuple(range(7))),
        ("weekdays", (0, 1, 2, 3, 4)),
        ("weekends", (5, 6)),
    ],
)
def test_slot_days(days, expected):
    assert tuple(d for d, _ in cadence.parse({"slots": [f"{days} 08:30"]}).slots) == expected


def test_every_problem_is_named_with_its_key_and_an_unknown_key_is_one():
    problems = cadence.problems(
        {
            "timezone": "Mars/Olympus",
            "slots": ["tues 9", "mon 25:00"],
            "minGap": "2 days",
            "perDay": 0,
            "perWeek": "two",
            "blackout": ["2026-12-31..2026-12-24"],
            "afterpage": "1h",
        }
    )
    assert [p.split(":")[0].split(" ")[0] for p in problems] == [
        "cadence.afterpage",
        "cadence.timezone",
        "cadence.slots[0]",
        "cadence.slots[1]",
        "cadence.minGap",
        "cadence.perDay",
        "cadence.perWeek",
        "cadence.blackout[0]",
    ]
    assert cadence.problems({"slots": []}) == [
        'cadence.slots: needs at least one slot, like "tue 09:00" or "mon-fri 08:30"'
    ]
    assert cadence.problems("tue 09:00")[0].startswith("cadence: an object")


def test_durations_read_and_print_alike():
    for text, span in (("0", timedelta(0)), ("90m", timedelta(minutes=90)), ("1d12h", timedelta(hours=36))):
        assert cadence.duration(text) == span
        assert cadence.duration(cadence.describe(span)) == span
    for bad in ("2 days", "1.5h", "h", "-1h", True):
        with pytest.raises(ValueError):
            cadence.duration(bad)


def test_a_pinned_time_is_read_in_the_cadences_zone_when_it_names_none():
    denver = ZoneInfo("America/Denver")
    assert cadence.moment("2026-11-10 09:00", denver) == at("2026-11-10T16:00:00")
    assert cadence.moment("2026-11-10T09:00:00Z", denver) == at("2026-11-10T09:00:00")
    assert cadence.moment("2026-11-10T09:00:00-05:00", denver) == at("2026-11-10T14:00:00")
    assert cadence.moment("2026-11-10", denver) == at("2026-11-10T07:00:00")
    for bad in ("", "next tuesday", "2026-13-01"):
        with pytest.raises(ValueError):
            cadence.moment(bad, denver)


# ── the calendar and its rules ──────────────────────────────────────────────


def test_slots_keep_their_local_time_across_the_change_from_daylight_time():
    c = cadence.parse({"timezone": "America/Denver", "slots": ["sun 09:00"]})
    october, november = list(c.slots_from(at("2026-10-24T12:00:00"), days=8))
    assert (october, november) == (at("2026-10-25T15:00:00"), at("2026-11-01T16:00:00"))
    assert c.show(november) == "Sun 2026-11-01 09:00 MST"


def test_the_rules_gap_daily_and_weekly_caps_and_blackouts():
    c = cadence.parse(
        {"slots": ["daily 09:00", "daily 17:00"], "minGap": "6h", "perDay": 2, "perWeek": 3, "blackout": ["2026-09-16"]}
    )
    monday = at("2026-09-14T09:00:00")
    assert c.reasons(monday, []) == []
    assert "minGap" in c.reasons(monday, [monday - timedelta(hours=2)])[0]
    assert "perDay" in c.reasons(monday, [at("2026-09-14T00:30:00"), at("2026-09-14T20:00:00")])[-1]
    assert "perWeek" in c.reasons(monday, [at("2026-09-15T09:00:00")] * 3)[-1]
    assert "blackout" in c.reasons(at("2026-09-16T09:00:00"), [])[0]
    # Tuesday's two slots are taken and Wednesday is dark, so Thursday morning is next.
    taken = [at("2026-09-15T09:00:00"), at("2026-09-15T17:00:00")]
    assert c.next_slot(at("2026-09-15T08:00:00"), taken) == at("2026-09-17T09:00:00")
    dark = cadence.parse({"slots": ["mon 09:00"], "blackout": ["2026-01-01..2028-01-01"]})
    assert dark.next_slot(monday) is None


def test_a_slot_is_open_until_grace_runs_out_or_something_publishes():
    c = cadence.parse(UTC_TWICE)
    assert c.open_slot(NOW) == at("2026-09-14T11:00:00")
    assert c.open_slot(NOW, [at("2026-09-14T11:30:00")]) is None, "something went since the slot opened"
    assert c.open_slot(NOW, [at("2026-09-12T11:00:00")]) == at("2026-09-14T11:00:00")
    assert c.open_slot(at("2026-09-14T17:30:00")) is None, "six hours of grace have passed"
    assert c.open_slot(at("2026-09-14T10:59:00")) is None, "Monday's slot has not opened"
    gap = cadence.parse({**UTC_TWICE, "minGap": "48h"})
    assert gap.open_slot(NOW, [at("2026-09-13T11:00:00")]) is None, "the rules hold at the moment of release"


def test_the_plan_puts_a_due_pin_first_then_the_queue_in_order():
    c = cadence.parse(UTC_TWICE)
    items = [
        cadence.Item("a", order=0),
        cadence.Item("b", order=1),
        cadence.Item("pinned", at("2026-09-16T00:00:00"), pinned=True, order=2),
        cadence.Item("phase", at("2026-09-22T00:00:00"), order=3),
    ]
    placed = {p.key: p.at for p in c.plan(items, times=c.slots_from(NOW))}
    assert placed == {
        "pinned": at("2026-09-16T11:00:00"),
        "a": at("2026-09-21T11:00:00"),
        "b": at("2026-09-23T11:00:00"),
        "phase": at("2026-09-28T11:00:00"),
    }
    dark = cadence.parse({"slots": ["mon 09:00"], "blackout": ["2026-01-01..2028-01-01"]})
    (lost,) = dark.plan([cadence.Item("a")], times=dark.slots_from(NOW))
    assert lost.at is None and "no slot" in lost.reason


# ── the lane: settings ──────────────────────────────────────────────────────


def test_a_cadence_the_lane_cannot_read_is_an_error_that_blocks_publishing(make_checkout):
    root = make_checkout({"cadence": {"slots": ["someday"], "perday": 2}})
    config = Config(root, env={})
    assert config.cadence is None
    assert [e.split(":")[0] for e in config.errors] == [
        "distribution.linkedin.cadence.perday is not a setting (known",
        "distribution.linkedin.cadence.slots[0]",
    ]
    pipe = lane(root)
    draft = approved_draft(pipe)
    assert "config_error" in [b.kind for b in pipe.preview(draft).blockers]
    good = make_checkout({"cadence": UTC_TWICE})
    assert Config(good, env={}).cadence.slots == cadence.parse(UTC_TWICE).slots
    assert not [w for w in Config(good, env={}).warnings if "cadence" in w]
    x = make_checkout(zer0={"distribution": {"x": {"account": "bamr87", "cadence": UTC_TWICE}}})
    assert XConfig(x, env={}).cadence is not None and not XConfig(x, env={}).warnings


# ── the lane: a queue run under a cadence ───────────────────────────────────


def test_a_queue_run_releases_one_draft_per_open_slot_and_the_rest_wait(make_checkout, web):
    root = make_checkout({"cadence": UTC_TWICE})
    post = script_publish(web)
    first = approved_draft(lane(root))
    second = note(lane(root), "second")
    early = lane(root, when=at("2026-09-14T10:00:00"), env=ARMED).publish_queue(live=True)
    assert [o.state for o in early] == ["waiting", "waiting"] and not web.calls
    assert early[0].messages == ["waiting for its slot: Mon 2026-09-14 11:00 UTC"]
    outcomes = lane(root, env=ARMED).publish_queue(live=True)
    assert [(o.draft.id, o.state) for o in outcomes] == [(first.id, "published"), (second.id, "waiting")]
    assert outcomes[1].messages == ["waiting for its slot: Wed 2026-09-16 11:00 UTC"]
    assert post.call_count == 1
    again = lane(root, when=NOW + timedelta(hours=1), env=ARMED).publish_queue(live=True)
    assert [o.state for o in again] == ["waiting"] and post.call_count == 1, "the slot is spent"
    wednesday = lane(root, when=at("2026-09-16T11:20:00"), env=ARMED).publish_queue(live=True)
    assert [o.state for o in wednesday] == ["published"] and post.call_count == 2


def test_a_draft_a_gate_refuses_gives_the_slot_to_the_next(make_checkout, web):
    root = make_checkout({"cadence": UTC_TWICE})
    script_publish(web)
    broken = note(lane(root), "a-broken")
    broken.path.write_text(broken.path.read_text().replace("A short note about a-broken.", "Synergy! " * 400))
    good = note(lane(root), "b-good")
    outcomes = lane(root, env=ARMED).publish_queue(live=True)
    assert [(o.draft.id, o.state) for o in outcomes] == [(broken.id, "blocked"), (good.id, "published")]


def test_a_rehearsal_shows_which_draft_the_open_slot_would_take(make_checkout, web):
    root = make_checkout({"cadence": UTC_TWICE})
    approved_draft(lane(root))
    note(lane(root), "second")
    assert [o.state for o in lane(root).publish_queue()] == ["rehearsed", "waiting"] and not web.calls


def test_a_named_publish_is_a_persons_act_and_never_waits(make_checkout, web):
    root = make_checkout({"cadence": UTC_TWICE})
    script_publish(web)
    draft = approved_draft(lane(root))
    pin(draft, "2026-12-01 09:00")
    pipe = lane(root, when=at("2026-09-15T03:00:00"), env=ARMED)
    assert pipe.publish(pipe.draft(draft.id), live=True).state == "published"


def test_publish_at_holds_a_draft_even_without_a_cadence_and_a_bad_one_blocks_it(checkout, web):
    script_publish(web)
    later = note(lane(checkout), "later")
    pin(later, "2026-09-14 18:00")
    now = note(lane(checkout), "now")
    broken = note(lane(checkout), "zz-broken")
    pin(broken, "next tuesday")
    outcomes = {o.draft.id: o for o in lane(checkout, env=ARMED).publish_queue(live=True)}
    assert {k: o.state for k, o in outcomes.items()} == {later.id: "waiting", now.id: "published", broken.id: "blocked"}
    assert outcomes[later.id].messages == ["waiting for its publish_at: 2026-09-14 18:00 UTC"]
    assert "not a time" in outcomes[broken.id].messages[0]
    evening = lane(checkout, when=at("2026-09-14T18:05:00"), env=ARMED).publish_queue(live=True)
    assert [(o.draft.id, o.state) for o in evening] == [(later.id, "published"), (broken.id, "blocked")]


def test_without_a_cadence_or_a_pin_a_queue_run_is_what_it_was(checkout, web):
    script_publish(web)
    approved_draft(lane(checkout))
    note(lane(checkout), "second")
    assert [o.state for o in lane(checkout, env=ARMED).publish_queue(live=True)] == ["published", "published"]


# ── the lane: the page's phase ──────────────────────────────────────────────


def git(root, *args, when=None):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    if when:
        env |= {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "-c", "core.hooksPath=/dev/null", *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
    )


def test_a_share_waits_after_page_for_its_page_to_land_on_the_branch(make_checkout, web):
    root = make_checkout({"cadence": {**UTC_TWICE, "afterPage": "2h"}})
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the site", when="2026-09-01T09:00:00+00:00")
    (root / MCP_POST).write_text((root / MCP_POST).read_text() + "\nOne more line.\n")
    git(root, "commit", "-qam", "the page lands again on main", when="2026-09-14T10:30:00+00:00")
    pipe = lane(root)
    page = pipe.resolve_source(MCP_POST)
    assert pipe.landed(page) == at("2026-09-01T09:00:00"), "the oldest first-parent commit is when it landed"
    script_publish(web)
    share = approved_draft(lane(root))
    rows = {r.draft.id: r for r in lane(root).calendar()}
    assert rows[share.id].not_before == at("2026-09-01T11:00:00") and rows[share.id].at == NOW
    fresh = make_checkout({"cadence": {**UTC_TWICE, "afterPage": "2h"}})
    git(fresh, "init", "-q", "-b", "main")
    git(fresh, "add", "-A")
    git(fresh, "commit", "-q", "-m", "the site, with the page, an hour ago", when="2026-09-14T11:00:00+00:00")
    share = approved_draft(lane(fresh))
    outcomes = lane(fresh, env=ARMED).publish_queue(live=True)
    assert outcomes[0].state == "waiting" and outcomes[0].messages == ["waiting for its slot: Wed 2026-09-16 11:00 UTC"]
    assert lane(fresh).landed(lane(fresh).resolve_source(MCP_POST)) == at("2026-09-14T11:00:00")


def test_without_git_a_page_has_landed_on_its_date(checkout):
    pipe = lane(checkout)
    page = pipe.resolve_source(MCP_POST)
    assert pipe.landed(page) == page.date and page.date.date() == date(2026, 7, 6)


# ── the lane: what a person and an agent see ────────────────────────────────


def test_the_calendar_command_and_the_mcp_tool(make_checkout):
    root = make_checkout({"cadence": UTC_TWICE})
    first = approved_draft(lane(root))
    second = note(lane(root), "second")
    out = io.StringIO()
    code = cli.main(["calendar", "--site", str(root), "--json"], out=out, env={})
    assert code == 0
    data = json.loads(out.getvalue())
    assert data["cadence"] == "mon,wed 11:00 (UTC), at most 1 a day"
    assert [(d["id"], d["at"]) for d in data["drafts"]] == [
        (first.id, data["drafts"][0]["at"]),
        (second.id, data["drafts"][1]["at"]),
    ]
    text = io.StringIO()
    assert cli.main(["calendar", "--site", str(root)], out=text, env={}) == 0
    assert "cadence  mon,wed 11:00 (UTC), at most 1 a day" in text.getvalue()
    from distribution.lane.mcp import Server

    server = Server(str(root), env={})
    reply = server.call("linkedin_calendar", {})
    assert not reply["isError"]
    assert [d["id"] for d in json.loads(reply["content"][0]["text"])["drafts"]] == [first.id, second.id]
