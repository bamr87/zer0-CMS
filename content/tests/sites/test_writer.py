"""The confined writer (sites/writer.py, PLAN G4): the Rails catalog's
`test_writer.rb` and the Rails app's `SitePath` and atomic-write rules, ported —
plain paths only, no symlink at any component, realpath inside the root, O_EXCL
for a new file, an atomic replace that re-checks the bytes, and file-name slugs."""

import os
import stat

import pytest

from sites import writer


@pytest.fixture
def root(tmp_path):
    site = tmp_path / "site"
    (site / "pages/_posts/hacks").mkdir(parents=True)
    (site / "pages/_docs").mkdir(parents=True)
    return site


@pytest.fixture
def outside(tmp_path):
    away = tmp_path / "outside"
    away.mkdir()
    return away


@pytest.mark.parametrize("bad", ["", "/etc/passwd", "../x", "a/../b", "a//b", "./a", "a/.", "a\0b"])
def test_only_plain_relative_paths(root, bad):
    with pytest.raises(writer.Refused):
        writer.confined_target(root, bad)


def test_reads_a_regular_file_through_no_symlink(root, outside):
    (root / "pages/_docs/real.md").write_text("x")
    assert writer.read_bytes(root, "pages/_docs/real.md") == b"x"
    assert writer.read_bytes(root, "pages/_docs/missing.md") is None
    (outside / "secret.md").write_text("secret")
    os.symlink(outside / "secret.md", root / "pages/_docs/linked.md")
    os.symlink(outside, root / "pages/linked-dir")
    for rel in ("pages/_docs/linked.md", "pages/linked-dir/secret.md"):
        with pytest.raises(writer.Refused):
            writer.confined_file(root, rel)
    with pytest.raises(writer.Refused):
        writer.confined_file(root, "pages/_docs")  # a directory is not a file


def test_a_new_file_is_created_once_and_never_through_a_planted_symlink(root, outside):
    writer.write(root, "pages/_docs/once.md", b"first", expected=None)
    with pytest.raises(writer.Stale):
        writer.write(root, "pages/_docs/once.md", b"second", expected=None)
    assert (root / "pages/_docs/once.md").read_bytes() == b"first"
    victim = outside / "victim.md"
    victim.write_text("original")
    os.symlink(victim, root / "pages/_docs/planted.md")
    os.symlink(outside / "dangling.md", root / "pages/_docs/dangling.md")
    for rel in ("pages/_docs/planted.md", "pages/_docs/dangling.md"):
        with pytest.raises(writer.Refused):
            writer.write(root, rel, b"x", expected=None)
    assert victim.read_text() == "original" and not (outside / "dangling.md").exists()


def test_a_directory_symlinked_away_is_refused_and_nothing_lands_outside(root, outside):
    (root / "pages/_docs").rmdir()
    os.symlink(outside, root / "pages/_docs")
    with pytest.raises(writer.Refused):
        writer.write(root, "pages/_docs/x.md", b"x", expected=None)
    assert list(outside.iterdir()) == []


def test_missing_directories_are_made_one_checked_component_at_a_time(root):
    writer.write(root, "pages/_notes/deep/first.md", b"note", expected=None)
    assert (root / "pages/_notes/deep/first.md").read_bytes() == b"note"


def test_a_replace_is_atomic_keeps_the_mode_and_needs_the_bytes_it_checked(root):
    path = root / "pages/_docs/page.md"
    path.write_bytes(b"one")
    os.chmod(path, 0o640)
    writer.write(root, "pages/_docs/page.md", b"two", expected=b"one")
    assert path.read_bytes() == b"two" and stat.S_IMODE(os.stat(path).st_mode) == 0o640
    with pytest.raises(writer.Stale):
        writer.write(root, "pages/_docs/page.md", b"three", expected=b"one")
    assert path.read_bytes() == b"two"
    assert [p.name for p in path.parent.iterdir()] == ["page.md"], "no temporary file is left behind"


def test_a_change_that_lands_mid_write_is_refused(root, monkeypatch):
    path = root / "pages/_docs/page.md"
    path.write_bytes(b"one")
    real_fsync = os.fsync

    def someone_else_writes(fd):
        real_fsync(fd)
        path.write_bytes(b"theirs")

    monkeypatch.setattr(writer.os, "fsync", someone_else_writes)
    with pytest.raises(writer.Stale):
        writer.write(root, "pages/_docs/page.md", b"mine", expected=b"one")
    assert path.read_bytes() == b"theirs"


def test_remove_only_what_is_still_expected(root):
    path = root / "pages/_docs/gone.md"
    path.write_bytes(b"x")
    with pytest.raises(writer.Stale):
        writer.remove(root, "pages/_docs/gone.md", expected=b"y")
    writer.remove(root, "pages/_docs/gone.md", expected=b"x")
    assert not path.exists()


# ── slugs ───────────────────────────────────────────────────────────────────


def test_slugs_are_validated_after_transliteration():
    assert writer.slug_for(None, "Café Crème Brûlée!") == "cafe-creme-brulee"
    assert writer.slug_for("Straße-Ærø") == "strasse-aero"
    for bad in ("../../x", "a/b", "a--b", "-a", "a_b", "..", "💥"):
        with pytest.raises(ValueError):
            writer.slug_for(bad)
    with pytest.raises(ValueError):
        writer.slug_for(None, "!!!")


def test_slugify_truncates_at_a_word_boundary():
    slug = writer.slugify("an extraordinarily long title that keeps going well past the sixty character limit")
    assert slug == "an-extraordinarily-long-title-that-keeps-going-well-past-the" and len(slug) <= 60
    assert writer.slugify("a" * 80) == "a" * 60
