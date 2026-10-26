"""The rules the ideas and research tables keep themselves: what a row made
inside a container inherits (`placement`), who changes a site's rows
(`Collaborative`), the database's own constraints (a citation cites from a
page or a brief, a feed item is kept once, a person votes once), and a row's
vector going with it when it is deleted."""

import pytest
from django.db import IntegrityError, transaction
from wagtail.models import Site

from graph.models import Embedding
from ideas import services as ideas
from ideas.models import Board, Idea, Vote
from research import services
from research.models import Citation, Collection, FeedSubscription, Source, placement


@pytest.fixture
def site(site_root):
    return Site.objects.get(root_page=site_root)


@pytest.mark.django_db
def test_a_row_made_inside_a_container_takes_its_place_as_far_as_its_owner_may_hold_it(alice, bob, site):
    team = Collection.objects.create(owner=alice, name="Team", site=site, visibility="site")
    everyone = Collection.objects.create(owner=alice, name="Open", site=site, visibility="shared")
    mine = Collection.objects.create(owner=alice, name="Mine")
    assert placement(alice, team) == {"site": site, "visibility": "site"}
    assert placement(bob, team) == {"site": None, "visibility": "private"}  # bob edits no site: his row stays his
    assert placement(bob, everyone) == {"site": None, "visibility": "shared"}
    assert placement(alice, mine) == {"site": None, "visibility": "private"}
    assert placement(alice, None) == {}


@pytest.mark.django_db
def test_a_sites_rows_are_changed_by_the_people_who_edit_that_site(alice, bob, site):
    from tests.ai.conftest import _person

    carol = _person("carol", editor=True)
    team = Board.objects.create(owner=alice, name="Team", site=site, visibility="site")
    private = Board.objects.create(owner=alice, name="Mine", site=site)
    assert team.can_edit(carol) and not team.can_edit(bob)
    assert private.can_edit(alice) and not private.can_edit(carol)
    assert set(Board.objects.visible_to(carol)) == {team} and set(Board.objects.visible_to(bob)) == set()


@pytest.mark.django_db
def test_the_database_keeps_a_citation_cited_a_feed_item_once_and_a_vote_per_person(alice):
    source = services.add_note(alice, "Back up nightly.")
    with pytest.raises(IntegrityError), transaction.atomic():
        Citation.objects.create(source=source)  # from neither a page nor a brief
    feed = FeedSubscription.objects.create(owner=alice, url="https://example.com/feed.xml")
    Source.objects.create(owner=alice, kind=Source.FEED, feed=feed, guid="a-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        Source.objects.create(owner=alice, kind=Source.FEED, feed=feed, guid="a-1")
    Source.objects.create(owner=alice, kind=Source.FEED, feed=feed, guid="")  # no guid: nothing to keep once
    Source.objects.create(owner=alice, kind=Source.FEED, feed=feed, guid="")
    idea = Idea.objects.create(owner=alice, title="Backups")
    Vote.objects.create(idea=idea, user=alice)
    with pytest.raises(IntegrityError), transaction.atomic():
        Vote.objects.create(idea=idea, user=alice)


@pytest.mark.django_db
def test_a_rows_vector_goes_with_it(alice, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        source = services.add_note(alice, "Back up nightly to a second disk.")
        idea = ideas.capture(alice, "Nightly backups")
    assert Embedding.objects.filter(kind__in=["source", "idea"]).count() == 2
    source.delete()
    idea.delete()
    assert not Embedding.objects.filter(kind__in=["source", "idea"]).exists()
