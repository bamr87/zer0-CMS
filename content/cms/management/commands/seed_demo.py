"""`manage.py seed_demo`: a small demo site to open the studio on.

Creates, once, a site (`demo`, served at demo.localhost) with a section, a
published article and a draft, reviewed by the "Editorial" workflow (the
brand agent, then a moderator: `manage.py seed_editorial`), and a person to
sign in as (`editor`, in Wagtail's Editors and Moderators groups, so they may
edit and publish). Every
run then makes sure the published article has a finished SEO-agent run with
pending suggestions, so the review inbox is never empty. Local development and
the browser scenarios (verify/scenarios/studio-*.yml) start from it.

Nothing here reaches a network or a model: the suggestions are written the
way an agent's tool writes them (`suggestions.services.propose`, as the agent
user, through the brand guard). The person's password defaults to a known
demo value only under DEBUG; anywhere else it must be given.

    python manage.py seed_demo [--username editor] [--password …]
"""

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from wagtail.models import Page, Site

from agents.models import AgentDefinition, AgentRun, AgentStep
from cms.models import ArticlePage, CollectionPage, SiteRootPage
from cms.services import publish, save_draft
from suggestions.models import Suggestion
from suggestions.services import propose
from workflow.services import assign, editorial

DEMO_PASSWORD = "zer0-demo"
WELCOME_BODY = [
    {"type": "heading", "value": {"level": "2", "text": "What the studio is for"}},
    {
        "type": "markdown",
        "value": "Write a page, ask an agent for help, review what it suggests, and publish when it reads well.",
    },
]
DRAFT_BODY = [
    {"type": "markdown", "value": "We copy the site to a second disk every night, and keep a week of copies."},
]


class Command(BaseCommand):
    help = "A demo site, a person to sign in as, and pending suggestions to review (for development)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="editor")
        parser.add_argument("--password", default=None, help="Required outside DEBUG.")

    def handle(self, *args, username, password, **options):
        if password is None:
            if not settings.DEBUG:
                raise CommandError("outside DEBUG, give the demo person a password: --password …")
            password = DEMO_PASSWORD
        if not AgentDefinition.objects.filter(slug="seo", live=True).exists():
            call_command("sync_agents", "--publish", verbosity=0)
        with transaction.atomic():
            editor = self.person(username, password)
            article = self.site(editor)
            assign(editorial(), SiteRootPage.objects.get(site_key="demo"))
            created = self.suggestions(article, editor)
        self.stdout.write(f"demo site ready: sign in as {username!r}; {created} new suggestion(s) on {article.title!r}")

    def person(self, username, password):
        user, _ = get_user_model().objects.get_or_create(
            username=username,
            defaults={"first_name": "Demo", "last_name": "Editor", "email": f"{username}@example.com"},
        )
        user.is_staff = True
        user.set_password(password)
        user.save()
        user.groups.add(*Group.objects.filter(name__in=["Editors", "Moderators"]))
        # The demo person's address counts as verified, so they sign in at once wherever verification is mandatory.
        EmailAddress.objects.update_or_create(user=user, email=user.email, defaults={"verified": True, "primary": True})
        return user

    def site(self, editor) -> ArticlePage:
        root = SiteRootPage.objects.filter(site_key="demo").first()
        if root is None:
            root = SiteRootPage(title="Demo site", slug="demo", site_key="demo")
            Page.get_first_root_node().add_child(instance=root)
            publish(root, editor)
            Site.objects.get_or_create(
                hostname="demo.localhost", port=80, defaults={"root_page": root, "site_name": "Demo site"}
            )
            posts = CollectionPage(title="Posts", slug="posts", collection="posts", output_dir="_posts")
            root.add_child(instance=posts)
            publish(posts, editor)
            welcome = ArticlePage(
                title="Welcome to the studio",
                slug="welcome",
                author="Demo Editor",
                date=timezone.now(),
                search_description="How a page travels from a draft to the site.",
                body=WELCOME_BODY,
            )
            posts.add_child(instance=welcome)
            publish(welcome, editor)
            draft = ArticlePage(title="Nightly backups", slug="nightly-backups", live=False, body=DRAFT_BODY)
            posts.add_child(instance=draft)
            save_draft(draft, editor)
        return ArticlePage.objects.descendant_of(root).get(slug="welcome")

    def suggestions(self, article, editor) -> int:
        if Suggestion.objects.filter(target_id=article.pk, status=Suggestion.PENDING).exists():
            return 0
        agent = AgentDefinition.objects.get(slug="seo")
        agent_user = get_user_model().objects.get(username=agent.username)
        run = AgentRun.objects.create(
            agent=agent,
            trigger="manual",
            target=article,
            input={"page_id": article.pk},
            started_by=editor,
            started_at=timezone.now(),
        )
        latest = article.get_latest_revision_as_object()
        made = [
            propose(
                target=article,
                op=Suggestion.META,
                field="seo_title",
                user=agent_user,
                run=run,
                payload={"value": "Welcome to the studio: write, review and publish"},
                rationale="Says what a person does here, in the words they would search for.",
            ),
            propose(
                target=article,
                op=Suggestion.REPLACE,
                block_id=latest.body[1].id,
                user=agent_user,
                run=run,
                payload={
                    "type": "markdown",
                    "value": "Write a page, ask an agent for help, and review each change it suggests "
                    "before anything is published.",
                },
                rationale="Puts the review step before publishing, where it happens.",
            ),
        ]
        for idx, s in enumerate(made):
            AgentStep.objects.create(
                run=run,
                idx=idx,
                kind=AgentStep.TOOL,
                name="content.propose_edit",
                args={"op": s.op, "field": s.field, "block_id": s.block_id},
                result={"suggestion_id": str(s.public_id)},
                latency_ms=40,
            )
        run.finish(AgentRun.SUCCEEDED, output={"note": "Two suggestions: a search title and a clearer opening."})
        run.save()
        return len(made)
