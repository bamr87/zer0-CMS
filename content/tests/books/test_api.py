"""`/api/v2/books/` (books/views.py): the studio's Books area over REST — the
library's shelf, a book's overview, new books and chapters, its other files,
validation, the manuscript, what a task's model reads, running a task (202,
idempotent) and a book from a premise — for people with the page rights, and a
404 for anyone else, or for a book that is not the library's."""

import json
from pathlib import Path

import pytest
from django.conf import settings

from agents.models import AgentRun
from agents.principals import ensure_principal
from ai.models import Brief
from books import services
from cms.models import BookPage, ChapterPage
from importers.jekyll import import_site

from .test_ai import DETAIL, OUTLINE


@pytest.mark.django_db
def test_the_shelf_lists_the_books_a_person_may_open(sample, api, alice, bob):
    shelf = api(alice).get("/api/v2/books/")
    assert shelf.status_code == 200
    [row] = shelf.json()
    assert (row["slug"], row["title"], row["status"], row["chapters"], row["planned_chapters"]) == (
        "sample",
        "A Sample Book",
        "drafting",
        2,
        4,
    )
    assert row["word_count"] > 0 and 0 < row["progress"] < 1 and row["template"] is False
    templates = api(alice).get("/api/v2/books/?templates=true").json()
    assert [t["slug"] for t in templates] == ["_template"]
    assert api(bob).get("/api/v2/books/").json() == []
    assert api(bob).get(f"/api/v2/books/{sample.pk}/").status_code == 404
    assert api().get("/api/v2/books/").status_code in (401, 403)
    agent = ensure_principal("books")
    assert api(agent).get("/api/v2/books/").status_code == 403  # agents use the tool registry


@pytest.mark.django_db
def test_a_books_overview_issues_manuscript_and_context(sample, api, alice):
    detail = api(alice).get(f"/api/v2/books/{sample.pk}/").json()
    assert [(c["number"], c["title"], c["status"]) for c in detail["chapter_list"]] == [
        (1, "Chapter 1", "draft"),
        (2, "Chapter 2", "draft"),
    ]
    assert detail["chapter_list"][0]["id"] == ChapterPage.objects.child_of(sample).get(number=1).pk
    assert detail["stats"]["status_counts"] == {"draft": 2} and detail["errors"] == 0
    assert "guides/act-1-chapters-01-02.md" in detail["documents"] and detail["can_add_chapter"] is True
    assert api(alice).get(f"/api/v2/books/{sample.pk}/issues/").json() == []  # a clean book
    api(alice).post(f"/api/v2/books/{sample.pk}/chapters/", {"title": "Later"}, format="json")
    issues = api(alice).get(f"/api/v2/books/{sample.pk}/issues/").json()
    assert {"level": "warning", "code": "nav-missing", "message": "no link to the next chapter"} in [
        {k: i[k] for k in ("level", "code", "message")} for i in issues
    ]
    assert any(i["path"] == "sample/chapters/ch03.md" and i["code"] == "chapter-missing-key" for i in issues)
    manuscript = api(alice).get(f"/api/v2/books/{sample.pk}/manuscript/").json()
    assert manuscript["filename"] == "sample-manuscript.md"
    assert manuscript["markdown"].startswith("# A Sample Book\n\nSomeone wants something and cannot have it.\n\n---")
    assert "## Act I\n\n### 1. Chapter 1\n\n*A subtitle*" in manuscript["markdown"]
    with_outline = api(alice).get(f"/api/v2/books/{sample.pk}/manuscript/?include_outline=true").json()
    assert "## Outline\n\n# A Sample Book\n\nAn outline." in with_outline["markdown"]
    first = ChapterPage.objects.child_of(sample).get(number=1)
    text = api(alice).get(f"/api/v2/books/{sample.pk}/context/?chapter={first.pk}&task=check").json()["text"]
    assert "# The chapter you are working on\n\nNumber: 1" in text and "Report facts, not taste." in text
    tasks = {t["key"]: t for t in api(alice).get("/api/v2/books/tasks/").json()}
    assert set(tasks) == {"draft", "continue", "revise", "check", "critique", "outline"}
    assert tasks["draft"]["suggests"] and not tasks["check"]["suggests"] and not tasks["outline"]["chapter"]


@pytest.mark.django_db
def test_new_books_and_chapters_are_drafts(sample, api, alice, bob):
    created = api(alice).post(
        "/api/v2/books/", {"title": "The Quiet Part", "logline": "A speechwriter tells."}, format="json"
    )
    assert created.status_code == 201, created.json()
    book = BookPage.objects.get(pk=created.json()["id"])
    assert (created.json()["slug"], created.json()["status"], book.live) == ("the-quiet-part", "idea", False)
    assert book.get_latest_revision_as_object().outline == "# The Quiet Part\n\nOutline for the-quiet-part.\n"
    again = api(alice).post("/api/v2/books/", {"title": "The Quiet Part"}, format="json")
    assert again.status_code == 422  # the slug is taken
    chapter = api(alice).post(f"/api/v2/books/{book.pk}/chapters/", {"title": "Opening Remarks"}, format="json")
    assert chapter.status_code == 201 and chapter.json()["chapter_list"][0]["title"] == "Opening Remarks"
    assert api(bob).post(f"/api/v2/books/{book.pk}/chapters/", {"title": "x"}, format="json").status_code == 404
    duplicate = api(alice).post(f"/api/v2/books/{book.pk}/chapters/", {"title": "x", "number": 1}, format="json")
    assert duplicate.status_code == 422


@pytest.mark.django_db
def test_a_task_is_a_202_with_its_run_and_a_key_replays_it(sample, api, alice, fake):
    fake.script.append({"text": "Ana sat."})
    first = ChapterPage.objects.child_of(sample).get(number=1)
    body = {"task": "draft", "chapter": first.pk}
    response = api(alice).post(f"/api/v2/books/{sample.pk}/assist/", body, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert response.status_code == 202
    run = AgentRun.objects.get(pk=response.json()["run"]["id"])
    assert run.agent.slug == "books" and response.json()["run"]["links"]["stream"].endswith("/stream/")
    replay = api(alice).post(f"/api/v2/books/{sample.pk}/assist/", body, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert replay.status_code == 202 and replay["Idempotent-Replayed"] == "true"
    assert AgentRun.objects.filter(agent__slug="books").count() == 1
    missing = api(alice).post(f"/api/v2/books/{sample.pk}/assist/", {"task": "draft"}, format="json")
    assert missing.status_code == 422
    other = api(alice).post(f"/api/v2/books/{sample.pk}/assist/", {"task": "check", "chapter": 999999}, format="json")
    assert other.status_code == 404


@pytest.mark.django_db
def test_a_book_from_a_premise_over_the_api(sample, api, alice, fake, worker):
    fake.script += [{"text": json.dumps(OUTLINE)}, {"text": json.dumps(DETAIL)}]
    response = worker(api(alice).post, "/api/v2/books/premise/", {"premise": "A truthful speechwriter."}, format="json")
    assert response.status_code == 202, response.json()
    brief_id = response.json()["brief"]["id"]
    assert Brief.objects.get(public_id=brief_id).status == Brief.READY  # the run ran eagerly
    followed = api(alice).get(f"/api/v2/ai/briefs/{brief_id}/").json()
    assert followed["result"]["title"] == "The Quiet Part"
    created = api(alice).post(f"/api/v2/books/premise/{brief_id}/create/", {}, format="json")
    assert created.status_code == 201
    assert [c["title"] for c in created.json()["chapter_list"]] == ["Opening Remarks", "The Leak", "Closing Remarks"]
    assert api(alice).post(f"/api/v2/books/premise/{brief_id}/create/", {}, format="json").status_code == 409


@pytest.mark.django_db
def test_the_shelf_reads_the_library_through_the_service(sample, alice):
    assert [services.summary(b)["slug"] for b in services.shelf(alice)] == ["sample"]


@pytest.mark.django_db
def test_a_jekyll_sites_books_are_not_the_librarys(sample, api, alice):
    """drsai's picture books and ABC books stay their site's pages until they are book types (books.abc)."""
    import_site(Path(settings.REPO_ROOT) / "content" / "tests" / "fixtures" / "jekyll" / "site", "fixture")
    theirs = BookPage.objects.exclude(pk__in=[b.pk for b in services.shelf(alice, templates=True)]).exclude(
        pk=sample.pk
    )
    assert theirs.exists()
    assert [b["slug"] for b in api(alice).get("/api/v2/books/").json()] == ["sample"]
    for book in theirs:
        assert api(alice).get(f"/api/v2/books/{book.pk}/").status_code == 404
        assert (
            api(alice).post(f"/api/v2/books/{book.pk}/assist/", {"task": "outline"}, format="json").status_code == 404
        )


@pytest.mark.django_db
def test_a_books_other_files_are_edited_one_by_one_as_draft_revisions(sample, api, alice, bob):
    url = f"/api/v2/books/{sample.pk}/documents/"
    got = api(alice).get(url).json()
    assert got["documents"] == [{"path": "guides/act-1-chapters-01-02.md", "text": "# Act I guide\n\nOpen cold.\n"}]
    guide = {
        "base_revision_id": got["revision"],
        "path": "guides/act-1-chapters-01-02.md",
        "text": "# Act I\n\nOpen warm.\n",
    }
    saved = api(alice).post(url, guide, format="json")
    assert saved.status_code == 200, saved.json()
    assert (
        saved.json()["documents"][0]["text"] == "# Act I\n\nOpen warm.\n"
        and saved.json()["revision"] != got["revision"]
    )
    assert api(alice).post(url, guide, format="json").status_code == 409  # edited from an older revision
    book = BookPage.objects.get(pk=sample.pk)
    assert book.has_unpublished_changes and book.documents[0]["text"] == "# Act I guide\n\nOpen cold.\n"  # a draft
    first = ChapterPage.objects.child_of(sample).get(number=1)
    task = api(alice).get(f"/api/v2/books/{sample.pk}/context/?chapter={first.pk}").json()["text"]
    assert "## Drafting guide covering chapter 1\n\n# Act I\n\nOpen warm." in task  # what the AI reads
    revision = saved.json()["revision"]
    for path in ("book.yml", "outline.md", "notes/continuity.md", "chapters/ch09.md", "../escape.md"):
        refused = api(alice).post(url, {"base_revision_id": revision, "path": path, "text": "x"}, format="json")
        assert refused.status_code == 422, path
    added = api(alice).post(
        url, {"base_revision_id": revision, "path": "guides/act-2.md", "text": "Act II."}, format="json"
    )
    assert [d["path"] for d in added.json()["documents"]] == ["guides/act-1-chapters-01-02.md", "guides/act-2.md"]
    gone = {"base_revision_id": added.json()["revision"], "path": "guides/act-2.md", "text": None}
    assert [d["path"] for d in api(alice).post(url, gone, format="json").json()["documents"]] == [
        "guides/act-1-chapters-01-02.md"
    ]
    assert api(bob).get(url).status_code == 404
