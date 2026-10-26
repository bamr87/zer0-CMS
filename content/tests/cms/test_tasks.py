"""Scheduled publishing on beat (cms/tasks.py): one object per transaction, so
one that fails never holds back the rest, and a sweep never runs twice at once."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from wagtail.models import Page, Revision

from cms import services
from cms.models import ArticlePage
from cms.tasks import LOCK, publish_scheduled
from tests.conftest import make_article


def scheduled(parent, title, editor):
    page = make_article(parent, title, publish=False)
    services.schedule(page, editor, timezone.now() + timedelta(hours=1))
    past = timezone.now() - timedelta(minutes=1)  # the clock reaches go_live_at
    revision = Revision.page_revisions.get(object_id=str(page.pk), approved_go_live_at__isnull=False)
    revision.content["go_live_at"] = past.isoformat()
    revision.approved_go_live_at = past
    revision.save(update_fields=["content", "approved_go_live_at"])
    return page


@pytest.mark.django_db
def test_one_failing_publish_holds_back_neither_the_others_nor_the_expiries(site_root, editor, monkeypatch):
    broken, fine = scheduled(site_root, "Broken", editor), scheduled(site_root, "Fine", editor)
    expiring = make_article(site_root, "Expiring")
    Page.objects.filter(pk=expiring.pk).update(expire_at=timezone.now() - timedelta(minutes=1))
    publish = Revision.publish

    def failing(self, *args, **kwargs):
        if self.object_id == str(broken.pk):
            raise RuntimeError("a sibling took the slug since it was scheduled")
        return publish(self, *args, **kwargs)

    monkeypatch.setattr(Revision, "publish", failing)
    publish_scheduled()
    assert ArticlePage.objects.get(pk=fine.pk).live and not ArticlePage.objects.get(pk=expiring.pk).live
    assert not ArticlePage.objects.get(pk=broken.pk).live
    assert Revision.page_revisions.filter(object_id=str(broken.pk), approved_go_live_at__isnull=False).exists()
    monkeypatch.setattr(Revision, "publish", publish)
    publish_scheduled()  # the next sweep retries it
    assert ArticlePage.objects.get(pk=broken.pk).live


@pytest.mark.django_db
def test_a_sweep_still_running_is_not_run_twice(site_root, editor):
    page = scheduled(site_root, "Due", editor)
    cache.add(LOCK, True)  # another worker is mid-sweep
    publish_scheduled()
    assert not ArticlePage.objects.get(pk=page.pk).live
    cache.delete(LOCK)
    publish_scheduled()
    assert ArticlePage.objects.get(pk=page.pk).live and cache.get(LOCK) is None
