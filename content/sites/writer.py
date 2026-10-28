"""The confined writer: the only way the platform reads or writes a file inside
a site's checkout (PLAN G4).

The Python port of the Rails app's `SitePath` and `PageEditor#write_atomically`
and of the Rails catalog's `Writer` (its slug rules and its O_EXCL create):

* a path is relative, plain (no `..`, `.`, empty segment, NUL or leading
  `/`), reaches no symlink at ANY component below the site root (each one is
  `lstat`ed), and its realpath is inside the root's realpath;
* an existing file is replaced atomically — a temporary file beside it
  (created with O_EXCL, the original's mode), flushed and fsynced, then
  renamed over it — and only while its bytes are still the bytes the caller
  checked: they are compared again right before the rename, so a change that
  lands mid-write is refused, never overwritten (`Stale`);
* a new file is created with O_EXCL, so an existing file or a symlink planted
  at the target is never followed or overwritten; missing directories are made
  one component at a time, each checked the same way;
* a file name's slug is `a-z0-9` words joined by single hyphens, after common
  Latin letters are transliterated, cut at a word boundary to 60 characters.

Like the catalog, it needs nothing from Django.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import unicodedata
from pathlib import Path


class Refused(Exception):
    """A path that is not a plain path inside the site, or a write the filesystem refused."""


class NotFound(Refused):
    """The file (or the site directory) does not exist."""


class Stale(Exception):
    """The file is not the bytes the caller checked: it changed on disk since."""


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def root_of(root) -> Path:
    try:
        return Path(os.path.realpath(root, strict=True))
    except OSError as e:
        raise NotFound("the site directory is not reachable") from e


def segments(relative: str) -> list[str]:
    text = str(relative)
    parts = text.split("/")
    if not text or text.startswith("/") or "\0" in text or any(p in ("", ".", "..") for p in parts):
        raise Refused(f"{text!r} is not a plain path inside the site")
    return parts


def _inside(root: Path, real: str) -> bool:
    return real.startswith(str(root).rstrip("/") + "/")


def confined_file(root, relative: str) -> Path:
    """An existing regular file, reached through no symlink; its realpath."""
    base = root_of(root)
    current = base
    try:
        for part in segments(relative):
            current = current / part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise Refused(f"{relative} goes through a symlink")
        if not stat.S_ISREG(os.lstat(current).st_mode):
            raise Refused(f"{relative} is not a regular file")
    except (FileNotFoundError, NotADirectoryError) as e:
        raise NotFound(f"{relative} does not exist") from e
    except OSError as e:
        raise Refused(f"{relative} cannot be read ({type(e).__name__})") from e
    real = os.path.realpath(current)
    if not _inside(base, real):
        raise Refused(f"{relative} resolves outside the site")
    return Path(real)


def confined_target(root, relative: str, *, make_dirs: bool = False) -> Path:
    """Where `relative` may be written: every existing component is no symlink,
    the file itself (if there) is a regular file, and the directory resolves
    inside the root. With `make_dirs`, a missing directory is created, one
    checked component at a time."""
    base = root_of(root)
    parts = segments(relative)
    current = base
    for part in parts[:-1]:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            if not make_dirs:
                raise NotFound(f"{relative}: {part}/ does not exist") from None
            try:
                os.mkdir(current)
            except FileExistsError:
                pass  # made by someone else since the lstat above; it is checked next
            mode = os.lstat(current).st_mode
        if stat.S_ISLNK(mode):
            raise Refused(f"{relative} goes through a symlink")
        if not stat.S_ISDIR(mode):
            raise Refused(f"{relative}: {part} is not a directory")
    target = current / parts[-1]
    try:
        mode = os.lstat(target).st_mode
    except FileNotFoundError:
        mode = None
    if mode is not None and not stat.S_ISREG(mode):
        raise Refused(f"{relative} is not a regular file")
    if not _inside(base, os.path.realpath(target.parent) + "/"):
        raise Refused(f"{relative} resolves outside the site")
    return target


def read_bytes(root, relative: str) -> bytes | None:
    """The file's bytes, or None when there is no file at `relative`."""
    try:
        return confined_file(root, relative).read_bytes()
    except NotFound:
        return None


def write(root, relative: str, data: bytes, *, expected: bytes | None) -> Path:
    """Write `data` at `relative` while the file is still `expected` (None: it
    must not exist yet). Raises `Stale` when the file is not what the caller
    checked, `Refused` for a path or a write the rules refuse."""
    target = confined_target(root, relative, make_dirs=expected is None)
    if expected is None:
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError as e:
            raise Stale(f"{relative} appeared on disk while it was being written") from e
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return target
    _ensure_unchanged(root, relative, expected)
    mode = stat.S_IMODE(os.lstat(target).st_mode)
    temporary = target.parent / f".{target.name}.zer0-cms-{secrets.token_hex(6)}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _ensure_unchanged(root, relative, expected)
        os.replace(temporary, target)
    except OSError as e:
        raise Refused(f"could not write {relative}: {e.strerror or e}") from e
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def remove(root, relative: str, *, expected: bytes) -> None:
    """Delete the file at `relative` while it is still `expected`."""
    _ensure_unchanged(root, relative, expected)
    try:
        confined_file(root, relative).unlink()
    except OSError as e:
        raise Refused(f"could not delete {relative}: {e.strerror or e}") from e


def _ensure_unchanged(root, relative: str, expected: bytes) -> None:
    current = read_bytes(root, relative)
    if current != expected:
        raise Stale(f"{relative} changed on disk; sync the site, then try again")


# ── slugs ───────────────────────────────────────────────────────────────────

SLUG = re.compile(r"\A[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SLUG_MAX = 60
# Letters Unicode decomposition does not reduce to ASCII.
LETTERS = str.maketrans(
    {
        "ß": "ss",
        "ẞ": "ss",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
        "ø": "o",
        "Ø": "o",
        "đ": "d",
        "Đ": "d",
        "ð": "d",
        "Ð": "d",
        "þ": "th",
        "Þ": "th",
        "ł": "l",
        "Ł": "l",
        "ı": "i",
        "ħ": "h",
        "Ħ": "h",
        "ŀ": "l",
        "Ŀ": "l",
    }
)


def transliterate(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(text).translate(LETTERS))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def slugify(title: str) -> str:
    return truncate(re.sub(r"\A-+|-+\Z", "", re.sub(r"[^a-z0-9]+", "-", transliterate(title).lower())))


def slug_for(slug: str | None, title: str = "") -> str:
    """A file name's slug: the one given (transliterated) or the title's; raises
    ValueError for anything but `a-z0-9` words joined by single hyphens."""
    given = (slug or "").strip()
    candidate = truncate(transliterate(given).lower()) if given else slugify(title)
    if not SLUG.match(candidate):
        raise ValueError(f"invalid slug {candidate!r}: use a-z, 0-9 and single hyphens")
    return candidate


def truncate(slug: str) -> str:
    """Cut at the last hyphen at or before SLUG_MAX; a single longer word is cut hard."""
    if len(slug) <= SLUG_MAX:
        return slug
    head = slug[:SLUG_MAX]
    if slug[SLUG_MAX] == "-":
        cut = head
    else:
        at = head.rfind("-")
        cut = head[:at] if at > 0 else head
    return cut.rstrip("-")
