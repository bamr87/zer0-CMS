"""The newsroom's tables (TARGET.md § The newsroom, PLAN G15).

A `Desk` is a section of a site with the people who run it; a `Story` is the
planning record behind a page — from a pitch to a published, updated or
corrected article — and the story budget and the editorial calendar are
queries over stories. The editing and copy stages are Wagtail's workflow
machinery (`StageTask`, a task the story's desk approves), so locks, moderation
and the audit log are Wagtail's; the rest of the newsroom workflow is the
story's `status`, moved by `newsroom.services`. `StoryEvent` is a story's
history (assignments, moves, the fast path's reason). `Correction` is the log a
site shows on a page; `Author` and `Byline` are who wrote it. `Front` and
`FrontSlot` curate home and section fronts; `Newsletter`, `Issue` and
`Subscriber` assemble stories into email, and `IssueDelivery` records who has
had an issue.

Every row a client names has a UUID `public_id`; integer keys stay inside.
`visible_to(user, site=None)` is the one place rows are scoped: staff see
everything, everyone else the rows of the sites they edit (`ai.models.sites_for`)
— and the authors of the stories they may see, or of none yet.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from wagtail.models import Task, TaskState
from wagtail.snippets.models import register_snippet

from ai.models import is_staff, sites_for

USER = settings.AUTH_USER_MODEL


def public_id():
    return models.UUIDField(default=uuid.uuid4, unique=True, editable=False)


class SiteScoped(models.QuerySet):
    def visible_to(self, user, site=None):
        """Staff see every row; anyone else the rows of the sites they edit. With `site`, that site's only."""
        if user is None or not user.is_authenticated:
            return self.none()
        rows = self if site is None else self.filter(site=site)
        return rows if is_staff(user) else rows.filter(site__in=sites_for(user))


# ── desks and stories ──────────────────────────────────────────────────────


class Desk(models.Model):
    """A section of a site and the people who run it: its editors assign, edit
    and publish; its copy editors (its editors, when it has none) clear copy.
    Its stories' pages are created under `section`; its writer is an assistant
    or a pipeline of the AI content layer."""

    public_id = public_id()
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80)
    description = models.TextField(blank=True)
    section = models.ForeignKey(
        "wagtailcore.Page", on_delete=models.PROTECT, related_name="+", help_text="Its stories' pages go here."
    )
    editors = models.ManyToManyField(USER, blank=True, related_name="edited_desks")
    copy_editors = models.ManyToManyField(USER, blank=True, related_name="copy_edited_desks")
    assistant = models.ForeignKey(
        "ai.Assistant", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", help_text="Its writer."
    )
    pipeline = models.ForeignKey(
        "ai.Pipeline", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", help_text="Or a pipeline."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SiteScoped.as_manager()

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(fields=["site", "slug"], name="newsroom_one_desk_slug_per_site")]

    def __str__(self):
        return self.name

    def clean(self):
        from cms.models import ArticlePage

        if self.section_id and self.site_id:
            section = self.section.specific
            if not section.path.startswith(self.site.root_page.path):
                raise ValidationError({"section": "the section is a page of the desk's site"})
            if not ArticlePage.can_create_at(section):
                raise ValidationError(
                    {"section": "the section is a page that takes articles (a site root or a collection)"}
                )

    def is_editor(self, user) -> bool:
        return bool(user.is_superuser or self.editors.filter(pk=user.pk).exists())

    def approvers(self, stage: str):
        if stage == Story.Status.COPY and self.copy_editors.exists():
            return self.copy_editors.all()
        return self.editors.all()

    def can_approve(self, user, stage: str) -> bool:
        return bool(user.is_superuser or self.approvers(stage).filter(pk=user.pk).exists())


class StoryQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        return self.filter(desk__in=Desk.objects.visible_to(user, site))


class Story(models.Model):
    """The planning record behind a page: what it is, who writes it, when it
    is due and when it runs, and where it stands in the newsroom workflow."""

    class Status(models.TextChoices):
        PITCH = "pitch", "Pitch"
        ASSIGNED = "assigned", "Assigned"
        DRAFTING = "drafting", "Drafting"
        EDITING = "editing", "Editing"
        COPY = "copy", "Copy"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHED = "published", "Published"
        UPDATED = "updated", "Updated"
        CORRECTED = "corrected", "Corrected"

    class Priority(models.IntegerChoices):
        TOP = 1, "Top"
        HIGH = 2, "High"
        NORMAL = 3, "Normal"
        LOW = 4, "Low"

    public_id = public_id()
    desk = models.ForeignKey(Desk, on_delete=models.CASCADE, related_name="stories")
    slug = models.SlugField(max_length=200)
    headline = models.CharField(max_length=255)
    summary = models.TextField(blank=True, help_text="The pitch: the angle, and why it matters now.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PITCH, db_index=True)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.NORMAL)
    assignee = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    deadline = models.DateTimeField(null=True, blank=True, help_text="When the draft is due.")
    slot_date = models.DateField(null=True, blank=True, db_index=True, help_text="The day it is planned to run.")
    embargo = models.DateTimeField(null=True, blank=True, help_text="It may not go live before this (go_live_at).")
    page = models.OneToOneField(
        "wagtailcore.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="story"
    )
    brief = models.ForeignKey("ai.Brief", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    source = models.JSONField(default=dict, blank=True, help_text="The wire or feed item it was pitched from.")
    breaking = models.BooleanField(default=False, help_text="Published by the fast path, skipping copy.")
    fast_path_reason = models.TextField(blank=True)
    ai = models.JSONField(default=dict, blank=True, help_text="The latest AI run of each kind: {kind: run id}.")
    bylines = models.ManyToManyField("Author", through="Byline", blank=True, related_name="stories")
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = StoryQuerySet.as_manager()

    class Meta:
        ordering = ["priority", "deadline", "-created_at", "id"]
        verbose_name_plural = "stories"
        constraints = [models.UniqueConstraint(fields=["desk", "slug"], name="newsroom_one_story_slug_per_desk")]
        indexes = [models.Index(fields=["desk", "status"]), models.Index(fields=["assignee", "status"])]

    def __str__(self):
        return self.headline

    @property
    def is_published(self) -> bool:
        return self.status in (self.Status.PUBLISHED, self.Status.UPDATED, self.Status.CORRECTED)


class StoryEvent(models.Model):
    """One thing that happened to a story: pitched, assigned (the assignment
    history), moved between stages, published by the fast path (with its
    reason), corrected or updated."""

    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="events")
    created_at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=24)
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12, blank=True)
    assignee = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at", "id"]


class StageTask(Task):
    """A stage of the newsroom workflow in Wagtail's machinery: Editing, then
    Copy. The story's desk approves it — its editors, or for copy its copy
    editors when it has any — and while a page is at a stage only they may
    change it. Reaching a stage moves the story there (`services.reached_stage`)."""

    stage = models.CharField(
        max_length=8, unique=True, choices=[(Story.Status.EDITING, "Editing"), (Story.Status.COPY, "Copy")]
    )

    admin_form_fields = Task.admin_form_fields + ["stage"]

    class Meta:
        verbose_name = "Newsroom stage"

    @classmethod
    def get_description(cls):
        return "The story's desk approves this stage of the newsroom workflow."

    def _approves(self, obj, user) -> bool:
        story = Story.objects.filter(page_id=obj.pk).select_related("desk").first()
        return bool(user.is_superuser or (story is not None and story.desk.can_approve(user, self.stage)))

    def start(self, workflow_state, user=None):
        from .services import reached_stage

        state = super().start(workflow_state, user=user)
        reached_stage(workflow_state.content_object, self.stage, user)
        return state

    def locked_for_user(self, obj, user):
        return not self._approves(obj, user)

    def user_can_access_editor(self, obj, user):
        return self._approves(obj, user)

    def get_actions(self, obj, user):
        return [("reject", "Send back", True), ("approve", "Approve", False)] if self._approves(obj, user) else []

    def get_task_states_user_can_moderate(self, user, **kwargs):
        states = self.task_states.filter(status=TaskState.STATUS_IN_PROGRESS)
        if user.is_superuser:
            return states
        stories = Story.objects.exclude(page=None).filter(
            desk__in=user.edited_desks.all() | user.copy_edited_desks.all()
        )
        pages = [str(s.page_id) for s in stories.select_related("desk") if s.desk.can_approve(user, self.stage)]
        return states.filter(workflow_state__object_id__in=pages)


# ── bylines and corrections ────────────────────────────────────────────────


class AuthorQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        """Staff see every author; anyone else the authors of the stories they may see, and the authors no
        story carries yet (so a desk can byline someone new). With `site`, that site's and the unused."""
        if user is None or not user.is_authenticated:
            return self.none()
        if is_staff(user) and site is None:
            return self
        stories = Story.objects.visible_to(user, site)
        return self.filter(models.Q(stories__in=stories) | models.Q(stories=None)).distinct()


@register_snippet
class Author(models.Model):
    """A byline and its author page: who wrote it. One author may write for several sites; it is
    changed by the desk editors of every site its bylines are on (`services.may_change_author`)."""

    public_id = public_id()
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    bio = models.TextField(blank=True)
    email = models.EmailField(blank=True)
    user = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AuthorQuerySet.as_manager()

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Byline(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="byline_rows")
    author = models.ForeignKey(Author, on_delete=models.PROTECT, related_name="+")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["story", "position", "id"]
        constraints = [models.UniqueConstraint(fields=["story", "author"], name="newsroom_one_byline_per_author")]


class Correction(models.Model):
    """One entry of the corrections and updates log a site shows on a page.
    Kept beside the page, not in its revisions: a revert never loses one."""

    class Kind(models.TextChoices):
        CORRECTION = "correction", "Correction"
        UPDATE = "update", "Update"

    public_id = public_id()
    page = models.ForeignKey("wagtailcore.Page", on_delete=models.CASCADE, related_name="+")
    story = models.ForeignKey(Story, null=True, blank=True, on_delete=models.SET_NULL, related_name="corrections")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["created_at", "id"]


# ── fronts ─────────────────────────────────────────────────────────────────


class Front(models.Model):
    """A home front (no desk) or a section front (a desk's): ordered slots."""

    public_id = public_id()
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE, related_name="+")
    desk = models.ForeignKey(Desk, null=True, blank=True, on_delete=models.SET_NULL, related_name="fronts")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SiteScoped.as_manager()

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(fields=["site", "slug"], name="newsroom_one_front_slug_per_site")]

    def __str__(self):
        return self.name


class FrontSlot(models.Model):
    """A place on a front: a story pinned there, or the next latest published
    story of a desk (any desk on the site, without one)."""

    class Rule(models.TextChoices):
        PINNED = "pinned", "Pinned"
        LATEST = "latest", "Latest"

    front = models.ForeignKey(Front, on_delete=models.CASCADE, related_name="slots")
    position = models.PositiveSmallIntegerField()
    rule = models.CharField(max_length=8, choices=Rule.choices, default=Rule.PINNED)
    story = models.ForeignKey(Story, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    desk = models.ForeignKey(Desk, null=True, blank=True, on_delete=models.CASCADE, related_name="+")

    class Meta:
        ordering = ["front", "position"]
        constraints = [models.UniqueConstraint(fields=["front", "position"], name="newsroom_one_slot_per_position")]


# ── newsletters ────────────────────────────────────────────────────────────


class Newsletter(models.Model):
    public_id = public_id()
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80)
    description = models.TextField(blank=True)
    from_email = models.CharField(max_length=254, blank=True, help_text="Empty: DEFAULT_FROM_EMAIL.")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SiteScoped.as_manager()

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(fields=["site", "slug"], name="newsroom_one_newsletter_slug_per_site")]

    def __str__(self):
        return self.name


class IssueQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        return self.filter(newsletter__in=Newsletter.objects.visible_to(user, site))


class Issue(models.Model):
    """One send of a newsletter: a subject, an introduction and stories, in order."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    public_id = public_id()
    newsletter = models.ForeignKey(Newsletter, on_delete=models.CASCADE, related_name="issues")
    subject = models.CharField(max_length=200)
    intro = models.TextField(blank=True)
    stories = models.ManyToManyField(Story, through="IssueStory", blank=True, related_name="+")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    recipients = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = IssueQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.subject


class IssueStory(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="items")
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="+")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["issue", "position", "id"]


class Subscriber(models.Model):
    """An address on a newsletter's list, confirmed by a link (double opt-in)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"

    public_id = public_id()
    newsletter = models.ForeignKey(Newsletter, on_delete=models.CASCADE, related_name="subscribers")
    email = models.EmailField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmation_sent_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["newsletter", "email"]
        constraints = [models.UniqueConstraint(fields=["newsletter", "email"], name="newsroom_one_subscription")]


class IssueDelivery(models.Model):
    """An issue sent to one subscriber, recorded as each message is accepted: what makes a send that
    failed part way, or a worker that died, resume with the rest instead of mailing everyone again."""

    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="deliveries")
    subscriber = models.ForeignKey(Subscriber, on_delete=models.CASCADE, related_name="+")
    sent_at = models.DateTimeField(default=timezone.now)
    message_id = models.CharField(max_length=255, blank=True, help_text="The ESP's id for the message, if it gave one.")

    class Meta:
        verbose_name_plural = "issue deliveries"
        constraints = [
            models.UniqueConstraint(fields=["issue", "subscriber"], name="newsroom_one_delivery_per_subscriber")
        ]
