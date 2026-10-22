"""A book's `library/<slug>/` as a generated file set (books/files.py): the
real library round-trips byte for byte (ADR 0006 decision 13's gate, on
`impairment` and `_template`), a re-import is idempotent and never overwrites
what was changed in the platform, an edit renders by line surgery so every
untouched line stays, and a book made here renders a manifest of its own."""

import filecmp
import shutil
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from agents.principals import ensure_legacy_import_user
from books import files, services
from books.files import export_library, import_library, set_keys
from cms.models import BookPage, ChapterPage
from cms.services import save_draft

LIBRARY = Path(settings.BOOKS_LIBRARY_DIR)


def tree_of(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}


def fresh(page):
    """The page's latest revision, read from the database (an instance's own `latest_revision` may be stale)."""
    return type(page).objects.get(pk=page.pk).get_latest_revision_as_object()


def edit(page, **fields):
    draft = page.get_latest_revision_as_object()
    for name, value in fields.items():
        setattr(draft, name, value)
    save_draft(draft, user=ensure_legacy_import_user())
    return type(page).objects.get(pk=page.pk)


# ── the gate: the real library ─────────────────────────────────────────────


@pytest.mark.django_db
def test_the_real_library_round_trips_byte_for_byte(capsys):
    """import_books → export_books on packages/books/library: impairment and _template, every file identical."""
    if not (LIBRARY / "impairment" / "book.yml").is_file():
        pytest.skip("packages/books/library is not in this checkout")
    call_command("roundtrip_books")
    out = capsys.readouterr().out
    assert "differs" not in out
    assert "26/26 file(s) identical after the round trip" in out


@pytest.mark.django_db
def test_import_then_export_writes_the_library_back_unchanged(impairment, tmp_path):
    report = export_library(tmp_path, site_key=settings.BOOKS_SITE_KEY)
    assert not report.extra
    for name in ("impairment", "_template"):
        compared = filecmp.dircmp(LIBRARY / name, tmp_path / name)
        assert tree_of(LIBRARY / name) == tree_of(tmp_path / name), compared.report()
    assert ChapterPage.objects.child_of(impairment).count() == 14
    again = export_library(tmp_path, site_key=settings.BOOKS_SITE_KEY)
    assert not again.written and len(again.unchanged) == len(report.written)  # a second export touches nothing


@pytest.mark.django_db
def test_the_book_holds_what_its_files_hold(impairment):
    book = impairment.get_latest_revision_as_object()
    assert (book.title, book.book_status, book.pov, book.tense, book.era) == (
        "The Impairment",
        "drafting",
        "Third person limited",
        "Past",
        "Early 2020s",
    )
    assert (book.acts, book.planned_chapters, book.target_word_count) == (3, 14, 90000)
    assert book.cast[:2] == ["Kareem Hassan", "Sarah"] and "Weaponization of finance" in book.themes
    assert book.outline.startswith('**"The Impairment"**') and "Continuity ledger" in book.continuity_notes
    assert "Character bible" in book.character_notes
    assert [d["path"] for d in book.documents] == [
        "README.md",
        "guides/README.md",
        "guides/act-1-chapters-01-05.md",
        "guides/act-2-chapters-06-09.md",
        "guides/act-3-chapters-10-14.md",
    ]
    assert book.front_matter["alt_titles"] == ["Goodwill", "The Valuation"]  # every other key is kept
    first = ChapterPage.objects.child_of(impairment).get(number=1)
    assert (first.act, first.chapter_status, first.pov, first.characters) == (
        1,
        "draft",
        "First person",
        ["Kareem Hassan", "Big Mike"],
    )
    assert any(
        b.block_type == "heading" and b.value["text"] == "Chapter 1: The Last Day in the Plant" for b in first.body
    )
    template = services.template_for(services.library_root())
    assert files.book_dir(template) == "_template" and services.is_template(template)


# ── re-importing ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_second_import_changes_nothing(sample, library_dir):
    revisions = BookPage.objects.get(pk=sample.pk).revisions.count()
    report = import_library(library_dir, site_key=settings.BOOKS_SITE_KEY)
    assert (report.created, report.updated, report.conflicts) == ([], [], [])
    assert len(report.unchanged) == 4  # two books (the template is one), two chapters
    assert BookPage.objects.get(pk=sample.pk).revisions.count() == revisions


@pytest.mark.django_db
def test_a_changed_file_updates_its_page_and_a_new_chapter_is_created(sample, library_dir):
    manifest = library_dir / "sample" / "book.yml"
    manifest.write_text(manifest.read_text().replace("status: drafting", "status: revising"))
    (library_dir / "sample" / "chapters" / "ch03.md").write_text("---\ntitle: Third\nnumber: 3\n---\n\nText.\n")
    report = import_library(library_dir, site_key=settings.BOOKS_SITE_KEY)
    assert report.updated == ["sample/book.yml"] and report.created == ["sample/chapters/ch03.md"]
    assert fresh(sample).book_status == "revising"
    assert ChapterPage.objects.child_of(sample).get(number=3).title == "Third"


@pytest.mark.django_db
def test_a_file_never_overwrites_what_the_platform_changed_unless_forced(sample, library_dir):
    chapter = ChapterPage.objects.child_of(sample).get(number=1)
    edit(chapter, chapter_status="revised")
    path = library_dir / "sample" / "chapters" / "ch01.md"
    path.write_text(path.read_text().replace("counted the empty chairs", "counted the chairs"))
    report = import_library(library_dir, site_key=settings.BOOKS_SITE_KEY)
    assert report.conflicts and "sample/chapters/ch01.md" in report.conflicts[0]
    assert fresh(chapter).chapter_status == "revised"
    forced = import_library(library_dir, site_key=settings.BOOKS_SITE_KEY, force=True)
    assert forced.updated == ["sample/chapters/ch01.md"]
    assert fresh(chapter).chapter_status == "draft"


@pytest.mark.django_db
def test_a_file_unchanged_since_the_import_leaves_the_platforms_newer_content(sample, library_dir):
    edit(sample, logline="A sharper logline.")
    report = import_library(library_dir, site_key=settings.BOOKS_SITE_KEY)
    assert not report.conflicts and "sample/book.yml" in report.unchanged
    assert fresh(sample).logline == "A sharper logline."


@pytest.mark.django_db
def test_an_export_is_in_sync_when_imported_again(sample, library_dir):
    edit(sample, logline="A sharper logline.")
    export_library(library_dir, site_key=settings.BOOKS_SITE_KEY)
    report = import_library(library_dir, site_key=settings.BOOKS_SITE_KEY)
    assert not report.conflicts and not report.updated
    hand = library_dir / "sample" / "book.yml"
    hand.write_text(hand.read_text().replace("acts: 3", "acts: 4"))  # a hand edit after the export
    assert import_library(library_dir, site_key=settings.BOOKS_SITE_KEY).updated == ["sample/book.yml"]
    assert fresh(sample).acts == 4


@pytest.mark.django_db
def test_a_chapter_whose_file_is_gone_is_reported_and_kept(sample, library_dir):
    (library_dir / "sample" / "chapters" / "ch02.md").unlink()
    report = import_library(library_dir, site_key=settings.BOOKS_SITE_KEY)
    assert report.errors == ["sample/chapters/ch02.md: its file is gone; the chapter is kept"]
    assert ChapterPage.objects.child_of(sample).filter(number=2).exists()


# ── rendering an edited book ───────────────────────────────────────────────


@pytest.mark.django_db
def test_an_edit_rewrites_only_its_own_lines(sample, library_dir, tmp_path):
    edit(sample, book_status="revising", cast=["Ana", "Boris", "Cleo"], logline="A plan: then a reversal.")
    chapter = ChapterPage.objects.child_of(sample).get(number=2)
    edit(chapter, chapter_status="final", tone=["Warm"])
    export_library(tmp_path, site_key=settings.BOOKS_SITE_KEY)
    manifest = (tmp_path / "sample" / "book.yml").read_text()
    original = (library_dir / "sample" / "book.yml").read_text()
    assert manifest == (
        original.replace("status: drafting", "status: revising")
        .replace("Someone wants something and cannot have it.", "'A plan: then a reversal.'")
        .replace("cast: [Ana, Boris]", "cast: [Ana, Boris, Cleo]")
    )
    text = (tmp_path / "sample" / "chapters" / "ch02.md").read_text()
    before = (library_dir / "sample" / "chapters" / "ch02.md").read_text()
    assert text == before.replace("status: draft\n", "status: final\n").replace("tone:\n- Wry\n", "tone:\n- Warm\n")
    for unchanged in ("outline.md", "chapters/ch01.md", "notes/continuity.md", "guides/act-1-chapters-01-02.md"):
        assert (tmp_path / "sample" / unchanged).read_bytes() == (library_dir / "sample" / unchanged).read_bytes()


@pytest.mark.django_db
def test_a_changed_body_is_written_from_its_blocks(sample, tmp_path):
    chapter = ChapterPage.objects.child_of(sample).get(number=1)
    body = list(chapter.body.get_prep_value())
    prose = next(i for i, b in enumerate(body) if b["type"] == "markdown" and "empty chairs" in b["value"])
    body[prose] = {**body[prose], "value": "Ana left the chairs where they were.\n\n---"}
    edit(chapter, body=body)
    export_library(tmp_path, site_key=settings.BOOKS_SITE_KEY)
    text = (tmp_path / "sample" / "chapters" / "ch01.md").read_text()
    assert text.startswith("---\ntitle: Chapter 1\n") and "Ana left the chairs where they were." in text
    assert "## Chapter Body\n\nAna left the chairs where they were.\n\n---\n\n## References" in text


@pytest.mark.django_db
def test_prune_removes_what_the_platform_does_not_hold(sample, library_dir):
    stray = library_dir / "sample" / "notes" / "scratch.md"
    stray.write_text("not imported")
    assert export_library(library_dir, site_key=settings.BOOKS_SITE_KEY).extra == ["sample/notes/scratch.md"]
    assert stray.exists()
    export_library(library_dir, site_key=settings.BOOKS_SITE_KEY, prune=True)
    assert not stray.exists()


@pytest.mark.django_db
def test_a_book_made_here_renders_a_manifest_of_its_own(sample, editor, tmp_path):
    book = services.new_book(services.library_root(), editor, title="The Quiet Part", logline="A speechwriter tells.")
    chapter = services.add_chapter(book, editor, title="Opening Remarks")
    export_library(tmp_path, site_key=settings.BOOKS_SITE_KEY, slugs=["the-quiet-part"])
    root = tmp_path / "the-quiet-part"
    manifest = (root / "book.yml").read_text()
    assert "slug: the-quiet-part\ntitle: The Quiet Part\nstatus: idea\npov: Third person limited\n" in manifest
    assert "logline: A speechwriter tells." in manifest and "created: '" in manifest
    assert (root / "outline.md").read_text() == "# The Quiet Part\n\nOutline for the-quiet-part.\n"
    text = (root / "chapters" / "ch01.md").read_text()
    assert text.startswith("---\ntitle: Opening Remarks\nnumber: 1\nact: 1\nstatus: stub\n")
    assert "_Opening Remarks is not written yet._" in text and chapter.chapter_status == "stub"
    assert (root / "chapters" / ".gitkeep").exists()  # the template's other files come along


def test_set_keys_rewrites_in_place_keeps_list_style_and_appends_what_is_new():
    text = "# head\nslug: x\ncast:\n  - A\n  - B\n\n# tail comment\ntags: [a, b]\n"
    out = set_keys(text, {"cast": ["A", "C"], "tags": ["a"], "genre": "Noir: dark"})
    assert out == "# head\nslug: x\ncast:\n  - A\n  - C\n\n# tail comment\ntags: [a]\ngenre: 'Noir: dark'\n"
    assert set_keys(text, {}) is text


@pytest.mark.django_db
def test_a_renumbered_chapter_moves_to_its_number(sample, library_dir, tmp_path):
    shutil.copytree(library_dir, tmp_path / "copy")
    chapter = ChapterPage.objects.child_of(sample).get(number=2)
    edit(chapter, number=5)
    export_library(tmp_path / "copy", site_key=settings.BOOKS_SITE_KEY)
    assert (tmp_path / "copy" / "sample" / "chapters" / "ch05.md").is_file()
    report = import_library(tmp_path / "copy", site_key=settings.BOOKS_SITE_KEY)
    assert "sample/chapters/ch05.md" in report.unchanged and not report.created
