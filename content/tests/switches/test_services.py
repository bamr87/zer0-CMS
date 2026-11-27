"""The content switches' reading of a switch (switches/services.py): opt-in and opt-out the way the loop reads them,
levels that win, drift against the map's recorded state, holds, the variables the map has no record of, and an
unreadable list that is never "off"."""

import yaml

from switches import services
from switches.services import effective, evaluate

from .conftest import MAP

SWITCH_MAP = yaml.safe_load(MAP)["switches"]
LOOPS = SWITCH_MAP["loops"]


def row(ident, live):
    return evaluate(ident, LOOPS[ident], SWITCH_MAP, live)


def test_opt_in_is_on_only_at_exactly_true_and_opt_out_is_on_unless_exactly_false():
    assert [effective("opt_in", v) for v in (None, "true", "false", "yes", "")] == ["off", "on", "off", "off", "off"]
    assert [effective("opt_out", v) for v in (None, "true", "false", "yes", "")] == ["on", "on", "off", "on", "on"]


def test_a_variable_the_map_does_not_know_is_on_at_true_off_at_false_and_otherwise_unknown():
    assert [effective(None, v) for v in ("true", "false", "yes", "")] == ["on", "off", "unknown", "unknown"]


def test_unreadable_is_unknown_never_off():
    assert effective("opt_in", None, readable=False) == "unknown"
    unread = row("lh/factory", None)
    assert unread["live_state"] == "unreadable" and unread["effective"] == "unknown" and not unread["drift"]
    assert unread["why"] == "CONTENT_FACTORY_ENABLED could not be read"


def test_an_opt_in_switch_that_agrees_with_the_map():
    factory = row("lh/factory", {"CONTENT_FACTORY_ENABLED": "true"})
    assert factory["effective"] == "on" and factory["live"] == "true" and factory["live_state"] == "set"
    assert factory["map_state"] == "on" and factory["verified"] and not factory["drift"]
    assert (factory["reason"], factory["set_by"], factory["set_at"]) == (
        "maintainer instruction",
        "bamr87",
        "2026-11-24",
    )
    assert factory["flippable"] and not factory["merge_authority"]


def test_drift_is_the_live_value_against_the_recorded_state_and_the_default_while_unverified():
    assert row("lh/factory", {"CONTENT_FACTORY_ENABLED": "false"})["drift"]  # the map says on
    assert row("lh/issue-1", {})["drift"]  # unset opt-in is off; the map says on
    epic = row("lh/weekly-epic", {})  # unverified: the default (off) is the map's claim
    assert epic["effective"] == "off" and epic["live_state"] == "unset" and not epic["drift"]
    assert row("lh/weekly-epic", {"WEEKLY_EPIC_ENABLED": "true"})["drift"]


def test_an_opt_out_switch_unset_is_on():
    daily = row("ij/daily", {})
    assert daily["semantics"] == "opt_out" and daily["effective"] == "on" and not daily["drift"]
    assert row("ij/daily", {"CMS_DAILY_LOOP_ENABLED": "false"})["effective"] == "off"


def test_a_group_that_is_off_wins_over_the_variable():
    links = row("ij/links", {"LINK_CHECKER_ENABLED": "true"})
    assert links["effective"] == "off" and links["why"] == "group paused is off: paused for the audit"
    assert links["live"] == "true"  # still shown as it is set


def test_a_hold_is_carried_and_said():
    merge = row("lh/auto-merge", {"AUTO_MERGE_ENABLED": "true"})
    assert merge["hold"] == {"kind": "env", "name": "HUB_ORIGINATION_HOLD", "value": "true", "lift": "a new amendment"}
    assert merge["effective"] == "on" and merge["drift"] and merge["merge_authority"]
    assert merge["why"].endswith("held by HUB_ORIGINATION_HOLD whatever the variable says")


def test_a_loop_with_no_repository_switch_is_what_the_map_says():
    nightly = row("lh/nightly", {})
    assert nightly["variable"] is None and nightly["live_state"] == "none" and not nightly["flippable"]
    assert nightly["effective"] == "on" and nightly["why"] == "no repository switch: the map's default is on"


def test_an_outlets_rows_are_its_records_then_its_unmapped_enabled_variables():
    records = services.records_for(SWITCH_MAP, "o/ij")
    assert [ident for ident, _ in records] == ["ij/daily", "ij/links"]  # O/IJ matches o/ij
    live = {"LINK_CHECKER_ENABLED": "true", "QUEST_FIX_ENABLED": "true", "NODE_VERSION": "20", "X_ENABLED": "maybe"}
    rows = services.unmapped(live, {"LINK_CHECKER_ENABLED"})
    assert [(r["variable"], r["effective"], r["in_map"]) for r in rows] == [
        ("QUEST_FIX_ENABLED", "on", False),
        ("X_ENABLED", "unknown", False),
    ]
    assert rows[0]["why"].endswith("not in the hub map, so its semantics are unknown")


def test_merge_authority_is_named():
    assert all(
        services.merge_authority(n)
        for n in ("AUTO_MERGE_ENABLED", "CONTENT_AUTOMERGE_ENABLED", "AUTO_UPDATE_ENABLED", "AUTO_FIX_ENABLED")
    )
    assert not any(services.merge_authority(n) for n in ("CONTENT_FACTORY_ENABLED", "AUTO_FIXUP_LOG", ""))
