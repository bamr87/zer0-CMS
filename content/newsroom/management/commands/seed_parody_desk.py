"""`manage.py seed_parody_desk [--editor USERNAME …]`: parodynews as a newsroom.

barodybroject generated parody news with an assistant, reviewed it and
published it to its sidecar site. Here that flow is the newsroom's: this makes
— once, and changes nothing on a second run — the parodynews site (its root and
its posts section, as `import_parodynews` makes them, served at
parodynews.localhost), the **Parody desk** on it whose writer is the parody news
writer the AI layer seeded from barodybroject (its prompt and its parody news
article schema), the newsroom workflow, a home front filled with the desk's
latest stories, and a newsletter. The posts already imported become the desk's
stories (published, or drafting). The editors named are the desk's editors.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from wagtail.models import Site

from ai.models import Assistant
from ai.services import import_bundled, stable_id
from cms.models import ArticlePage
from importers.parodynews import _site as parodynews_posts
from newsroom import services
from newsroom.models import Desk, Front, FrontSlot, Newsletter, Story

WRITER = stable_id("bundled-assistant", "parody-news-writer")


class Command(BaseCommand):
    help = "The Parody desk on the parodynews site, with its front and newsletter (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--editor", action="append", default=[], help="A username to make a desk editor.")

    @transaction.atomic
    def handle(self, *args, editor, **options):
        people = list(get_user_model().objects.filter(username__in=editor))
        if missing := sorted(set(editor) - {p.username for p in people}):
            raise CommandError(f"no such person: {', '.join(missing)}")
        posts = parodynews_posts()
        root = posts.get_parent()
        site = Site.objects.filter(root_page=root).first() or Site.objects.create(
            hostname="parodynews.localhost", port=80, root_page=root, site_name="parodynews"
        )
        writer = Assistant.objects.filter(public_id=WRITER).first()
        if writer is None:
            import_bundled()
            writer = Assistant.objects.get(public_id=WRITER)
        desk, created = Desk.objects.get_or_create(
            site=site,
            slug="parody",
            defaults={
                "name": "Parody desk",
                "description": "Satire that starts dark and ends hopeful — barodybroject's news, run as a desk.",
                "section": posts,
                "assistant": writer,
            },
        )
        desk.editors.add(*people)
        services.workflow()
        front, new_front = Front.objects.get_or_create(site=site, slug="home", defaults={"name": "Home"})
        if new_front:
            FrontSlot.objects.bulk_create(
                FrontSlot(front=front, position=i, rule=FrontSlot.Rule.LATEST, desk=desk) for i in range(5)
            )
        Newsletter.objects.get_or_create(
            site=site,
            slug="parody-weekly",
            defaults={"name": "The Parody Weekly", "description": "The week's parody news, every Friday."},
        )
        adopted = 0
        for page in ArticlePage.objects.child_of(posts).filter(story__isnull=True):
            story = Story.objects.create(
                desk=desk,
                headline=page.title,
                slug=services.unique_slug(desk, page.slug),
                page=page,
                status=Story.Status.PUBLISHED if page.live else Story.Status.DRAFTING,
            )
            services.record(story, None, None, "adopted", note="an imported parodynews post")
            adopted += 1
        self.stdout.write(
            f"parodynews: the Parody desk {'created' if created else 'already there'} at {site.hostname}; "
            f"{adopted} post(s) adopted as stories; {len(people)} editor(s) added"
        )
