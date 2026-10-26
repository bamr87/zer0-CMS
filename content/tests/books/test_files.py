"""A book's `library/<slug>/` as a generated file set (books/files.py): the
real library round-trips byte for byte (ADR 0006 decision 13's gate, on
`impairment` and `_template`); a re-import is idempotent; neither command loses
what the other side changed — an export never overwrites a hand edit, an
import never overwrites a change made here, never publishes a draft and never
brings back a deleted page; two chapters never share a file; an edit renders
by line surgery so every untouched line stays; and a book made here renders a
manifest of its own."""

import filecmp
import re
import shutil
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from agents.principals import ensure_legacy_import_user
from books import files, library, services
from books.files import export_library, import_library, set_keys
from books.models import LibraryFile
from cms.models import BookPage, ChapterPage
from cms.services import publish, save_draft
from importers.models import ImportedSource

LIBRARY = Path(settings.BOOKS_LIBRARY_DIR)
KEY = settings.BOOKS_SITE_KEY


def tree_of(directory: Path) -> dict[str, bytes]:
    return {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}


def fresh(page):
    """The page's latest revision, read from the database (an instance's own `latest_revision` may be stale)."""
    return type(page).objects.get(pk=page.pk).get_latest_revision_as_object()


def live(page):
    """What is published of the page."""
    return type(page).objects.get(pk=page.pk)


def edit(page, *, published=False, **fields):
    """A person's change to the page: a draft revision, or (`published`) one that goes live."""
    draft = page.get_latest_revision_as_object()
    for name, value in fields.items():
        setattr(draft, name, value)
    (publish if published else save_draft)(draft, ensure_legacy_import_user())
    return type(page).objects.get(pk=page.pk)


def chapter(book, number):
    return next(c for c in ChapterPage.objects.child_of(book) if fresh(c).number == number)


# ── the gate: the real library ─────────────────────────────────────────────


@pytest.mark.django_db
def test_the_real_library_round_trips_byte_for_byte(capsys):
    """import_books → export_books on packages/books/library: impairment and _template, every file identical."""
    if not (LIBRARY / "impairment" / "book.yml").is_file():
        pytest.skip("packages/books/library is not in this checkout")
    call_command("roundtrip_books")
    out = capsys.readouterr().out
    identical = re.search(r"(\d+)/(\d+) file\(s\) identical after the round trip", out)
    assert "differs" not in out and identical and identical.group(1) == identical.group(2), out
    assert (
        int(identical.group(1)) >= 26
    )  # impairment (book.yml, outline, 14 chapters, guides, notes, README) and _template


@pytest.mark.django_db
def test_import_then_export_writes_the_library_back_unchanged(impairment, tmp_path):
    report = export_library(tmp_path, site_key=KEY)
    assert not report.extra and not report.conflicts
    for name in ("impairment", "_template"):
        compared = filecmp.dircmp(LIBRARY / name, tmp_path / name)
        assert tree_of(LIBRARY / name) == tree_of(tmp_path / name), compared.report()
    assert ChapterPage.objects.child_of(impairment).count() == 14
    again = export_library(tmp_path, site_key=KEY)
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


@pytest.mark.django_db
def test_an_empty_notes_file_round_trips(library_dir, tmp_path):
    (library_dir / "sample" / "notes" / "style-guide.md").write_text("", encoding="utf-8")
    import_library(library_dir, site_key=KEY)
    export_library(tmp_path, site_key=KEY)
    assert (tmp_path / "sample" / "notes" / "style-guide.md").read_text() == ""


# ── re-importing ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_second_import_changes_nothing(sample, library_dir):
    revisions = BookPage.objects.get(pk=sample.pk).revisions.count()
    report = import_library(library_dir, site_key=KEY)
    assert (report.created, report.updated, report.conflicts) == ([], [], [])
    assert len(report.unchanged) == 4  # two books (the template is one), two chapters
    assert BookPage.objects.get(pk=sample.pk).revisions.count() == revisions


@pytest.mark.django_db
def test_a_changed_file_updates_its_page_and_a_new_chapter_is_created(sample, library_dir):
    manifest = library_dir / "sample" / "book.yml"
    manifest.write_text(manifest.read_text().replace("status: drafting", "status: revising"))
    (library_dir / "sample" / "chapters" / "ch03.md").write_text("---\ntitle: Third\nnumber: 3\n---\n\nText.\n")
    report = import_library(library_dir, site_key=KEY)
    assert report.updated == ["sample/book.yml"] and report.created == ["sample/chapters/ch03.md"]
    assert live(sample).book_status == "revising"  # a live book with no draft: published, as imports are
    third = ChapterPage.objects.child_of(sample).get(number=3)
    assert third.title == "Third" and third.live  # under a live book


@pytest.mark.django_db
def test_a_file_never_overwrites_what_the_platform_changed_unless_forced(sample, library_dir):
    first = chapter(sample, 1)
    edit(first, chapter_status="revised")
    path = library_dir / "sample" / "chapters" / "ch01.md"
    path.write_text(path.read_text().replace("counted the empty chairs", "counted the chairs"))
    report = import_library(library_dir, site_key=KEY)
    assert report.conflicts and "sample/chapters/ch01.md" in report.conflicts[0]
    assert fresh(first).chapter_status == "revised"
    forced = import_library(library_dir, site_key=KEY, force=True)
    assert forced.updated == ["sample/chapters/ch01.md"]
    assert fresh(first).chapter_status == "draft"
    assert live(first).chapter_status == "draft" and "counted the empty chairs" in live(first).body.raw_data[4]["value"]


@pytest.mark.django_db
def test_a_file_unchanged_since_the_import_leaves_the_platforms_newer_content(sample, library_dir):
    edit(sample, logline="A sharper logline.")
    report = import_library(library_dir, site_key=KEY)
    assert not report.conflicts and "sample/book.yml" in report.unchanged
    assert fresh(sample).logline == "A sharper logline."


@pytest.mark.django_db
def test_an_export_is_in_sync_when_imported_again(sample, library_dir):
    edit(sample, logline="A sharper logline.")
    export_library(library_dir, site_key=KEY, include_drafts=True)
    report = import_library(library_dir, site_key=KEY)
    assert not report.conflicts and not report.updated
    hand = library_dir / "sample" / "book.yml"
    hand.write_text(hand.read_text().replace("acts: 3", "acts: 4"))  # a hand edit after the export
    assert import_library(library_dir, site_key=KEY).updated == ["sample/book.yml"]
    assert fresh(sample).acts == 4 and fresh(sample).logline == "A sharper logline."
    assert live(sample).acts == 3  # over a person's draft, the import is a draft too


@pytest.mark.django_db
def test_a_chapter_whose_file_is_gone_is_reported_and_kept(sample, library_dir):
    (library_dir / "sample" / "chapters" / "ch02.md").unlink()
    report = import_library(library_dir, site_key=KEY)
    assert report.errors == ["sample/chapters/ch02.md: its file is gone; the chapter is kept"]
    assert ChapterPage.objects.child_of(sample).filter(number=2).exists()


# ── an import never publishes what nobody accepted ─────────────────────────


@pytest.mark.django_db
def test_a_hand_edit_to_a_draft_chapter_stays_a_draft(sample, editor, library_dir):
    book = services.new_book(services.library_root(), editor, title="The Quiet Part")
    stub = services.add_chapter(book, editor, title="Opening Remarks")
    export_library(library_dir, site_key=KEY, include_drafts=True)
    assert len(import_library(library_dir, site_key=KEY).unchanged) == 6  # the platform's own export, in sync
    path = library_dir / "the-quiet-part" / "chapters" / "ch01.md"
    path.write_text(path.read_text().replace("status: stub", "status: outline"))
    report = import_library(library_dir, site_key=KEY)
    assert report.updated == ["the-quiet-part/chapters/ch01.md"] and not report.conflicts
    stub = ChapterPage.objects.get(pk=stub.pk)
    assert fresh(stub).chapter_status == "outline" and not stub.live and stub.live_revision is None


@pytest.mark.django_db
def test_a_persons_unpublished_draft_is_never_published_by_an_import(sample, library_dir, tmp_path):
    sixth = chapter(sample, 2)
    edit(sixth, subtitle="PRIVATE DRAFT SUBTITLE")
    export_library(library_dir, site_key=KEY)  # what is live: the draft stays out of the files
    path = library_dir / "sample" / "chapters" / "ch02.md"
    assert "PRIVATE" not in path.read_text()
    path.write_text(path.read_text().replace("- Wry", "- Dry"))
    report = import_library(library_dir, site_key=KEY)
    assert report.conflicts and "sample/chapters/ch02.md" in report.conflicts[0]  # a draft the file does not hold
    assert live(sixth).subtitle == "A subtitle" and live(sixth).tone == ["Wry"]
    copy = tmp_path / "drafts"
    export_library(copy, site_key=KEY, include_drafts=True)
    drafted = copy / "sample" / "chapters" / "ch02.md"
    drafted.write_text(drafted.read_text().replace("- Wry", "- Dry"))
    assert import_library(copy, site_key=KEY).updated == ["sample/chapters/ch02.md"]
    assert fresh(sixth).tone == ["Dry"] and fresh(sixth).subtitle == "PRIVATE DRAFT SUBTITLE"
    assert live(sixth).subtitle == "A subtitle"  # still not published


@pytest.mark.django_db
def test_export_writes_what_is_live_unless_asked_for_drafts(sample, editor, tmp_path):
    services.new_book(services.library_root(), editor, title="The Quiet Part")
    services.add_chapter(sample, editor, title="Later")
    report = export_library(tmp_path, site_key=KEY)
    assert "the-quiet-part (not live; --include-drafts writes it)" in report.skipped
    assert not (tmp_path / "sample" / "chapters" / "ch03.md").exists()
    export_library(tmp_path, site_key=KEY, include_drafts=True)
    assert (tmp_path / "sample" / "chapters" / "ch03.md").is_file() and (tmp_path / "the-quiet-part").is_dir()


# ── an export never overwrites a hand edit ─────────────────────────────────


@pytest.mark.django_db
def test_an_export_keeps_a_hand_edit_it_has_not_read(sample, library_dir, capsys):
    path = library_dir / "sample" / "chapters" / "ch01.md"
    path.write_text(path.read_text() + "A HAND EDIT.\n")
    edit(chapter(sample, 1), chapter_status="revised", published=True)  # the platform has something new to write
    report = export_library(library_dir, site_key=KEY)
    assert report.conflicts == [
        "sample/chapters/ch01.md: changed on disk since the platform last read or wrote it — kept"
    ]
    assert "A HAND EDIT." in path.read_text() and "status: draft" in path.read_text()
    with pytest.raises(SystemExit):
        call_command("export_books", "--out", str(library_dir))
    capsys.readouterr()
    forced = export_library(library_dir, site_key=KEY, force=True)
    assert forced.written == ["sample/chapters/ch01.md"] and "A HAND EDIT." not in path.read_text()


@pytest.mark.django_db
def test_an_export_after_an_import_conflict_keeps_the_file(sample, library_dir):
    fourth = chapter(sample, 2)
    edit(fourth, chapter_status="revised")
    path = library_dir / "sample" / "chapters" / "ch02.md"
    path.write_text(path.read_text().replace("- Wry", "- Hand-made"))
    assert import_library(library_dir, site_key=KEY).conflicts
    report = export_library(library_dir, site_key=KEY, include_drafts=True)
    assert [c.split(":")[0] for c in report.conflicts] == ["sample/chapters/ch02.md"]
    assert "- Hand-made" in path.read_text()


@pytest.mark.django_db
def test_an_export_elsewhere_never_makes_the_librarys_files_look_changed(sample, library_dir, tmp_path):
    edit(chapter(sample, 1), chapter_status="revised", published=True)
    export_library(tmp_path / "scratch", site_key=KEY)
    report = import_library(library_dir, site_key=KEY)
    assert not report.updated and not report.conflicts
    assert fresh(chapter(sample, 1)).chapter_status == "revised"  # not reverted by the older file


# ── renumbering, duplicates and deletions ──────────────────────────────────


@pytest.mark.django_db
def test_a_renumbered_chapter_moves_to_its_number(sample, library_dir, tmp_path):
    shutil.copytree(library_dir, tmp_path / "copy")
    edit(chapter(sample, 2), number=5)
    export_library(tmp_path / "copy", site_key=KEY, include_drafts=True)
    assert (tmp_path / "copy" / "sample" / "chapters" / "ch05.md").is_file()
    assert not (tmp_path / "copy" / "sample" / "chapters" / "ch02.md").exists()
    report = import_library(tmp_path / "copy", site_key=KEY)
    assert "sample/chapters/ch05.md" in report.unchanged and not report.created


@pytest.mark.django_db
def test_importing_before_the_renumber_is_exported_changes_nothing(sample, library_dir):
    moved = chapter(sample, 2)
    edit(moved, number=5)
    report = import_library(library_dir, site_key=KEY)
    assert (report.created, report.updated, report.conflicts, report.errors) == ([], [], [], [])
    assert "sample/chapters/ch02.md" in report.unchanged  # its old file, until an export moves it
    assert ChapterPage.objects.child_of(sample).count() == 2 and fresh(moved).number == 5
    assert ImportedSource.objects.filter(page=moved).exists()  # it still renders over its own file
    export_library(library_dir, site_key=KEY, include_drafts=True)
    assert sorted(p.name for p in (library_dir / "sample" / "chapters").iterdir()) == ["ch01.md", "ch05.md"]
    again = import_library(library_dir, site_key=KEY)
    assert not again.created and not again.updated and not again.errors


@pytest.mark.django_db
def test_two_chapters_with_one_number_keep_their_own_files(sample, alice, library_dir):
    first = chapter(sample, 1)
    edit(first, number=2)  # what the studio's page editor allows while a person renumbers
    tree = files.book_tree(sample)
    assert sorted(p for p in tree if library.is_chapter(p)) == ["chapters/ch01.md", "chapters/ch02.md"]
    assert "number: 2" in tree["chapters/ch01.md"]
    detail = services.detail(sample, alice)
    assert sorted(c["id"] for c in detail["chapter_list"]) == sorted(c.pk for c in ChapterPage.objects.child_of(sample))
    assert "chapter-duplicate" in {i.code for i in services.validate(sample)}
    report = export_library(library_dir, site_key=KEY, include_drafts=True)
    assert not report.removed and sorted(p.name for p in (library_dir / "sample" / "chapters").iterdir()) == [
        "ch01.md",
        "ch02.md",
    ]
    made = [services.add_chapter(sample, alice, title=t) for t in ("Third", "Fourth")]
    edit(made[1], number=3)  # two chapters made here, one number: neither is lost
    paths = sorted(p for p in files.book_tree(sample) if library.is_chapter(p))
    assert paths == ["chapters/ch003.md", "chapters/ch01.md", "chapters/ch02.md", "chapters/ch03.md"]


@pytest.mark.django_db
def test_chapter_in_finds_a_chapter_by_its_file_not_its_number(sample):
    first, second = chapter(sample, 1), chapter(sample, 2)
    edit(first, number=2)
    for page, path in ((first, "sample/chapters/ch01.md"), (second, "sample/chapters/ch02.md")):
        _rm, found = services.chapter_in(sample, page)
        assert found.path == path and found.number == 2
    edit(second, number=7)  # a renumbered draft is found where it would be written
    _rm, found = services.chapter_in(sample, second)
    assert (found.path, found.number) == ("sample/chapters/ch07.md", 7)


@pytest.mark.django_db
def test_a_chapter_deleted_here_is_not_brought_back(sample, library_dir):
    chapter(sample, 2).delete()
    report = import_library(library_dir, site_key=KEY)
    assert not report.created and "sample/chapters/ch02.md" in report.unchanged
    assert not ChapterPage.objects.child_of(sample).filter(number=2).exists()
    removed = export_library(library_dir, site_key=KEY)
    assert removed.removed == ["sample/chapters/ch02.md"] and not removed.extra
    assert not import_library(library_dir, site_key=KEY).created


@pytest.mark.django_db
def test_a_deleted_chapters_hand_edited_file_is_a_conflict_until_forced(sample, library_dir):
    chapter(sample, 2).delete()
    path = library_dir / "sample" / "chapters" / "ch02.md"
    path.write_text(path.read_text().replace("- Wry", "- Kept"))
    report = import_library(library_dir, site_key=KEY)
    assert report.conflicts == [
        "sample/chapters/ch02.md: deleted in the platform, and changed on disk since (--force reads it in)"
    ]
    assert export_library(library_dir, site_key=KEY).conflicts and path.is_file()
    assert import_library(library_dir, site_key=KEY, force=True).created == ["sample/chapters/ch02.md"]


@pytest.mark.django_db
def test_a_deleted_book_is_not_brought_back_and_its_files_go(sample, library_dir):
    sample.delete()
    assert not import_library(library_dir, site_key=KEY).created
    report = export_library(library_dir, site_key=KEY)
    assert "sample/book.yml" in report.removed and not (library_dir / "sample" / "book.yml").exists()


# ── rendering an edited book ───────────────────────────────────────────────


@pytest.mark.django_db
def test_an_edit_rewrites_only_its_own_lines(sample, library_dir, tmp_path):
    edit(sample, book_status="revising", cast=["Ana", "Boris", "Cleo"], logline="A plan: then a reversal.")
    edit(chapter(sample, 2), chapter_status="final", tone=["Warm"])
    export_library(tmp_path, site_key=KEY, include_drafts=True)
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
    first = chapter(sample, 1)
    body = list(first.body.get_prep_value())
    prose = next(i for i, b in enumerate(body) if b["type"] == "markdown" and "empty chairs" in b["value"])
    body[prose] = {**body[prose], "value": "Ana left the chairs where they were.\n\n---"}
    edit(first, body=body)
    export_library(tmp_path, site_key=KEY, include_drafts=True)
    text = (tmp_path / "sample" / "chapters" / "ch01.md").read_text()
    assert text.startswith("---\ntitle: Chapter 1\n") and "Ana left the chairs where they were." in text
    assert "## Chapter Body\n\nAna left the chairs where they were.\n\n---\n\n## References" in text


@pytest.mark.django_db
def test_prune_removes_what_the_platform_does_not_hold(sample, library_dir):
    stray = library_dir / "sample" / "notes" / "scratch.md"
    stray.write_text("not imported")
    assert export_library(library_dir, site_key=KEY).extra == ["sample/notes/scratch.md"]
    assert stray.exists()
    export_library(library_dir, site_key=KEY, prune=True)
    assert not stray.exists()


@pytest.mark.django_db
def test_a_book_made_here_renders_a_manifest_of_its_own(sample, editor, tmp_path):
    book = services.new_book(services.library_root(), editor, title="The Quiet Part", logline="A speechwriter tells.")
    made = services.add_chapter(book, editor, title="Opening Remarks")
    export_library(tmp_path, site_key=KEY, slugs=["the-quiet-part"], include_drafts=True)
    root = tmp_path / "the-quiet-part"
    manifest = (root / "book.yml").read_text()
    assert "slug: the-quiet-part\ntitle: The Quiet Part\nstatus: idea\npov: Third person limited\n" in manifest
    assert "logline: A speechwriter tells." in manifest and "created: '" in manifest
    assert (root / "outline.md").read_text() == "# The Quiet Part\n\nOutline for the-quiet-part.\n"
    text = (root / "chapters" / "ch01.md").read_text()
    assert text.startswith("---\ntitle: Opening Remarks\nnumber: 1\nact: 1\nstatus: stub\n")
    assert "_Opening Remarks is not written yet._" in text and made.chapter_status == "stub"
    assert (root / "chapters" / ".gitkeep").exists()  # the template's other files come along
    assert LibraryFile.objects.filter(path="the-quiet-part/chapters/ch01.md", page=made).exists()


def test_set_keys_rewrites_in_place_keeps_list_style_and_appends_what_is_new():
    text = "# head\nslug: x\ncast:\n  - A\n  - B\n\n# tail comment\ntags: [a, b]\n"
    out = set_keys(text, {"cast": ["A", "C"], "tags": ["a"], "genre": "Noir: dark"})
    assert out == "# head\nslug: x\ncast:\n  - A\n  - C\n\n# tail comment\ntags: [a]\ngenre: 'Noir: dark'\n"
    assert set_keys(text, {}) is text


@pytest.mark.django_db
def test_pages_imported_before_the_manuscript_fields_keep_their_hash(sample):
    """cms/0002's new fields are hashed only once they leave their defaults, so a
    Jekyll site's book or chapter imported before them is still unchanged."""
    page = ChapterPage(title="A chapter", number=3)
    assert set(page.hashed_content()) & set(ChapterPage.sparse_hashed_fields) == set()
    assert "number" in page.hashed_content()
    book = BookPage(title="A book", profile="story")
    assert set(book.hashed_content()) & set(BookPage.sparse_hashed_fields) == set()
    before = book.compute_content_hash()
    book.book_status = "drafting"
    assert book.hashed_content()["book_status"] == "drafting" and book.compute_content_hash() != before
