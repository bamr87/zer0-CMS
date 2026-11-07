"""Syncing a book's chapters to Substack through one adapter — Design for
Failure: detect, contain, recover, log.

* **Idempotent.** The ledger (`distribution/ledger.py`'s file and byte format,
  `target: substack`) is keyed by each chapter's canonical URL and keeps the
  content digest and the state on Substack; an unchanged chapter in the same
  state is not sent again. The feed is the exception: it is the whole set of
  published chapters every time (`always_full`), so it re-renders them all.
* **Detect.** Every failure is a `SubstackError` that says whether a retry may
  help (`retryable`) and whether the write may have landed (`doubt`).
* **Contain.** One chapter's failure never stops the others; the result lists
  each chapter's outcome.
* **Recover.** A retryable failure with no doubt is tried again with
  exponential backoff (`attempts`, `backoff`). A doubtful one is never retried:
  it is ledgered `unconfirmed`, and that key is refused until a person checks
  Substack and syncs again with `force`.
* **Log.** One line per outcome through `logging` (whose handler redacts token
  shapes); no message here ever carries the session cookie.
"""

import logging
import time
from dataclasses import dataclass, field

from distribution.ledger import Ledger, LedgerError, stamp, unconfirmed_entry

from .adapters import Skipped, SubstackAdapter, SubstackError
from .chapters import Chapter

log = logging.getLogger(__name__)
TARGET = "substack"


@dataclass
class Outcome:
    key: str
    chapter: int
    status: str  # sent | unchanged | skipped | blocked | failed | unconfirmed
    detail: str = ""


@dataclass
class Report:
    adapter: str
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(o.status in ("failed", "unconfirmed", "blocked") for o in self.outcomes)

    def counts(self) -> dict:
        out: dict = {}
        for o in self.outcomes:
            out[o.status] = out.get(o.status, 0) + 1
        return out


def sync(
    chapters: list[Chapter],
    adapter: SubstackAdapter,
    ledger: Ledger,
    *,
    force: bool = False,
    dry_run: bool = False,
    attempts: int = 3,
    backoff: float = 2.0,
    sleep=time.sleep,
) -> Report:
    if not ledger.readable:
        raise LedgerError(f"{ledger.path.name} is not valid JSON — refusing to sync over it")
    report = Report(adapter=adapter.name)
    always_full = getattr(adapter, "always_full", adapter.name == "feed")
    for chapter in chapters:
        report.outcomes.append(
            _one(
                chapter,
                adapter,
                ledger,
                force=force,
                dry_run=dry_run,
                always_full=always_full,
                attempts=max(1, attempts),
                backoff=backoff,
                sleep=sleep,
            )
        )
    if not dry_run:
        adapter.finish()
    for o in report.outcomes:
        level = logging.WARNING if o.status in ("failed", "unconfirmed", "blocked") else logging.INFO
        log.log(level, "substack[%s]: chapter %s %s %s", adapter.name, o.chapter, o.status, o.detail)
    return report


def _one(chapter, adapter, ledger, *, force, dry_run, always_full, attempts, backoff, sleep) -> Outcome:
    key = chapter.key
    previous = ledger.entry(key)
    if ledger.unconfirmed(key) and not force:
        return Outcome(
            key,
            chapter.number,
            "blocked",
            "an earlier attempt may have posted: check Substack, then sync again with --force",
        )
    if (
        not always_full
        and previous
        and previous.get("urn")
        and previous.get("digest") == chapter.digest
        and previous.get("wanted") == chapter.state
        and not force
    ):
        return Outcome(key, chapter.number, "unchanged")
    if dry_run:
        return Outcome(key, chapter.number, "sent", "dry run: nothing written")
    for attempt in range(1, attempts + 1):
        try:
            pushed = adapter.push(chapter, previous)
        except Skipped as e:
            return Outcome(key, chapter.number, "skipped", str(e))
        except SubstackError as e:
            if e.doubt:
                ledger.mark_unconfirmed(
                    key,
                    {
                        **unconfirmed_entry(
                            error=e.message, kind="article", target=TARGET, source_file=chapter.source_file
                        )
                    },
                )
                return Outcome(key, chapter.number, "unconfirmed", e.message)
            if e.retryable and attempt < attempts:
                sleep(backoff * 2 ** (attempt - 1))
                continue
            return Outcome(key, chapter.number, "failed", e.message)
        entry = {
            "posted_at": stamp(),
            "target": TARGET,
            "type": "article",
            "urn": pushed.external_id,
            "source_file": chapter.source_file,
            "digest": chapter.digest,
            "wanted": chapter.state,
            "substack_state": pushed.state,
            "adapter": adapter.name,
        }
        if pushed.url:
            entry["url"] = pushed.url
        ledger.record(key, entry)
        return Outcome(key, chapter.number, "sent", pushed.state)
    return Outcome(key, chapter.number, "failed", "no attempt left")  # unreachable: the loop always returns
