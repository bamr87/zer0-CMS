"""The platform's release queue (issue #89): a channel's cadence, approving
into the next slot, a time a person chose, and beat's release of what is due
(`services.schedule`, `unschedule`, `release_due`, `calendar` and their API).
A cadence decides when an approved post goes, never whether: every gate runs
again at release, and a person's Publish now is never held.

Recorded HTTP only (respx); the worker runs what a release queued after it
commits (`worker`).
"""

from datetime import UTC, timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from distribution import cadence as cadences
from distribution import services
from distribution.models import Channel, DistributionPost
from ops.errors import Conflict, Invalid

from ..conftest import make_article
from . import test_platform as platform
from .test_platform import API, REST, approved

# The platform tests' people, page and channel, as fixtures of this module too.
article, carol, channel, manager = platform.article, platform.carol, platform.channel, platform.manager

DAILY = {"timezone": "UTC", "slots": ["daily 09:00"]}


def published(web, urn="urn:li:share:88"):
    return web.post(f"{REST}/posts").respond(201, headers={"x-restli-id": urn})


def with_cadence(channel, spec):
    Channel.objects.filter(pk=channel.pk).update(cadence=spec)
    channel.refresh_from_db()
    return channel


def post_of(channel, user, page, text="We copy the site every night."):
    return services.compose(channel, user=user, page=page, commentary=text)


def second_page(article, title="Weekly restores"):
    return make_article(article.get_parent(), title, search_description="Why we restore a copy every week.")


# ── a channel's cadence ─────────────────────────────────────────────────────


def test_a_channels_cadence_is_checked_on_save_and_shown_in_words(api, manager, channel):
    url = f"{API}/channels/{channel.public_id}/"
    bad = api(manager).patch(url, {"cadence": {"slots": ["someday"], "perday": 2}}, format="json")
    assert bad.status_code == 422
    assert [d["message"].split(":")[0] for d in bad.json()["error"]["details"]] == [
        "cadence.perday is not a setting (known",
        "cadence.slots[0]",
    ]
    assert "cadence.perday is not a setting" in bad.json()["error"]["message"]
    good = api(manager).patch(url, {"cadence": {**DAILY, "afterPage": "1h"}}, format="json")
    assert good.status_code == 200, good.json()
    assert good.json()["cadence_summary"] == "daily 09:00 (UTC), at most 1 a day, 1h after the page"
    cleared = api(manager).patch(url, {"cadence": {}}, format="json")
    assert (cleared.json()["cadence"], cleared.json()["cadence_summary"]) == ({}, "")


# ── approving into the queue ────────────────────────────────────────────────


def test_approving_on_a_cadence_channel_queues_each_post_in_the_next_free_slot(alice, channel, article):
    with_cadence(channel, DAILY)
    spec = cadences.parse(DAILY)
    before = timezone.now()
    first = approved(post_of(channel, alice, article), alice)
    assert first.status == "approved" and first.scheduled_by == alice and not first.scheduled_pinned
    assert first.scheduled_for == spec.next_slot(before)
    assert first.notes[-1].startswith("scheduled for ") and first.notes[-1].endswith(" UTC")
    second = approved(post_of(channel, alice, second_page(article)), alice)
    assert second.scheduled_for == first.scheduled_for + timedelta(days=1), "one a day: the next day's slot"


def test_a_share_waits_after_page_once_its_page_is_live(alice, channel, article):
    with_cadence(channel, {"timezone": "UTC", "slots": ["daily 00:00", "daily 12:00"], "afterPage": "2d"})
    post = approved(post_of(channel, alice, article), alice)
    assert post.scheduled_for >= article.first_published_at + timedelta(days=2)
    assert post.scheduled_for < article.first_published_at + timedelta(days=2, hours=12, minutes=1)


def test_without_a_cadence_approval_leaves_the_post_to_a_person_who_may_choose_a_time(api, alice, channel, article):
    post = approved(post_of(channel, alice, article), alice)
    assert post.scheduled_for is None
    with pytest.raises(Invalid, match="has no cadence"):
        services.schedule(post, alice)
    with pytest.raises(Invalid, match="has passed"):
        services.schedule(post, alice, timezone.now() - timedelta(hours=1))
    at = (timezone.now() + timedelta(days=3)).replace(microsecond=0)
    reply = api(alice).post(f"{API}/posts/{post.public_id}/schedule/", {"at": at.isoformat()}, format="json")
    assert reply.status_code == 200, reply.json()
    assert (reply.json()["scheduled_for"], reply.json()["scheduled_pinned"], reply.json()["scheduled_by"]) == (
        at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        True,
        "alice",
    )
    listed = api(alice).get(f"{API}/posts/", {"scheduled": "true"}).json()["results"]
    assert [p["id"] for p in listed] == [str(post.public_id)]
    off = api(alice).post(f"{API}/posts/{post.public_id}/unschedule/", {}, format="json")
    assert off.status_code == 200 and off.json()["scheduled_for"] is None and off.json()["status"] == "approved"
    assert api(alice).get(f"{API}/posts/", {"scheduled": "true"}).json()["results"] == []


def test_scheduling_is_a_publishing_act_and_only_an_approved_post_is_scheduled(api, alice, carol, channel, article):  # noqa: F811
    post = post_of(channel, alice, article)
    with pytest.raises(Conflict, match="only an approved post"):
        services.schedule(post, alice, timezone.now() + timedelta(days=1))
    post = approved(post, alice)
    refused = api(carol).post(f"{API}/posts/{post.public_id}/schedule/", {}, format="json")
    assert refused.status_code == 403


def test_a_changed_text_a_rejection_or_publish_now_takes_a_post_off_the_schedule(
    api, alice, channel, article, web, worker
):
    with_cadence(channel, DAILY)
    post = approved(post_of(channel, alice, article), alice)
    assert post.scheduled_for is not None
    edited = services.edit(post, alice, commentary="We copy the site to a second disk every night.")
    assert (edited.status, edited.scheduled_for) == ("draft", None) and "text changed" in edited.notes[-1]
    again = approved(edited, alice)
    assert again.scheduled_for is not None, "approving again queues it again"
    rejected = services.reject(again, alice, "not this week")
    assert rejected.scheduled_for is None and rejected.notes[-1] == "taken off the schedule: rejected"
    published(web)
    other = approved(post_of(channel, alice, second_page(article)), alice)
    with override_settings(DISTRIBUTION_ARMED={"linkedin"}):
        went = worker(api(alice).post, f"{API}/posts/{other.public_id}/publish/", {}, format="json")
    assert went.status_code == 202
    other.refresh_from_db()
    assert (other.status, other.scheduled_for) == ("published", None), "Publish now is never held"


# ── the release ─────────────────────────────────────────────────────────────


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_beat_releases_a_due_post_as_its_schedulers_publish_and_nothing_early(alice, channel, article, web, worker):
    route = published(web)
    post = approved(post_of(channel, alice, article), alice)
    at = timezone.now() + timedelta(hours=2)
    services.schedule(post, alice, at)
    assert services.release_due(at - timedelta(minutes=1)) == 0 and route.call_count == 0
    assert worker(services.release_due, at + timedelta(seconds=30)) == 1
    post.refresh_from_db()
    assert (post.status, post.published_by, post.scheduled_for, post.external_id) == (
        "published",
        alice,
        None,
        "urn:li:share:88",
    )
    assert post.notes[-1].startswith("released on schedule (")
    assert route.call_count == 1


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_a_backlog_after_downtime_goes_one_slot_at_a_time_never_in_a_burst(alice, channel, article, web, worker):
    with_cadence(channel, DAILY)
    route = published(web)
    first = approved(post_of(channel, alice, article), alice)
    second = approved(post_of(channel, alice, second_page(article)), alice)
    now = timezone.now()
    # The worker was away: both slots passed while nothing ran.
    DistributionPost.objects.filter(pk=first.pk).update(scheduled_for=now - timedelta(days=2))
    DistributionPost.objects.filter(pk=second.pk).update(scheduled_for=now - timedelta(days=1))
    assert worker(services.release_due) == 1 and route.call_count == 1
    second.refresh_from_db()
    assert second.status == "approved" and second.scheduled_for > now
    assert second.notes[-1].startswith("moved: ") and "(perDay)" in second.notes[-1]


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_times_a_person_chose_are_not_moved_by_the_cadences_rules(alice, channel, article, web, worker):
    with_cadence(channel, DAILY)
    route = published(web)
    at = timezone.now() + timedelta(minutes=5)
    for page in (article, second_page(article)):
        post = approved(post_of(channel, alice, page), alice)
        services.schedule(post, alice, at)
    assert worker(services.release_due, at + timedelta(minutes=1)) == 2 and route.call_count == 2


@override_settings(DISTRIBUTION_ARMED={"linkedin"})
def test_a_post_whose_page_is_not_live_is_held_and_a_refusal_takes_it_off_the_schedule(alice, channel, article, web):
    with_cadence(channel, DAILY)
    post = approved(post_of(channel, alice, article), alice)
    article.unpublish()
    due = post.scheduled_for + timedelta(minutes=1)
    assert services.release_due(due) == 0
    post.refresh_from_db()
    assert post.status == "approved" and post.scheduled_for > due and post.notes[-1].startswith("held: the page")
    held_again = post.scheduled_for + timedelta(minutes=1)
    services.release_due(held_again)
    post.refresh_from_db()
    assert sum(n.startswith("held: the page") for n in post.notes) == 1, "a hold is said once, not every slot"
    article.save_revision().publish()
    Channel.objects.filter(pk=channel.pk).update(armed=False)
    services.release_due(post.scheduled_for + timedelta(minutes=1))
    post.refresh_from_db()
    assert (post.status, post.scheduled_for) == ("approved", None)
    assert "publish_disabled" in post.error and post.notes[-1].startswith("taken off the schedule: the release")
    assert not web.calls


# ── the calendar ────────────────────────────────────────────────────────────


def test_the_channels_calendar_shows_what_waits_the_free_slots_and_what_went(api, alice, channel, article):
    with_cadence(channel, DAILY)
    post = approved(post_of(channel, alice, article), alice)
    data = api(alice).get(f"{API}/channels/{channel.public_id}/calendar/").json()
    assert data["timezone"] == "UTC" and data["problems"] == [] and data["recent"] == []
    assert [p["id"] for p in data["scheduled"]] == [str(post.public_id)]
    assert len(data["free"]) == 12 and data["scheduled"][0]["scheduled_for"] not in data["free"]
    Channel.objects.filter(pk=channel.pk).update(cadence={"slots": ["someday"]})
    broken = api(alice).get(f"{API}/channels/{channel.public_id}/calendar/").json()
    assert broken["summary"] == "" and broken["problems"][0].startswith("cadence.slots[0]")
