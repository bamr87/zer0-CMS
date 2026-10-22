"""The ledger as a file: what has already been published, keyed by canonical
URL — or `draft:<path>` for a text update, which has no URL of its own.

The key is the coordination. Whichever lane publishes a URL first writes it;
every other lane — the VS Code extension, a site's CI (`manage.py linkedin`),
the platform (`distribution.services`, which also keeps its own ledger rows) —
looks it up and skips. That only works if they agree on the file, so:

* it is written as Python's `json.dump(data, indent=2, sort_keys=True)` — with
  `ensure_ascii` — plus a newline (`serialize`), byte for byte what the
  extension's `saveLedger` and the Ruby lane wrote;
* an entry carries the post URN under both `linkedin_urn` (the name live
  ledgers hold) and `urn` (the name the extension reads); a reader takes either;
* a write is a read-modify-write under an exclusive lock outside the
  repository, then an atomic rename, and every key it does not own — metadata
  other lanes wrote, of any shape — survives it;
* an attempt the target did not confirm is an entry with `state: unconfirmed`,
  `attempted_at` and `error` but no URN: no reader counts it as published, and
  every lane refuses that key until a person records the post or forces past it;
* an unreadable ledger — present but not a JSON object — is never read as
  "nothing published" (that would re-post every accepted draft) and never
  rewritten: `readable` is False, and publishing refuses.
"""

import fcntl
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

META = "_meta"


class LedgerError(Exception):
    """The ledger cannot be read or written; the message says which file and why."""


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def serialize(data: dict) -> str:
    """Python's `json.dump(…, indent=2, sort_keys=True)` (`ensure_ascii` is its default) and a newline."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def urn_of(entry) -> str | None:
    if not isinstance(entry, dict):
        return None
    return next((str(entry[k]) for k in ("linkedin_urn", "urn") if entry.get(k)), None)


def entry_for(*, urn, kind, target, author=None, source_file=None, image_urn=None, now=None) -> dict:
    """A published entry, as every lane writes one: a re-publish is a new fact about the key, so nothing from an
    older entry is merged in, and an absent option is left out rather than written as null."""
    entry = {"posted_at": stamp(now), "target": target, "type": kind, "urn": urn}
    if target == "linkedin":
        entry["linkedin_urn"] = urn
    for key, value in (("author", author), ("source_file", source_file), ("image_urn", image_urn)):
        if value:
            entry[key] = value
    return entry


def unconfirmed_entry(*, error, kind, target, author=None, source_file=None, now=None) -> dict:
    entry = {
        "state": "unconfirmed",
        "attempted_at": stamp(now),
        "error": str(error)[:300],
        "target": target,
        "type": kind,
    }
    for key, value in (("author", author), ("source_file", source_file)):
        if value:
            entry[key] = value
    return entry


class Ledger:
    def __init__(self, path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def readable(self) -> bool:
        if not self.exists():
            return True
        try:
            return isinstance(json.loads(self.path.read_text(encoding="utf-8")), dict)
        except (OSError, ValueError):
            return False

    def raw(self) -> dict:
        """The whole file as parsed, so a rewrite keeps keys of any shape it does not own."""
        if not self.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def entries(self) -> dict:
        return {key: value for key, value in self.raw().items() if isinstance(value, dict)}

    def entry(self, key):
        return self.entries().get(str(key))

    def urn_for(self, key) -> str | None:
        return urn_of(self.entry(key))

    def unconfirmed(self, key):
        entry = self.entry(key)
        return entry if entry and urn_of(entry) is None and entry.get("state") == "unconfirmed" else None

    def shares(self) -> list[tuple[str, dict]]:
        """The published shares, and only those: `_`-prefixed metadata and rows without a URN are skipped — the
        only correct way to enumerate the file."""
        out = []
        for key, entry in self.entries().items():
            urn = urn_of(entry)
            if not key.startswith("_") and urn:
                out.append((key, {**entry, "urn": urn}))
        return out

    def record(self, key, entry: dict) -> dict:
        if not key or str(key).startswith("_"):
            raise ValueError("a ledger key is a URL or draft:<path>, never empty or _-prefixed")

        def change(data):
            data[str(key)] = entry

        self.mutate(change)
        return entry

    def mark_unconfirmed(self, key, entry: dict) -> dict:
        """Write down that an attempt may have posted — never over a recorded post."""

        def change(data):
            if not urn_of(data.get(str(key))):
                data[str(key)] = entry

        self.mutate(change)
        return entry

    def write_meta(self, patch: dict) -> None:
        self.mutate(lambda data: data.__setitem__(META, {**(data.get(META) or {}), **patch}))

    def mutate(self, change) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(str(self.path.resolve()).encode()).hexdigest()[:16]
        lock = Path(tempfile.gettempdir()) / f"zer0-cms-ledger-{digest}.lock"  # outside the repository
        with open(lock, "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if not self.readable:
                raise LedgerError(f"{self.path.name} is not valid JSON — refusing to rewrite it")
            data = self.raw()
            change(data)
            self._write(serialize(data))

    def _write(self, text: str) -> None:
        mode = (self.path.stat().st_mode & 0o777) if self.exists() else 0o644
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temp, mode)
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
