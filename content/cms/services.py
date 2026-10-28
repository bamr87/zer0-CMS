"""Saving, publishing, scheduling and reverting pages, as one transaction each.

Every writer in the content plane — the suggestion accept flow, the agent
tools, the importers and the studio's API (api/pages.py) — goes through these
functions rather than calling `save_revision()` / `publish()` directly, so a
revision, its log entry, the graph rows and the outbox event either all commit
or none do.

`save_draft` and `publish` are the two primitives. The rest are what a person
does to a page in the studio or the extension: create it as a draft, save a
draft over the latest revision, publish the latest revision now, schedule it
(and its expiry), cancel the schedule, unpublish, and revert to an old revision
— which is a new draft revision, never a publish. Each checks the person's
Wagtail page permissions itself (`PermissionDenied`); bad input is Django's
`ValidationError`; a save against a revision someone else has since replaced is
`StaleRevision`.

Every writer of an existing page starts with `writable()`: it takes the page
row's lock for the transaction, so two writers that start from the same
revision run one after the other (the second save is then stale, the second
accept builds on the first's revision), and it refuses a page that a Wagtail
lock keeps from this person — another person's lock, a workflow task's, or a
scheduled publish's (`PageLocked`), as Wagtail's own editor does. Cancelling a
schedule takes the row lock alone: it is how a scheduled page's lock is lifted.
"""

import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags
from wagtail.permission_policies.pages import PagePermissionPolicy

from . import files


class StaleRevision(Exception):
    """The page has a newer revision than the one the caller edited."""


class PageLocked(PermissionDenied):
    """A Wagtail lock keeps this person from changing the page; says why."""


@transaction.atomic
def save_draft(page, user, log_action=True, changed=True, previous_revision=None):
    """A new draft revision authored by `user`. Validates the page first."""
    page.full_clean()
    return page.save_revision(
        user=user, log_action=log_action, changed=changed, clean=False, previous_revision=previous_revision
    )


@transaction.atomic
def publish(page, user, log_action=True):
    """A new revision authored by `user`, published."""
    revision = save_draft(page, user, log_action=log_action)
    revision.publish(user=user, log_action=log_action, skip_permission_checks=True)
    return revision


# ── what a person does in the studio ───────────────────────────────────────


def visible_pages(user):
    """The pages a person finds in the studio: Wagtail's explorable pages (those
    they hold a permission on, and the ancestors that lead to them) of the
    platform's own page types — not the tree's root, nor the placeholder page
    Wagtail's first migration makes. Opening one needs more (api/pages.py)."""
    from .models import BasePage

    return PagePermissionPolicy().explorable_instances(user).type(BasePage)


def lock_for(page, user) -> str | None:
    """Why a Wagtail lock keeps `user` from changing `page`, or None."""
    lock = page.get_lock()
    if lock is None or not lock.for_user(user):
        return None
    return strip_tags(lock.get_message(user) or "") or f"{page} is locked"


def writable(page, user):
    """`page` as it is now, its row locked until the transaction ends; refused
    (`PageLocked`) when a Wagtail lock keeps `user` from changing it."""
    page = type(page).objects.select_for_update().get(pk=page.pk)
    if (reason := lock_for(page, user)) is not None:
        raise PageLocked(reason)
    return page


def _require(allowed: bool, message: str):
    if not allowed:
        raise PermissionDenied(message)


def creatable_types(parent, user) -> list:
    """The page models `user` may create under `parent`."""
    if not parent.permissions_for_user(user).can_add_subpage():
        return []
    return [model for model in parent.specific_class.creatable_subpage_models() if model.can_create_at(parent)]


def editable_fields(model) -> tuple[str, ...]:
    return model.shared_editor_fields + model.editor_fields + model.file_editor_fields


def apply_fields(page, values: dict, parent=None):
    """Set editor fields on `page` in memory. Each value is parsed and validated
    by its own model field, so every error names the field it belongs to (an
    empty slug is left for Wagtail to make from the title). The page's file —
    `file_path` and raw `front_matter` — is checked against its site
    (cms/files.py; `parent` is where a new page goes), and a dated file name
    against the date whenever either changes."""
    allowed = editable_fields(type(page))
    errors = {}
    dated = (page.legacy_path, getattr(page, "date", None))
    for name, value in values.items():
        if name not in allowed:
            errors[name] = [f"{name} is not an editable field of a {page._meta.verbose_name}"]
            continue
        try:
            if name == "file_path":
                files.set_file_path(page, value, parent)
                continue
            if name == "front_matter":
                files.set_front_matter(page, value)
                continue
            field = page._meta.get_field(name)
            if name == "tags":
                if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
                    raise ValidationError("tags is a list of names")
                page.tags.set([v.strip() for v in value])
            elif field.many_to_many:
                wanted = set(value or [])
                found = list(field.related_model.objects.filter(pk__in=wanted))
                if len(found) != len(wanted):
                    raise ValidationError(f"unknown {field.related_model._meta.verbose_name} id")
                getattr(page, name).set(found)
            elif name == "ai_keywords":
                if not isinstance(value, list) or not all(isinstance(v, str) and 0 < len(v) <= 64 for v in value):
                    raise ValidationError("ai_keywords is a list of strings of 1–64 characters")
                page.ai_keywords = value
            else:
                value = "" if value is None and not field.null else value
                setattr(
                    page, name, field.to_python(value) if name == "slug" and not value else field.clean(value, page)
                )
        except ValidationError as e:
            errors.update(e.message_dict if hasattr(e, "error_dict") else {name: e.messages})
    redated = (page.legacy_path, getattr(page, "date", None)) != dated
    if redated and not errors.keys() & {"file_path", "date"} and (problem := files.date_problem(page)) is not None:
        errors["file_path" if "file_path" in values else "date"] = [problem]
    if errors:
        raise ValidationError(errors)


def clean_body(page, blocks: list) -> list[dict]:
    """The body a person saved, as StreamField data. A block they did not touch
    is kept exactly as stored; a new or changed one is validated with the
    block's own rules (the same check a suggestion passes) and keeps its id, so
    pending suggestions and provenance still find it."""
    from suggestions.services import SuggestionError, clean_block

    stored = {b["id"]: b for b in page.body.get_prep_value()}
    cleaned, errors, seen = [], {}, set()
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors[f"body.{i}"] = ['a block is {"type": …, "value": …}']
            continue
        if block.get("id") and block["id"] in seen:  # suggestions and provenance find a block by its id
            errors[f"body.{i}"] = [f"block id {block['id']!r} is used twice; every block has its own"]
            continue
        seen.add(block.get("id"))
        same = stored.get(block.get("id"))
        if same is not None and same["type"] == block.get("type") and same["value"] == block.get("value"):
            cleaned.append(same)
            continue
        try:
            value = clean_block({"type": block.get("type"), "value": block.get("value")})
        except SuggestionError as e:
            errors[f"body.{i}"] = [str(e)]
            continue
        cleaned.append({**value, "id": block.get("id") or str(uuid.uuid4())})
    if errors:
        raise ValidationError(errors)
    return cleaned


@transaction.atomic
def create_draft(parent, model, user, *, fields: dict, body: list | None = None):
    """A new page under `parent`, not live, with one draft revision."""
    _require(model in creatable_types(parent, user), f"{user} may not create a {model._meta.verbose_name} here")
    page = model(owner=user, live=False, has_unpublished_changes=True)
    apply_fields(page, fields, parent=parent)
    if body:
        page.body = clean_body(page, body)
    parent.add_child(instance=page)
    save_draft(page, user, log_action="wagtail.create")
    return page


@transaction.atomic
def save_changes(page, user, *, base_revision_id, fields: dict, body: list | None = None):
    """A new draft revision over the latest one, which must be the revision the
    person edited (`base_revision_id`; None only for a page without one).
    Never publishes."""
    _require(page.permissions_for_user(user).can_edit(), f"{user} may not edit {page}")
    page = writable(page, user)
    if page.latest_revision_id != base_revision_id:
        raise StaleRevision(
            f"page {page.pk} has a newer revision ({page.latest_revision_id}) than the one edited ({base_revision_id})"
        )
    draft = page.get_latest_revision_as_object()
    apply_fields(draft, fields)
    if body is not None:
        draft.body = clean_body(draft, body)
    return save_draft(draft, user)


@transaction.atomic
def publish_now(page, user):
    """Publish the latest revision now. A future go-live time on it is cleared,
    and so is an expiry that has passed, or the next sweep would take the page
    straight down again."""
    _require(page.permissions_for_user(user).can_publish(), f"{user} may not publish {page}")
    page = writable(page, user)
    revision = page.get_latest_revision()
    draft = page.get_latest_revision_as_object()
    now = timezone.now()
    expired = draft.expire_at is not None and draft.expire_at <= now
    if revision is None or (draft.go_live_at and draft.go_live_at > now) or expired:
        draft.go_live_at = None
        draft.expire_at = None if expired else draft.expire_at
        revision = save_draft(draft, user)
    revision.publish(user=user, skip_permission_checks=True)
    return revision


@transaction.atomic
def schedule(page, user, go_live_at=None, expire_at=None):
    """Publish the latest revision at `go_live_at` (now, when it is None) and
    take the page down at `expire_at`. Wagtail holds a future revision until
    `publish_scheduled` (Celery beat, cms/tasks.py) finds it due, and takes a
    live page down once its expiry has passed; an expiry belongs to the
    revision that goes live, as in Wagtail."""
    _require(page.permissions_for_user(user).can_publish(), f"{user} may not publish {page}")
    page = writable(page, user)
    now = timezone.now()
    if go_live_at is None and expire_at is None:
        raise ValidationError({"go_live_at": ["give a time to publish at, a time to take the page down at, or both"]})
    if go_live_at is not None and go_live_at <= now:
        raise ValidationError({"go_live_at": ["a schedule is in the future; publish now instead"]})
    if expire_at is not None and expire_at <= (go_live_at or now):
        raise ValidationError({"expire_at": ["the page comes down after it goes live"]})
    draft = page.get_latest_revision_as_object()
    draft.go_live_at = go_live_at
    if expire_at is not None:
        draft.expire_at = expire_at
    revision = save_draft(draft, user)
    revision.publish(user=user, skip_permission_checks=True)
    return revision


@transaction.atomic
def unschedule(page, user):
    """Cancel a scheduled publish — the one change a scheduled page's lock
    allows, since it is how the lock is lifted (as in Wagtail)."""
    _require(page.permissions_for_user(user).can_unschedule(), f"{user} may not unschedule {page}")
    page = type(page).objects.select_for_update().get(pk=page.pk)
    revision = page.scheduled_revision
    if revision is not None:
        revision.approved_go_live_at = None
        revision.save(user=user, update_fields=["approved_go_live_at"])
    return revision


@transaction.atomic
def unpublish(page, user):
    page = writable(page, user)  # first: Wagtail's can_unpublish() is false on a locked page, and the lock says why
    _require(page.permissions_for_user(user).can_unpublish(), f"{user} may not unpublish {page}")
    page.unpublish(user=user)


@transaction.atomic
def revert(page, revision, user):
    """A new draft revision with an old revision's content. Never publishes."""
    _require(page.permissions_for_user(user).can_edit(), f"{user} may not edit {page}")
    writable(page, user)
    return save_draft(revision.as_object(), user, previous_revision=revision)
