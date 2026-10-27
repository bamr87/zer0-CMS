"""The outbox desk's services: the belt read and written through the library, trials and claim checks started here
and run by the worker, calibration, and the `published` handoff for a page that went live (outboxdesk/README.md).

Views, tasks and the consumer call these; nothing else touches the harness. The belt is read through the library —
`Belt.ledger`, `dead_letters`, `journey`, `write_belt_summary`, `to_cloudevent` — and the only belt files written
here are a sender's own outbox records (`Station.send`, which validates and refuses to overwrite) and, in the
worker, the relay's (`Belt.deliver`, the single writer of the ledger). A person sends as the editor station; a page
going live is announced by the publisher station, and only from the transactional outbox's event, never from the
request or the signal that published it. The claim desk only reads: a verdict is advice to the editor who decides,
and nothing here edits or publishes a page.
"""

import json
import re
import tempfile
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from wagtail.models import Page

from ops.errors import Conflict, Invalid, NotFound

from .harness import module, version
from .models import ClaimCheck, SentHandoff, Status, Trial

# What a person may send as the editor station: a new piece of work, an approval of one, a signal about one. The
# belt's other kinds are the pipeline stations' own.
SENDABLE = ("idea", "approval", "signal")
TRACEPARENT = re.compile(r"\A00-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}\Z")
# A published handoff's id is derived from the outbox event's, so a redelivered event finds it already sent.
PUBLISHED = uuid.UUID("6b1d6c55-8f3e-4a52-9a43-2f4f0b7c1e10")


def out_dir() -> Path:
    return Path(settings.OUTBOX_OUT_DIR)


def _queue(task, pk=None) -> None:
    """Start `task` once the change that asked for it has committed."""
    transaction.on_commit(lambda: task.delay(pk) if pk is not None else task.delay())


# ── the belt ───────────────────────────────────────────────────────────────


def open_belt():
    """The belt at OUTBOX_BELT_ROOT with every configured station, so the relay knows each recipient (it dead-letters
    a message to a station that has no directory)."""
    return module("belt").Belt(Path(settings.OUTBOX_BELT_ROOT), settings.OUTBOX_BELT_STATIONS)


def _undelivered(belt) -> int:
    """Outbox records the relay has neither delivered nor dead-lettered, keyed as the relay keys them."""
    seen = {row.get("id") for row in belt.ledger()} | {row.get("id") for row in belt.dead_letters()}
    waiting = 0
    for station in belt.relay.stations():
        for path in (belt.root / "stations" / station / "outbox").glob("*.json"):
            try:
                msg_id = json.loads(path.read_text(encoding="utf-8")).get("id") or f"no-id:{station}/{path.name}"
            except (OSError, ValueError):
                msg_id = f"unparseable:{station}/{path.name}"
            waiting += msg_id not in seen
    return waiting


def summary() -> dict:
    """The library's belt summary (delivered, dead letters, traces, kinds, gapless, unique), the stations, and how
    many records wait for the relay."""
    belt = open_belt()
    with tempfile.TemporaryDirectory() as scratch:  # write_belt_summary writes its answer to a file too
        found = module("belt").write_belt_summary(belt, Path(scratch) / "summary.json")
    return {
        **found,
        "kinds": [{"kind": kind, "count": count} for kind, count in found["kinds"].items()],
        "pending": _undelivered(belt),
        "stations": belt.relay.stations(),
        "editor": settings.OUTBOX_BELT_EDITOR,
        "harness": version(),
    }


def messages(*, kind: str = "", station: str = "", trace: str = "", oldest_first: bool = False) -> list[dict]:
    """Delivered messages, newest first: of a kind, from or to a station, on a trace."""
    rows = open_belt().ledger()
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if station:
        rows = [r for r in rows if r.get("from") == station or station in (r.get("to") or [])]
    if trace:
        rows = [r for r in rows if r.get("trace") == trace]
    return rows if oldest_first else rows[::-1]


def message(message_id: str) -> dict:
    """One delivered message, with its CloudEvents form."""
    row = next((r for r in open_belt().ledger() if r.get("id") == message_id), None)
    if row is None:
        raise NotFound(f"no delivered message {message_id}")
    return {**row, "cloudevent": module("belt").to_cloudevent(row)}


def journey(trace: str) -> list[dict]:
    """Every delivered message about one piece of work, in relay order."""
    rows = open_belt().journey(trace)
    if not rows:
        raise NotFound(f"no delivered message on trace {trace}")
    return rows


def dead_letters() -> list[dict]:
    return open_belt().dead_letters()[::-1]


def _refused(errors: list[str]) -> Invalid:
    """The library's reasons as the envelope's details, each on the field it is about."""

    def field(code: str) -> str | None:
        if code.startswith("missing:"):
            return code.removeprefix("missing:")
        for name in ("parent_id", "trace", "to", "payload", "ref"):
            if name in code:
                return name
        return None

    details = [{"field": field(code), "code": code, "message": code.replace("_", " ")} for code in errors]
    return Invalid("the belt refuses this handoff: " + ", ".join(errors), details=details)


def send(
    user,
    *,
    kind: str,
    to: list[str],
    subject: str = "",
    payload: dict | None = None,
    parent_id: str = "",
    trace: str = "",
    ref: dict | None = None,
    page=None,
) -> dict:
    """A handoff from the editor station, sent by a person: validated by the library, recorded with who sent it
    (`SentHandoff`, and `payload.by` on the belt), written to the editor's outbox for the relay to deliver. A reply
    (`parent_id`, a delivered message) keeps its parent's trace and, unless given one, its subject."""
    lib = module("belt")
    if kind not in SENDABLE:
        raise Invalid(
            f"a person sends {', '.join(SENDABLE)}", details=[{"field": "kind", "code": "invalid", "message": kind}]
        )
    belt = open_belt()
    known = set(belt.relay.stations())
    unknown = [d for d in to if d != "ledger" and d not in known]
    if unknown:
        why = f"no station {', '.join(unknown)} on the belt"
        raise Invalid(why, details=[{"field": "to", "code": "unknown_station", "message": why}])
    parent = None
    if parent_id:
        parent = next((r for r in belt.ledger() if r.get("id") == parent_id), None)
        if parent is None:
            why = f"no delivered message {parent_id} to answer"
            raise Invalid(why, details=[{"field": "parent_id", "code": "not_found", "message": why}])
        if trace and trace != parent["trace"]:
            why = "a reply keeps its parent's trace"
            raise Invalid(why, details=[{"field": "trace", "code": "mismatch", "message": why}])
        trace = parent["trace"]
    if page is not None:
        ref = {**(ref or {}), "page_id": page.pk, "url": page.full_url or page.url_path}
    fields = {"trace": trace} if trace else {}
    handoff = lib.Handoff(
        kind=kind,
        from_station=settings.OUTBOX_BELT_EDITOR,
        to=list(to),
        subject=subject or (parent["subject"] if parent else ""),
        payload={**(payload or {}), "by": user.get_username()},
        parent_id=parent_id or None,
        ref=ref or None,
        **fields,
    )
    data = handoff.to_dict()
    if errors := lib.validate_handoff(data):
        raise _refused(errors)
    # The row first: if writing the record fails, the request's transaction takes the row back with it.
    SentHandoff.objects.create(
        public_id=handoff.id, kind=kind, subject=handoff.subject, trace=handoff.trace, sent_by=user
    )
    belt.station(settings.OUTBOX_BELT_EDITOR).send(handoff)
    return data


def deliver() -> list[dict]:
    """Run the relay once (in the worker): every undelivered outbox record into its recipients' inboxes and the
    ledger, in one total order, or into the dead letters."""
    return open_belt().deliver()


def ask_delivery() -> int:
    """Queue a relay pass; returns how many records wait for it."""
    from .tasks import deliver_belt

    _queue(deliver_belt)
    return _undelivered(open_belt())


# ── a page went live (the transactional outbox's consumer) ──────────────────


def trace_of(traceparent: str | None) -> str:
    """The W3C trace id of a `traceparent`, or "" when there is none or it is not one."""
    match = TRACEPARENT.match(traceparent or "")
    return match.group(1) if match and match.group(1) != "0" * 32 else ""


def publish_page(envelope: dict) -> dict | None:
    """The `published` handoff for a `content.page.published` event, from the publisher station: `ref` names the
    page (its id and URL), the trace is the event's `traceparent`'s when it has one, and the parent is the latest
    delivered message about the page (`ref.page_id`) — an editor's approval, say — else the outbox event itself, since
    the belt parents every `published`. Idempotent: a redelivered event finds its handoff already in the outbox and
    sends nothing (None)."""
    lib = module("belt")
    data = envelope["data"]
    page_id = data["page_id"]
    handoff_id = str(uuid.uuid5(PUBLISHED, envelope["id"]))
    belt = open_belt()
    station = belt.station(settings.OUTBOX_BELT_PUBLISHER)
    if any(station.outbox.glob(f"*_{handoff_id}.json")):
        return None
    page = Page.objects.filter(pk=page_id).first()
    url = (page.full_url if page is not None else None) or data["url_path"]
    about = next((r for r in reversed(belt.ledger()) if (r.get("ref") or {}).get("page_id") == page_id), None)
    trace = trace_of(envelope.get("traceparent")) or (about["trace"] if about else uuid.UUID(envelope["id"]).hex)
    handoff = lib.Handoff(
        kind="published",
        from_station=settings.OUTBOX_BELT_PUBLISHER,
        to=list(settings.OUTBOX_BELT_PUBLISHED_TO),
        subject=envelope.get("subject") or f"page:{page_id}",
        payload={
            "canonical_url": url,
            "page_type": data["page_type"],
            "revision_id": data["revision_id"],
            "content_hash": data["content_hash"],
            "locale": data["locale"],
            "event_id": envelope["id"],
        },
        parent_id=about["id"] if about else envelope["id"],
        trace=trace,
        id=handoff_id,
        ref={"page_id": page_id, "url": url, "url_path": data["url_path"]},
    )
    station.send(handoff)
    return handoff.to_dict()


# ── trials and claim checks (started here, run by the worker) ───────────────


def _claim(model, pk: int):
    """Take a queued run for one worker: None when it is gone or another worker took it."""
    if model.objects.filter(pk=pk, status=Status.QUEUED).update(status=Status.RUNNING, started_at=timezone.now()) != 1:
        return None
    return model.objects.get(pk=pk)


def _finish(row, *, error: str = "", **fields):
    fields.update(status=Status.FAILED if error else Status.SUCCEEDED, error=error[:4000], finished_at=timezone.now())
    for name, value in fields.items():
        setattr(row, name, value)
    row.save(update_fields=list(fields))
    return row


def _failure(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def start_trial(user, task: dict, lag_b: int | None = None) -> Trial:
    from .tasks import run_trial

    trial = Trial.objects.create(requested_by=user, task=task, lag_b=lag_b)
    _queue(run_trial, trial.pk)
    return trial


def run_trial(pk: int) -> Trial | None:
    """The harness's arena on the trial's card (its three offline policy agents), scored at close."""
    trial = _claim(Trial, pk)
    if trial is None:
        return None
    arena = module("arena")
    card = {**trial.task, **({"lag_b": trial.lag_b} if trial.lag_b is not None else {})}
    run_id = f"trial-{trial.public_id}"
    try:
        result = arena.Arena(arena.new_run_dir(out_dir(), run_id), card).run()
    except Exception as exc:  # noqa: BLE001 — whatever the harness raised is the trial's failure, kept on its row
        return _finish(trial, error=_failure(exc), run_dir=f"runs/{run_id}")
    return _finish(trial, result=result, run_dir=f"runs/{run_id}")


def trial_ledger(trial: Trial) -> list[dict]:
    """The arena's ledger: every delivered message and tick, as `outbox watch` replays it."""
    if not trial.run_dir:
        return []
    return module("score").load_jsonl(out_dir() / trial.run_dir / "ledger.jsonl")


def start_claim_check(user, *, claims, timeline, closes_at_tick=8, lag_b=2, title="", author="", page=None):
    from .tasks import run_claim_check

    check = ClaimCheck.objects.create(
        requested_by=user,
        claims=claims,
        timeline=timeline,
        closes_at_tick=closes_at_tick,
        lag_b=lag_b,
        title=title,
        author=author,
        page=page,
    )
    _queue(run_claim_check, check.pk)
    return check


def run_claim_check(pk: int) -> ClaimCheck | None:
    """The claim desk over the check's claims: two verifiers raced per claim, a verdict each, pass only if all do."""
    check = _claim(ClaimCheck, pk)
    if check is None:
        return None
    desk = module("claimdesk")
    run_id = f"claims-{check.public_id}"
    try:
        root = module("arena").new_run_dir(out_dir(), run_id)
        report = desk.check_claims(
            check.claims, check.timeline, root, closes_at_tick=check.closes_at_tick, lag_b=check.lag_b
        )
    except Exception as exc:  # noqa: BLE001 — whatever the harness raised is the check's failure, kept on its row
        return _finish(check, error=_failure(exc), run_dir=f"runs/{run_id}")
    # Each verdict's `arena` is a path on this machine; the row keeps the run's directory instead.
    verdicts = [{k: v for k, v in verdict.items() if k != "arena"} for verdict in report["claims"]]
    return _finish(check, report={**report, "claims": verdicts}, passed=report["pass"], run_dir=f"runs/{run_id}")


def ask_resolution(check: ClaimCheck, truth: dict) -> ClaimCheck:
    """Resolve a checked claim set once the truth is known (in the worker): the truth names every claim, no more."""
    from .tasks import resolve_claim_check

    if check.status != Status.SUCCEEDED:
        raise Conflict("a check is resolved after it has run", code="claimcheck.not_checked")
    if check.resolution_status in (Status.QUEUED, Status.RUNNING):
        raise Conflict("this check is being resolved", code="claimcheck.resolving")
    ids = [claim["id"] for claim in check.claims]
    missing, extra = [i for i in ids if i not in truth], [k for k in truth if k not in ids]
    if missing or extra:
        problems = [f"no truth for {i}" for i in missing] + [f"no claim {k}" for k in extra]
        raise Invalid(
            "the truth names every claim of the check, and only those",
            details=[{"field": "truth", "code": "claims", "message": p} for p in problems],
        )
    check.truth, check.resolution_status, check.resolution_error = truth, Status.QUEUED, ""
    check.save(update_fields=["truth", "resolution_status", "resolution_error"])
    _queue(resolve_claim_check, check.pk)
    return check


def resolve_claim_check(pk: int) -> ClaimCheck | None:
    """Re-score each claim's arena from its own ledger against the truth: who was right, and Brier scores."""
    if ClaimCheck.objects.filter(pk=pk, resolution_status=Status.QUEUED).update(resolution_status=Status.RUNNING) != 1:
        return None
    check = ClaimCheck.objects.get(pk=pk)
    desk = module("claimdesk")
    try:
        resolutions = [
            {
                "claim_id": claim["id"],
                **desk.resolve(out_dir() / check.run_dir / desk.build_task(claim, [])["id"], check.truth[claim["id"]]),
            }
            for claim in check.claims
        ]
    except Exception as exc:  # noqa: BLE001 — whatever the harness raised is the resolution's failure, kept on its row
        check.resolution_status, check.resolution_error = Status.FAILED, _failure(exc)[:4000]
        check.save(update_fields=["resolution_status", "resolution_error"])
        return check
    check.resolutions, check.resolution_status, check.resolved_at = resolutions, Status.SUCCEEDED, timezone.now()
    check.save(update_fields=["resolutions", "resolution_status", "resolved_at"])
    return check


def calibration() -> dict:
    """Mean Brier per verifier and per draft author over every resolved check (the library's `calibration`). A claim
    is keyed by its check too, so two checks' claims that share an id never share an author."""
    resolutions, authors = [], {}
    rows = ClaimCheck.objects.filter(resolution_status=Status.SUCCEEDED).only("public_id", "author", "resolutions")
    for check in rows:
        for resolution in check.resolutions or []:
            key = f"{check.public_id}/{resolution['task_id']}"
            resolutions.append({**resolution, "task_id": key})
            authors[key] = check.author or "unknown"
    found = module("claimdesk").calibration(resolutions, authors)
    return {
        "resolved": found["resolved"],
        "winner_accuracy": found["winner_accuracy"],
        "verifiers": [{"name": name, **score} for name, score in found["verifiers"].items()],
        "authors": [{"name": name, **score} for name, score in found["authors"].items()],
    }
