"""`Suggestion` and `BlockProvenance`.

A suggestion is one proposed change to one page (or image): insert a block
after another, replace or delete a block by its id, set a meta field, or add
a graph edge. It records the revision it was proposed against, the run and
the agent that proposed it, and — once an editor decides — who decided and
when. The accept rate an agent is promoted on is computed from these rows.

`BlockProvenance` is the sidecar the note describes: for every block an
accepted suggestion wrote, which run, model and prompt version produced it
and who accepted it. Block ids are stable across revisions, so a block keeps
its provenance until it is changed again.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Suggestion(models.Model):
    INSERT, REPLACE, DELETE, META, EDGE = "insert", "replace", "delete", "meta", "edge"
    OPS = [(o, o) for o in (INSERT, REPLACE, DELETE, META, EDGE)]
    PENDING, ACCEPTED, REJECTED, SUPERSEDED, FAILED = "pending", "accepted", "rejected", "superseded", "failed"
    STATUSES = [(s, s) for s in (PENDING, ACCEPTED, REJECTED, SUPERSEDED, FAILED)]

    target_ct = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    target_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("target_ct", "target_id")
    op = models.CharField(max_length=8, choices=OPS)
    block_id = models.CharField(max_length=64, blank=True, help_text="The block replaced, deleted, or inserted after.")
    field = models.CharField(max_length=64, blank=True, help_text="For op=meta: the field set.")
    payload = models.JSONField(
        default=dict, blank=True, help_text="{type, value} for blocks, {value} for meta, the edge for edges."
    )
    rationale = models.TextField(blank=True)
    run = models.ForeignKey(
        "agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="suggestions"
    )
    agent = models.ForeignKey(
        "agents.AgentDefinition", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    base_revision = models.ForeignKey(
        "wagtailcore.Revision", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=12, choices=STATUSES, default=PENDING, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    applied_revision = models.ForeignKey(
        "wagtailcore.Revision", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    error = models.TextField(blank=True)
    legacy_ref = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["target_ct", "target_id", "status"])]

    def __str__(self):
        return f"{self.op} on {self.target_ct.model}:{self.target_id} ({self.status})"


class BlockProvenance(models.Model):
    page_revision = models.ForeignKey("wagtailcore.Revision", on_delete=models.CASCADE, related_name="+")
    block_id = models.CharField(max_length=64, db_index=True)
    suggestion = models.ForeignKey(Suggestion, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    run = models.ForeignKey("agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    model = models.CharField(max_length=120, blank=True)
    prompt_version = models.CharField(max_length=12, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.block_id} ← run {self.run_id}"


def target_content_type(obj) -> ContentType:
    return ContentType.objects.get_for_model(obj, for_concrete_model=False)
