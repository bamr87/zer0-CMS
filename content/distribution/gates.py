"""The publish gates, in one fixed order, for every surface: the platform's
queue (`services.preview`), a site's own lane (`lane.pipeline`) and the tools.

A preview reports every blocker; a publish refuses on any. `force` lifts exactly
three, and only for one named post — a guard error a person has read, a ledger
entry they mean to post past, an unconfirmed attempt they checked did not post
— and never approval (a person's act) or arming (the operator's). The last
three kinds say a post is not cleared to go yet, not that anything is wrong with
it, so a rehearsal passes with only those.
"""

from dataclasses import dataclass

ORDER = (
    "config_error",
    "no_author",
    "source_missing",
    "ledger_unreadable",
    "guard_error",
    "already_published",
    "publish_unconfirmed",
    "status_not_accepted",
    "publish_disabled",
    "no_credential",
)
FORCEABLE = frozenset({"guard_error", "already_published", "publish_unconfirmed"})
LIVE_ONLY = frozenset({"publish_disabled", "no_credential"})
WAITING = frozenset({"status_not_accepted", "publish_disabled", "no_credential"})


@dataclass(frozen=True)
class Blocker:
    kind: str
    message: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message}


def ordered(blockers) -> list[Blocker]:
    return sorted(blockers, key=lambda b: ORDER.index(b.kind))  # sorted is stable: same kind keeps its order


def lifted(blockers, *, force: bool) -> list[Blocker]:
    return [b for b in blockers if not (force and b.kind in FORCEABLE)]


def problems(blockers) -> list[Blocker]:
    """What is wrong with a post, as opposed to what it is waiting for."""
    return [b for b in blockers if b.kind not in WAITING]
