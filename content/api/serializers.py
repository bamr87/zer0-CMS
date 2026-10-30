"""The REST shapes of the studio's endpoints (api/session.py, api/pages.py,
api/review.py) and of the agent-run endpoints the studio reads.

These serializers are the contract: drf-spectacular writes them into
`schemas/openapi/openapi.json`, and `web/packages/api` generates the studio's
typed client from that file. The views build plain values and pass them
through these to shape and render them; input serializers validate a request
before a service sees it. Values that depend on a page's type travel as one
`fields` object, described per type by `FieldSpec`, so a client renders any
page type without knowing the types in advance.
"""

from rest_framework import serializers

# The enums, named in the document by SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"].
GROUPS = ("content", "seo", "settings", "file")
KINDS = ("text", "textarea", "datetime", "integer", "choice", "multichoice", "tags", "json", "boolean")
PAGE_STATUSES = ("draft", "live", "changed", "scheduled", "expired")
CHANGE_KINDS = ("block", "field", "edge")
TARGET_TYPES = ("page", "image")


# ── people and sessions ────────────────────────────────────────────────────


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    name = serializers.CharField(source="get_full_name")
    email = serializers.CharField()
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()


class MeSerializer(serializers.Serializer):
    authenticated = serializers.BooleanField()
    user = UserSerializer(allow_null=True)
    permissions = serializers.ListField(child=serializers.CharField(), help_text="`app_label.codename`, sorted.")
    csrf_token = serializers.CharField(help_text="Send it as `X-CSRFToken` on every unsafe request.")


# ── sites and pages ────────────────────────────────────────────────────────


class PageRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


class PageSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(help_text="The latest revision's title.")
    slug = serializers.CharField()
    type = serializers.CharField(help_text="The page model, e.g. `cms.ArticlePage`.")
    type_label = serializers.CharField()
    status = serializers.ChoiceField(PAGE_STATUSES)
    live = serializers.BooleanField()
    has_unpublished_changes = serializers.BooleanField()
    locked = serializers.BooleanField()
    url_path = serializers.CharField()
    depth = serializers.IntegerField()
    children = serializers.IntegerField(help_text="How many pages sit directly under it.")
    go_live_at = serializers.DateTimeField(allow_null=True)
    latest_revision_created_at = serializers.DateTimeField(allow_null=True)
    last_published_at = serializers.DateTimeField(allow_null=True)


class ChoiceSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class FieldSpecSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()
    group = serializers.ChoiceField(GROUPS)
    kind = serializers.ChoiceField(KINDS)
    required = serializers.BooleanField()
    help_text = serializers.CharField(allow_blank=True)
    max_length = serializers.IntegerField(allow_null=True)
    choices = ChoiceSerializer(many=True)


class BlockSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, help_text="Absent on a block that is new in this request.")
    type = serializers.CharField()
    value = serializers.JSONField()


class PagePermissionsSerializer(serializers.Serializer):
    edit = serializers.BooleanField()
    publish = serializers.BooleanField()
    unpublish = serializers.BooleanField()
    add_subpage = serializers.BooleanField()
    delete = serializers.BooleanField()


class RevisionRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    user = serializers.CharField(allow_null=True)


class PageDetailSerializer(PageSummarySerializer):
    parent = PageRefSerializer(allow_null=True)
    site_id = serializers.IntegerField(allow_null=True)
    expire_at = serializers.DateTimeField(allow_null=True)
    first_published_at = serializers.DateTimeField(allow_null=True)
    latest_revision = RevisionRefSerializer(allow_null=True)
    live_revision_id = serializers.IntegerField(allow_null=True)
    fields = serializers.DictField(child=serializers.JSONField(allow_null=True))
    field_specs = FieldSpecSerializer(many=True)
    body = BlockSerializer(many=True)
    markdown = serializers.CharField(allow_blank=True, help_text="The body as Markdown, as the exporter writes it.")
    permissions = PagePermissionsSerializer()
    lock = serializers.CharField(
        allow_null=True,
        help_text="Why the caller cannot change the page now — a Wagtail lock: another person's, a workflow "
        "task's, or a scheduled publish's (cancelling the schedule lifts it) — or null.",
    )
    pending_suggestions = serializers.IntegerField()
    preview_url = serializers.CharField(help_text="The latest revision rendered by the platform.")
    live_url = serializers.CharField(allow_null=True)


FIELDS_HELP = (
    "The type's editable fields by name, as `field_specs` describes them. A page that is a file of its own "
    "(`cms.ArticlePage`, `cms.StandardPage`) also takes `file_path` — its file, relative to the site's root, e.g. "
    "`pages/_posts/wire/2026-10-28-example.md` — and `front_matter`, the file's other front-matter keys as a JSON "
    "object in order, e.g. `excerpt`, `permalink`, `sources`; a key a typed field writes is refused (422)."
)


class PageCreateSerializer(serializers.Serializer):
    parent = serializers.IntegerField()
    type = serializers.CharField(help_text="One of the parent's creatable types, e.g. `cms.ArticlePage`.")
    fields = serializers.DictField(child=serializers.JSONField(allow_null=True), help_text=FIELDS_HELP)
    body = BlockSerializer(many=True, required=False)


class PageUpdateSerializer(serializers.Serializer):
    base_revision_id = serializers.IntegerField(
        allow_null=True,
        help_text="The revision edited (null only for a page without one); a newer one makes the save a 409.",
    )
    fields = serializers.DictField(
        child=serializers.JSONField(allow_null=True), required=False, help_text=f"Only what changed. {FIELDS_HELP}"
    )
    body = BlockSerializer(many=True, required=False)


class ScheduleSerializer(serializers.Serializer):
    go_live_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="When the latest revision goes live; leave it out to publish now."
    )
    expire_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="When the page comes down again. Give one of the two, or both."
    )


class PageTypeSerializer(serializers.Serializer):
    type = serializers.CharField()
    label = serializers.CharField()


class RevisionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    user = serializers.CharField(allow_null=True)
    approved_go_live_at = serializers.DateTimeField(allow_null=True)
    is_live = serializers.BooleanField()
    is_latest = serializers.BooleanField()


class RevisionSnapshotSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    user = serializers.CharField(allow_null=True)
    fields = serializers.DictField(child=serializers.JSONField(allow_null=True))
    body = BlockSerializer(many=True)
    markdown = serializers.CharField(allow_blank=True)


class RevisionCompareSerializer(serializers.Serializer):
    a = RevisionSnapshotSerializer()
    b = RevisionSnapshotSerializer()
    changed = serializers.ListField(child=serializers.CharField(), help_text="Field names that differ, and `body`.")


# ── suggestions and runs ───────────────────────────────────────────────────


class ChangeSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(CHANGE_KINDS)
    label = serializers.CharField()
    before = serializers.CharField(allow_blank=True)
    after = serializers.CharField(allow_blank=True)
    stale = serializers.BooleanField(help_text="The block it aims at is gone; accepting it would be refused.")


class TargetSerializer(serializers.Serializer):
    type = serializers.ChoiceField(TARGET_TYPES)
    id = serializers.IntegerField()
    title = serializers.CharField()


class SuggestionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    op = serializers.CharField()
    block_id = serializers.CharField(allow_blank=True)
    field = serializers.CharField(allow_blank=True)
    payload = serializers.JSONField()
    rationale = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    agent = serializers.CharField(allow_null=True)
    run_id = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()
    target = TargetSerializer()
    change = ChangeSerializer()


class AcceptRunSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        help_text="The run's pending suggestions the caller saw and accepts — only these, never the rest of the run.",
    )


class AcceptedRunSerializer(serializers.Serializer):
    accepted = serializers.ListField(child=serializers.IntegerField())
    revision_ids = serializers.ListField(child=serializers.IntegerField())


class StepSerializer(serializers.Serializer):
    idx = serializers.IntegerField()
    kind = serializers.CharField()
    name = serializers.CharField()
    args = serializers.JSONField()
    result = serializers.JSONField()
    error = serializers.CharField(allow_blank=True)
    latency_ms = serializers.IntegerField()
    tokens = serializers.IntegerField()


class RunTargetSerializer(serializers.Serializer):
    type = serializers.CharField(allow_null=True)
    id = serializers.IntegerField(allow_null=True)


class RunLinksSerializer(serializers.Serializer):
    """Where to follow a run: the AI layer's `202` answers and the runs API share this shape."""

    self = serializers.CharField(help_text="The run with its steps.")
    stream = serializers.CharField(help_text="Its steps and final status as server-sent events.")


class RunSerializer(serializers.Serializer):
    """What `api.views.run_json` returns; `steps` only on a single run."""

    id = serializers.IntegerField()
    agent = serializers.CharField()
    status = serializers.CharField()
    is_final = serializers.BooleanField(help_text="It has finished (succeeded, failed, refused or cancelled).")
    trigger = serializers.CharField()
    target = RunTargetSerializer()
    input = serializers.JSONField()
    output = serializers.JSONField()
    error = serializers.CharField(allow_blank=True)
    cost_usd = serializers.CharField()
    tokens = serializers.IntegerField()
    trace_id = serializers.CharField(allow_blank=True)
    schema_version = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    links = RunLinksSerializer()
    steps = StepSerializer(many=True, required=False)


class RunListSerializer(serializers.Serializer):
    results = RunSerializer(many=True)
