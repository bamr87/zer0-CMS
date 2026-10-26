"""The ideas tables (TARGET.md § Ideas and research; PLAN G14).

| Model   | What |
|---------|------|
| `Board` | A named list of ideas; its columns are an idea's statuses |
| `Idea`  | A title, notes, tags and a status; the sources it links to; where it came from (captured, written, brainstormed — the reply it came from) and what it became (a brief, a page: an article or a book) |
| `Vote`  | One person's vote for one idea |

Boards and ideas are owned rows (the AI layer's `Owned`, through research's
`Collaborative`): a UUID public id, owner, site, visibility, `visible_to(user,
site)` — and a board visible to a site is one its editors work on together. An
idea with no board is in its owner's inbox. Vectors for clustering live in
`graph.Embedding` (kind `idea`), never on the row.
"""

from django.conf import settings
from django.db import models
from taggit.managers import TaggableManager

from research.models import Collaborative

USER = settings.AUTH_USER_MODEL


class Board(Collaborative):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Idea(Collaborative):
    NEW, EXPLORING, PLANNED, PROMOTED, ARCHIVED = "new", "exploring", "planned", "promoted", "archived"
    STATUSES = [(s, s) for s in (NEW, EXPLORING, PLANNED, PROMOTED, ARCHIVED)]
    WRITTEN, CAPTURED, BRAINSTORMED = "written", "captured", "brainstormed"
    ORIGINS = [(o, o) for o in (WRITTEN, CAPTURED, BRAINSTORMED)]

    board = models.ForeignKey(Board, null=True, blank=True, on_delete=models.SET_NULL, related_name="ideas")
    title = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    tags = TaggableManager(blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default=NEW, db_index=True)
    origin = models.CharField(max_length=12, choices=ORIGINS, default=WRITTEN)
    url = models.URLField(max_length=2000, blank=True, help_text="Where it was captured from.")
    sources = models.ManyToManyField("research.Source", blank=True, related_name="ideas")
    source_message = models.ForeignKey(
        "ai.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", help_text="Brainstormed in."
    )
    brief = models.ForeignKey("ai.Brief", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    page = models.ForeignKey("wagtailcore.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["board", "status"])]

    def __str__(self):
        return self.title


class Vote(models.Model):
    idea = models.ForeignKey(Idea, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["idea", "user"], name="ideas_one_vote_per_person")]

    def __str__(self):
        return f"{self.user_id} → {self.idea_id}"
