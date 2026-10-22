"""The books app has no tables of its own: a book is a `cms.BookPage` with its
`cms.ChapterPage`s (their manuscript fields are in cms/models.py), the file it
was read from is an `importers.ImportedSource`, its AI setup is `ai.Assistant`,
`ai.OutputSchema` and `ai.Pipeline` rows, and its memory is `agents.Memory`.
This module exists so Django sends the app `post_migrate` (books/apps.py)."""
