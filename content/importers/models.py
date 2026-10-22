"""`ImportedSource`: the file a page came from, kept beside the page rather
than on it (a revision copies every page field, and this is the whole file).

It is what makes the bridge exact: the exporter writes `source_text` back
verbatim while the page's `content_hash` still equals `import_hash` — an
unchanged page round-trips byte for byte — and the importer skips a file whose
digest has not moved, and refuses to overwrite a page an editor changed in
Wagtail since the last import.

`ImportedRecord` is the same promise for a row that is not a page (the AI
layer's assistants, briefs, conversations …, importers/parodynews_ai.py): a
digest of the fields the import last wrote, so a re-import leaves alone a row a
person changed or deleted here since (`--force` aside).
"""

from django.db import models


class ImportedSource(models.Model):
    page = models.OneToOneField("wagtailcore.Page", on_delete=models.CASCADE, related_name="imported_source")
    site_key = models.SlugField(max_length=80, db_index=True)
    legacy_path = models.CharField(max_length=512)
    source_text = models.TextField()
    source_digest = models.CharField(max_length=64)
    import_hash = models.CharField(max_length=64, help_text="The page's content_hash right after import.")
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["site_key", "legacy_path"], name="one_page_per_source_file")]

    def __str__(self):
        return f"{self.site_key}:{self.legacy_path}"


class ImportedRecord(models.Model):
    source = models.SlugField(max_length=80)
    key = models.CharField(max_length=255, help_text="What the row came from, e.g. `assistant:asst_1`.")
    digest = models.CharField(max_length=64, help_text="sha256 of the row's imported fields as the import left them.")
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "key"], name="one_record_per_source_key")]

    def __str__(self):
        return f"{self.source}:{self.key}"
