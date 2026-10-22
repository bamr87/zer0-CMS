"""`LibraryFile`: what the platform last read from, or wrote to, each file of a
library directory — the record that lets `import_books` and `export_books`
tell each other's changes apart (books/files.py, ADR 0006 decision 13).

A book is a `cms.BookPage` with its `cms.ChapterPage`s (their manuscript fields
are in cms/models.py), the text a page renders over is the
`importers.ImportedSource` it was read from, and its AI setup is `ai.Assistant`,
`ai.OutputSchema` and `ai.Pipeline` rows. What this app adds is one row per
file per directory: its digest, the page whose content it is, and that page's
content hash at that moment. A file whose bytes still have the digest is the
platform's own; one that does not was changed by hand since. The page is kept
as SET_NULL, so a page deleted here leaves its files' rows behind: the export
removes those files, and the import does not bring the page back.

Rows are per directory (as the repository names it when it is inside it), so
exporting to a scratch directory never makes the library's own files look
changed by hand.
"""

from django.db import models


class LibraryFile(models.Model):
    site_key = models.SlugField(max_length=80, help_text="The library's site key (BOOKS_SITE_KEY).")
    directory = models.CharField(
        max_length=512, help_text="The library directory, relative to the repository when it is inside it."
    )
    path = models.CharField(max_length=512, help_text="The file inside the library: <book>/<file>.")
    page = models.ForeignKey(
        "wagtailcore.Page",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="The page whose content the file is; empty once that page is deleted here.",
    )
    digest = models.CharField(max_length=64, help_text="sha256 of the file as the platform last read or wrote it.")
    page_hash = models.CharField(max_length=64, blank=True, help_text="The page's content hash at that moment.")
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site_key", "directory", "path"], name="one_record_per_library_file")
        ]

    def __str__(self):
        return f"{self.site_key}:{self.directory}/{self.path}"
