"""Proposing, applying, accepting and rejecting suggestions.

This is the extension's governance lifecycle on the content plane (M10):

| Extension (`src/core/governance`)       | Here                                       |
|-----------------------------------------|--------------------------------------------|
| a draft in the queue (`pending`)        | a `Suggestion` with status `pending`       |
| the brand guard (`guard.ts`)            | `guard.page_findings`, run at propose *and* at accept |
| approval (`approve`)                    | `accept()` — a person with edit rights     |
| the ledger (`ledger.ts`)                | the revision + `BlockProvenance` + the run |

`accept()` takes one or many pending suggestions on the same target and
applies them to the target's latest revision in order, as **one** new
revision authored by the agent user that proposed them — one revision per
accepted outcome (note §9, "revision bloat"). Every check is re-run at accept
time against the current state, because a suggestion made against revision 5
may meet revision 7: a block it replaces may be gone, and then it is refused
rather than applied somewhere it was not aimed.

For the review inbox (the studio's Review area, api/review.py): the
suggestions a person may decide are `Suggestion.objects.visible_to(user)`,
`describe` is one suggestion's change as before/after text for a diff,
measured against the target's latest revision, and `accept_run` accepts the
pending suggestions of a run that the person saw — one revision per target.

A decision a person may not make is `PermissionDenied` (its message never
names the target), a page someone has locked is `cms.services.PageLocked`, and
a decision the target's current state refuses is `SuggestionError`.
"""

import json
import uuid

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from wagtail.admin.rich_text.converters.editor_html import EditorHTMLConverter
from wagtail.blocks import RichTextBlock
from wagtail.log_actions import log
from wagtail.models import Revision

from agents.schema import META_FIELDS, BlockInvalid, validate_block

from .guard import builtin_bans, has_errors, markup_findings, page_findings, site_of, text_of
from .models import BlockProvenance, Suggestion, target_content_type

IMAGE_META_FIELDS = ("ai_alt", "ai_caption", "ai_tags")
TEXT_LIMITS = {"title": 255, "seo_title": 255, "search_description": 1000, "ai_summary": 4000}


class SuggestionError(ValueError):
    pass


# ── validation shared by propose, draft and accept ─────────────────────────


def clean_block(payload: dict) -> dict:
    """Validate {type, value} with the block itself; return the JSON form."""
    from cms.models import BasePage

    if not isinstance(payload, dict) or "type" not in payload or "value" not in payload:
        raise SuggestionError('a block is {"type": …, "value": …}')
    try:
        native = validate_block(payload["type"], payload["value"])
    except BlockInvalid as e:
        raise SuggestionError(str(e)) from e
    child = BasePage._meta.get_field("body").stream_block.child_blocks[payload["type"]]
    value = child.get_prep_value(native)
    if isinstance(child, RichTextBlock):
        # Rich text arrives in Wagtail's database format — the form every reader
        # of a page gets (the studio's API, the agent tools) — with internal
        # links as <a linktype="page" id="…">. The whitelist below reads the
        # editor's form (data-linktype), so the value is expanded to that form
        # first: a link or embed the block's features allow keeps its target,
        # and anything else is dropped, as Wagtail's own editor drops it.
        converter = EditorHTMLConverter(features=child.features)
        value = converter.to_database_format(converter.from_database_format(value))
    return {"type": payload["type"], "value": value}


def clean_meta(field: str, value):
    if field not in META_FIELDS:
        raise SuggestionError(f"op meta sets one of {', '.join(META_FIELDS)}; not {field!r}")
    if field == "ai_keywords":
        if not isinstance(value, list) or not all(isinstance(v, str) and 0 < len(v) <= 64 for v in value):
            raise SuggestionError("ai_keywords is a list of strings of 1–64 characters")
        return value
    if not isinstance(value, str):
        raise SuggestionError(f"{field} is a string")
    if len(value) > TEXT_LIMITS[field]:
        raise SuggestionError(f"{field} is at most {TEXT_LIMITS[field]} characters (got {len(value)})")
    if field == "title" and not value.strip():
        raise SuggestionError("a title cannot be empty")
    return value


def guard(value, block_type=None, before=None, site=None, builtin=True):
    """The checks every agent-proposed value passes, at propose time and again
    at accept time: the brand guard — on what a replace adds to the block it
    replaces (`before`), so the author's own words never block it, with the
    brand rules of the `site` it is for, and the built-in bans unless a book's
    chapter is exempt from them (`guard.builtin_bans`) — and, outside a code
    block, which shows markup rather than running it, no active markup at all."""
    text = text_of(value)
    old = None if before is None else text_of(before)
    findings = page_findings(text, before=old, site=site, builtin=builtin)
    findings += [] if block_type == "code" else markup_findings(text)
    if has_errors(findings):
        raise SuggestionError("brand guard: " + "; ".join(f["message"] for f in findings if f["level"] == "error"))
    return findings


def _block_ids(page) -> list[str]:
    return [b.id for b in page.body]


def _block_value(page, block_id):
    """The stored value of one of `page`'s blocks (None when it has no such block)."""
    return next((b["value"] for b in page.body.get_prep_value() if b.get("id") == block_id), None)


def apply_op(page, op: str, *, block_id="", payload=None, field="") -> str | None:
    """Apply one op to `page` in memory. Returns the id of the block it wrote."""
    if op == Suggestion.META:
        setattr(page, field, clean_meta(field, (payload or {}).get("value")))
        return None
    raw = list(page.body.get_prep_value())
    ids = [b.get("id") for b in raw]
    if op in (Suggestion.REPLACE, Suggestion.DELETE) or (op == Suggestion.INSERT and block_id):
        if block_id not in ids:
            raise SuggestionError(f"block {block_id!r} is not in the page's latest revision")
    written = None
    if op == Suggestion.INSERT:
        block = clean_block(payload)
        written = str(uuid.uuid4())
        at = ids.index(block_id) + 1 if block_id else len(raw)
        raw.insert(at, {**block, "id": written})
    elif op == Suggestion.REPLACE:
        block = clean_block(payload)
        at = ids.index(block_id)
        raw[at] = {**block, "id": block_id}
        written = block_id
    elif op == Suggestion.DELETE:
        raw.pop(ids.index(block_id))
    else:
        raise SuggestionError(f"unknown op {op!r}")
    page.body = raw
    return written


# ── propose ────────────────────────────────────────────────────────────────


def validate_proposal(target, op, block_id, payload, field):
    from cms.models import BasePage

    if op == Suggestion.EDGE:
        from graph.services import clean_edge

        return clean_edge(target, payload)
    if not isinstance(target, BasePage):
        if op != Suggestion.META or field not in IMAGE_META_FIELDS:
            raise SuggestionError(f"an image takes op meta on one of {', '.join(IMAGE_META_FIELDS)}")
        value = (payload or {}).get("value")
        if field == "ai_tags":
            if not isinstance(value, list) or not all(isinstance(v, str) and 0 < len(v) <= 64 for v in value):
                raise SuggestionError("ai_tags is a list of strings of 1–64 characters")
        elif not isinstance(value, str) or len(value) > 1000:
            raise SuggestionError(f"{field} is a string of at most 1000 characters")
        guard(value)
        return {"value": value}
    latest = target.get_latest_revision_as_object()
    site, builtin = site_of(target), builtin_bans(target)
    if op == Suggestion.META:
        value = clean_meta(field, (payload or {}).get("value"))
        guard(value, site=site, builtin=builtin)
        return {"value": value}
    if op in (Suggestion.REPLACE, Suggestion.DELETE) and block_id not in _block_ids(latest):
        raise SuggestionError(f"block {block_id!r} is not in page {target.pk}")
    if op == Suggestion.INSERT and block_id and block_id not in _block_ids(latest):
        raise SuggestionError(f"block {block_id!r} is not in page {target.pk}")
    if op in (Suggestion.INSERT, Suggestion.REPLACE):
        block = clean_block(payload)
        before = _block_value(latest, block_id) if op == Suggestion.REPLACE else None
        guard(block["value"], block["type"], before=before, site=site, builtin=builtin)
        return block
    if op == Suggestion.DELETE:
        return {}
    raise SuggestionError(f"unknown op {op!r}")


@transaction.atomic
def propose(*, target, op, user, run=None, agent=None, block_id="", payload=None, field="", rationale="") -> Suggestion:
    from cms.models import BasePage
    from outbox.services import emit

    clean = validate_proposal(target, op, block_id, payload, field)
    base = target.get_latest_revision() if hasattr(target, "get_latest_revision") else None
    suggestion = Suggestion.objects.create(
        target_ct=target_content_type(target),
        target_id=target.pk,
        op=op,
        block_id=block_id or "",
        field=field or "",
        payload=clean,
        rationale=rationale,
        run=run,
        agent=agent or (run.agent if run else None),
        base_revision=base,
        created_by=user,
    )
    log(suggestion, "zer0.suggestion.propose", user=user, data=_logged(suggestion))
    emit(
        "content.suggestion.created",
        subject=f"{'page' if isinstance(target, BasePage) else 'image'}:{target.pk}",
        version=2,
        data={
            "suggestion_id": str(suggestion.public_id),
            "target": f"{'page' if isinstance(target, BasePage) else 'image'}:{target.pk}",
            "page_id": target.pk if isinstance(target, BasePage) else None,
            "op": op,
            "block_id": block_id or None,
            "field": field or None,
            "agent": suggestion.agent.slug if suggestion.agent else "unknown",
            "run_id": str(run.public_id) if run else None,
        },
    )
    return suggestion


def _logged(suggestion) -> dict:
    """What a suggestion's log entry records beside who and when (`wagtail.log_actions.log`)."""
    return {
        "target": f"{suggestion.target_ct.model}:{suggestion.target_id}",
        "op": suggestion.op,
        "field": suggestion.field or None,
        "block_id": suggestion.block_id or None,
        "run_id": str(suggestion.run.public_id) if suggestion.run else None,
    }


# ── accept / reject ────────────────────────────────────────────────────────


def _record_human_step(runs, user, name, args, result):
    from agents.models import AgentStep

    for run in runs:
        AgentStep.objects.create(
            run=run, idx=run.next_step_index(), kind=AgentStep.HUMAN, name=name, args=args, result=result, user=user
        )


def can_decide(user, target) -> bool:
    if user is None or not user.is_authenticated or user.username.startswith("agent:"):
        return False  # a person decides; an agent never accepts its own (or another agent's) work
    if hasattr(target, "permissions_for_user"):
        return target.permissions_for_user(user).can_edit()
    return user.has_perm(f"{target._meta.app_label}.change_{target._meta.model_name}")


@transaction.atomic
def accept(suggestions, user):
    """Apply pending suggestions on one target as one revision. Returns the
    revision (pages) or the saved object (images, edges)."""
    from cms.models import BasePage
    from cms.services import save_draft, writable

    suggestions = list(
        Suggestion.objects.select_for_update().filter(pk__in=[s.pk for s in suggestions]).order_by("created_at", "id")
    )
    if not suggestions:
        raise SuggestionError("nothing to accept")
    targets = {(s.target_ct_id, s.target_id) for s in suggestions}
    if len(targets) != 1:
        raise SuggestionError("accept suggestions for one target at a time")
    if any(s.status != Suggestion.PENDING for s in suggestions):
        raise SuggestionError("only pending suggestions can be accepted")
    authors = {s.created_by_id for s in suggestions}
    if len(authors) != 1 or None in authors:
        raise SuggestionError("one accepted outcome has one author: accept one agent's suggestions together")
    target = suggestions[0].target
    target = target.specific if hasattr(target, "specific") else target
    if not can_decide(user, target):
        raise PermissionDenied("you may not decide suggestions on this target")
    author = suggestions[0].created_by

    edges = [s for s in suggestions if s.op == Suggestion.EDGE]
    rest = [s for s in suggestions if s.op != Suggestion.EDGE]
    if edges:
        from graph.services import upsert_edge

        for s in edges:
            upsert_edge(target, s.payload, source="agent", run=s.run)

    result = target
    written: list[tuple[Suggestion, str]] = []
    if rest and isinstance(target, BasePage):
        # The page's row lock, so a save or another accept that started from the
        # same revision runs after this one and builds on its revision; and a
        # page someone has locked is refused, as for any other writer.
        page = writable(target, user).get_latest_revision_as_object()
        site, builtin = site_of(target), builtin_bans(target)
        for s in rest:
            payload = s.payload
            if s.op == Suggestion.META:
                guard(payload.get("value"), site=site, builtin=builtin)
            elif s.op in (Suggestion.INSERT, Suggestion.REPLACE):
                before = _block_value(page, s.block_id) if s.op == Suggestion.REPLACE else None
                guard(payload.get("value"), payload.get("type"), before=before, site=site, builtin=builtin)
            block = apply_op(page, s.op, block_id=s.block_id, payload=payload, field=s.field)
            if block:
                written.append((s, block))
        result = save_draft(page, user=author)
        for s, block in written:
            BlockProvenance.objects.create(
                page_revision=result,
                block_id=block,
                suggestion=s,
                run=s.run,
                model=(s.agent.model if s.agent else ""),
                prompt_version=(s.run.prompt_version if s.run else ""),
                accepted_by=user,
            )
    elif rest:
        for s in rest:
            setattr(target, s.field, s.payload.get("value"))
        target.save()

    now = timezone.now()
    applied = result if isinstance(result, Revision) else None
    for s in suggestions:
        s.status = Suggestion.ACCEPTED
        s.decided_by = user
        s.decided_at = now
        s.applied_revision = applied
        s.save(update_fields=["status", "decided_by", "decided_at", "applied_revision"])
        log(s, "zer0.suggestion.accept", user=user, data={**_logged(s), "revision_id": applied.pk if applied else None})
    runs = {s.run for s in suggestions if s.run}
    _record_human_step(
        runs,
        user,
        "accept",
        {"suggestions": [str(s.public_id) for s in suggestions]},
        {"revision_id": applied.pk if applied else None},
    )
    return result


@transaction.atomic
def reject(suggestion, user, reason=""):
    suggestion = Suggestion.objects.select_for_update().get(pk=suggestion.pk)
    if suggestion.status != Suggestion.PENDING:
        raise SuggestionError("only pending suggestions can be rejected")
    target = suggestion.target
    target = target.specific if hasattr(target, "specific") else target
    if not can_decide(user, target):
        raise PermissionDenied("you may not decide suggestions on this target")
    suggestion.status = Suggestion.REJECTED
    suggestion.decided_by = user
    suggestion.decided_at = timezone.now()
    suggestion.error = reason
    suggestion.save(update_fields=["status", "decided_by", "decided_at", "error"])
    log(suggestion, "zer0.suggestion.reject", user=user, data={**_logged(suggestion), "reason": reason})
    if suggestion.run:
        _record_human_step(
            [suggestion.run], user, "reject", {"suggestion": str(suggestion.public_id)}, {"reason": reason}
        )
    return suggestion


def pending_for(target):
    return Suggestion.objects.filter(
        target_ct=target_content_type(target), target_id=target.pk, status=Suggestion.PENDING
    ).select_related("agent", "run")


def accept_rate(agent=None):
    """accepted / (accepted + rejected), overall or for one agent; None when
    nothing has been decided."""
    qs = Suggestion.objects.filter(status__in=[Suggestion.ACCEPTED, Suggestion.REJECTED])
    if agent is not None:
        qs = qs.filter(agent=agent)
    total = qs.count()
    return None if total == 0 else qs.filter(status=Suggestion.ACCEPTED).count() / total


# ── the review inbox ───────────────────────────────────────────────────────


def _text(block_type, value) -> str:
    from importers.markdown import block_to_markdown

    return block_to_markdown(block_type, value) or json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def _line(value) -> str:
    return ", ".join(str(v) for v in value) if isinstance(value, list) else str(value or "")


def _source(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def describe(suggestion, latest=None) -> dict:
    """The change as {kind, label, before, after, stale} text for a diff.
    `latest` is the target page's latest revision as an object — pass it when
    describing many suggestions on one page. `stale` means the block the
    suggestion aims at is gone, so accepting it would be refused. A replacement
    whose text reads the same but whose stored value differs (a link's target,
    the markup) is described by its stored values, labelled "markup only"."""
    from cms.models import BasePage

    target = latest
    if target is None:
        target = suggestion.target
        if isinstance(target, BasePage):
            target = target.get_latest_revision_as_object()
    op, payload = suggestion.op, suggestion.payload or {}
    if op == Suggestion.EDGE:
        return {"kind": "edge", "label": "graph edge", "before": "", "after": _text("edge", payload), "stale": False}
    if op == Suggestion.META:
        before = _line(getattr(target, suggestion.field, ""))
        after = _line(payload.get("value"))
        return {"kind": "field", "label": suggestion.field, "before": before, "after": after, "stale": False}
    blocks = {b["id"]: b for b in target.body.get_prep_value()} if isinstance(target, BasePage) else {}
    aimed = blocks.get(suggestion.block_id)
    if op == Suggestion.INSERT:
        where = "after a block" if suggestion.block_id else "at the end"
        return {
            "kind": "block",
            "label": f"insert {payload.get('type')} {where}",
            "before": "",
            "after": _text(payload.get("type"), payload.get("value")),
            "stale": bool(suggestion.block_id) and aimed is None,
        }
    label = f"{op} {aimed['type'] if aimed else 'block'}"
    before = _text(aimed["type"], aimed["value"]) if aimed else ""
    after = _text(payload.get("type"), payload.get("value")) if op == Suggestion.REPLACE else ""
    if op == Suggestion.REPLACE and aimed and before == after and aimed["value"] != payload.get("value"):
        # Only what the text cannot show changes — a link's target, the markup, a field outside the text — so
        # the diff is of the stored values: a person never accepts a change that reads as none.
        label, before, after = f"{label} (markup only)", _source(aimed["value"]), _source(payload.get("value"))
    return {"kind": "block", "label": label, "before": before, "after": after, "stale": aimed is None}


@transaction.atomic
def accept_run(run, user, ids) -> tuple[list[Suggestion], list]:
    """Accept the suggestions `ids` of `run` — the ones the person saw, never
    the rest of the run — as one revision per target (and per proposing user,
    as `accept` requires). Each must be a pending suggestion of the run that
    the person may decide. All of them, or none. `ids` are public ids.
    Returns the suggestions and what each `accept` returned."""
    wanted = {str(i) for i in ids}
    found = list(
        Suggestion.objects.visible_to(user)
        .filter(run=run, status=Suggestion.PENDING, public_id__in=wanted)
        .order_by("created_at", "id")
    )
    missing = ", ".join(sorted(wanted - {str(s.public_id) for s in found}))
    if not wanted or missing:
        raise SuggestionError(
            f"not pending suggestions of run {run.public_id} you may decide: {missing or 'none given'}"
        )
    groups: dict = {}
    for s in found:
        groups.setdefault((s.target_ct_id, s.target_id, s.created_by_id), []).append(s)
    return found, [accept(group, user) for group in groups.values()]
