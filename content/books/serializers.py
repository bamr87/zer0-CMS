"""The shapes `/api/v2/books/` reads and returns (books/views.py), named once
so the OpenAPI document and the studio's generated client follow them. A
book's editable fields — its manifest, outline, notes and style guide — and a
chapter's are the generic page endpoints' (`/api/v2/content/pages/<id>/`)."""

from rest_framework import serializers

from ai.serializers import RunRefSerializer
from api.serializers import PAGE_STATUSES

from .context import TASKS
from .library import ERROR, WARNING

ISSUE_LEVELS = [(ERROR, "error"), (WARNING, "warning")]
TASK_CHOICES = [(t.key, t.label) for t in TASKS.values()]


class BookSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="The book's page id.")
    slug = serializers.CharField(help_text="Its directory in the library.")
    title = serializers.CharField()
    status = serializers.CharField(help_text="idea, outlining, drafting, revising, complete or archived.")
    page_status = serializers.ChoiceField(choices=PAGE_STATUSES, help_text="Where the book's page stands.")
    profile = serializers.CharField(help_text="book, abc or story.")
    logline = serializers.CharField(allow_blank=True)
    genre = serializers.CharField(allow_blank=True)
    chapters = serializers.IntegerField()
    planned_chapters = serializers.IntegerField()
    word_count = serializers.IntegerField(help_text="Narrative prose only: the outline scaffolding is not counted.")
    target_word_count = serializers.IntegerField()
    progress = serializers.FloatField(help_text="0–1: words against the target, else chapters against the plan.")
    site_id = serializers.IntegerField(allow_null=True)
    template = serializers.BooleanField(help_text="A template new books start from, not on the shelf.")


class ChapterBriefSerializer(serializers.Serializer):
    number = serializers.IntegerField(allow_null=True)
    title = serializers.CharField()
    word_count = serializers.IntegerField()


class BookStatsSerializer(serializers.Serializer):
    chapters = serializers.IntegerField()
    status_counts = serializers.DictField(child=serializers.IntegerField(), help_text="Chapters per status.")
    word_count = serializers.IntegerField()
    target_word_count = serializers.IntegerField()
    planned_chapters = serializers.IntegerField()
    average = serializers.IntegerField(help_text="Words per chapter.")
    longest = ChapterBriefSerializer(allow_null=True)
    shortest = ChapterBriefSerializer(allow_null=True)
    progress = serializers.FloatField()


class BookChapterSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True, help_text="The chapter's page id.")
    number = serializers.IntegerField(allow_null=True)
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_blank=True)
    act = serializers.IntegerField(allow_null=True)
    status = serializers.CharField(help_text="stub, outline, draft, revised or final.")
    pov = serializers.CharField(allow_blank=True)
    word_count = serializers.IntegerField()
    path = serializers.CharField(help_text="Its file, relative to the library.")
    errors = serializers.IntegerField()
    warnings = serializers.IntegerField()


class BookDetailSerializer(BookSummarySerializer):
    stats = BookStatsSerializer()
    chapter_list = BookChapterSerializer(many=True, help_text="In reading order.")
    errors = serializers.IntegerField()
    warnings = serializers.IntegerField()
    documents = serializers.ListField(child=serializers.CharField(), help_text="Its files besides the chapters.")
    can_edit = serializers.BooleanField()
    can_add_chapter = serializers.BooleanField()


class IssueSerializer(serializers.Serializer):
    level = serializers.ChoiceField(choices=ISSUE_LEVELS)
    code = serializers.CharField(help_text="The validation code (the books package's docs/SCHEMA.md).")
    message = serializers.CharField()
    path = serializers.CharField(help_text="The file, relative to the library.")
    line = serializers.IntegerField(allow_null=True)


class BookTaskSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=TASK_CHOICES)
    label = serializers.CharField()
    description = serializers.CharField()
    chapter = serializers.BooleanField(help_text="Works on a chapter (else on the book).")
    suggests = serializers.BooleanField(help_text="Its result arrives as suggestions on the chapter.")


class NewBookSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    slug = serializers.SlugField(required=False, allow_blank=True, help_text="Its directory; else from the title.")
    logline = serializers.CharField(required=False, allow_blank=True)
    genre = serializers.CharField(required=False, allow_blank=True)


class NewChapterSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    number = serializers.IntegerField(required=False, min_value=1, help_text="Else the next one.")
    act = serializers.IntegerField(required=False, min_value=1, help_text="Else spread over the acts.")


class AssistSerializer(serializers.Serializer):
    task = serializers.ChoiceField(choices=TASK_CHOICES)
    chapter = serializers.IntegerField(required=False, help_text="The chapter's page id (every task but outline).")
    instruction = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    selection = serializers.CharField(
        required=False, allow_blank=True, max_length=20000, help_text="For revise: the passage."
    )
    assistant = serializers.UUIDField(required=False, help_text="An assistant of yours; else the task's bundled one.")


class PremiseSerializer(serializers.Serializer):
    premise = serializers.CharField(max_length=8000, help_text="One or two sentences: premise, protagonist or theme.")
    assistant = serializers.UUIDField(required=False, help_text="An outliner of yours; else the bundled one.")


class OutlineBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="public_id", help_text="Follow it on /api/v2/ai/briefs/<id>/.")
    status = serializers.CharField()


class PremiseAcceptedSerializer(serializers.Serializer):
    brief = OutlineBriefSerializer()
    run = RunRefSerializer()


class DocumentSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="Inside the book, e.g. guides/act-1-chapters-01-05.md.")
    text = serializers.CharField(allow_blank=True, trim_whitespace=False)


class BookDocumentsSerializer(serializers.Serializer):
    revision = serializers.IntegerField(allow_null=True, help_text="The revision they are from: send it back to save.")
    documents = DocumentSerializer(many=True)


class SetDocumentSerializer(serializers.Serializer):
    base_revision_id = serializers.IntegerField(allow_null=True, help_text="The revision edited; a newer one is a 409.")
    path = serializers.CharField(max_length=500)
    text = serializers.CharField(
        allow_blank=True, allow_null=True, trim_whitespace=False, help_text="The file's text; null removes it."
    )


class ManuscriptSerializer(serializers.Serializer):
    filename = serializers.CharField()
    markdown = serializers.CharField(help_text="The compiled manuscript: title page, acts, chapters, no scaffolding.")
    word_count = serializers.IntegerField()


class ContextSerializer(serializers.Serializer):
    text = serializers.CharField(help_text="The request a task's model would be given, without calling it.")
