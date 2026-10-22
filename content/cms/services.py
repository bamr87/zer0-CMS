"""Saving, publishing, scheduling and reverting pages, as one transaction each.

Every writer in the content plane — the suggestion accept flow, the agent
tools, the importers and the studio's API (api/pages.py) — goes through these
functions rather than calling `save_revision()` / `publish()` directly, so a
revision, its log entry, the graph rows and the outbox event either all commit
or none do.

`save_draft` and `publish` are the two primitives. The rest are what a person
does to a page in the studio or the extension: create it as a draft, save a
draft over the latest revision, publish the latest revision now, schedule it,
cancel the schedule, unpublish, and revert to an old revision — which is a new
draft revision, never a publish. Each checks the person's Wagtail page
permissions itself (`PermissionDenied`); bad input is Django's
`ValidationError`; a save against a revision someone else has since replaced is
`StaleRevision`.
"""

import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from wagtail.permission_policies.pages import PagePermissionPolicy


class StaleRevision(Exception):
    """The page has a newer revision than the one the caller edited."""


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
    """The pages a person may work with: Wagtail's explorable pages (those they
    hold a permission on, and their ancestors), without the tree's root."""
    return PagePermissionPolicy().explorable_instances(user).filter(depth__gt=1)


def _require(allowed: bool, message: str):
    if not allowed:
        raise PermissionDenied(message)


def creatable_types(parent, user) -> list:
    """The page models `user` may create under `parent`."""
    if not parent.permissions_for_user(user).can_add_subpage():
        return []
    return [model for model in parent.specific_class.creatable_subpage_models() if model.can_create_at(parent)]


def editable_fields(model) -> tuple[str, ...]:
    return model.shared_editor_fields + model.editor_fields


def apply_fields(page, values: dict):
    """Set editor fields on `page` in memory. Each value is parsed and validated
    by its own model field, so every error names the field it belongs to (an
    empty slug is left for Wagtail to make from the title)."""
    allowed = editable_fields(type(page))
    errors = {}
    for name, value in values.items():
        if name not in allowed:
            errors[name] = [f"{name} is not an editable field of a {page._meta.verbose_name}"]
            continue
        field = page._meta.get_field(name)
        try:
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
            errors[name] = e.messages
    if errors:
        raise ValidationError(errors)


def clean_body(page, blocks: list) -> list[dict]:
    """The body a person saved, as StreamField data. A block they did not touch
    is kept exactly as stored; a new or changed one is validated with the
    block's own rules (the same check a suggestion passes) and keeps its id, so
    pending suggestions and provenance still find it."""
    from suggestions.services import SuggestionError, clean_block

    stored = {b["id"]: b for b in page.body.get_prep_value()}
    cleaned, errors = [], {}
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors[f"body.{i}"] = ['a block is {"type": …, "value": …}']
            continue
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
    apply_fields(page, fields)
    if body:
        page.body = clean_body(page, body)
    parent.add_child(instance=page)
    save_draft(page, user, log_action="wagtail.create")
    return page


@transaction.atomic
def save_changes(page, user, *, fields: dict, body: list | None = None, base_revision_id=None):
    """A new draft revision over the latest one. Never publishes."""
    _require(page.permissions_for_user(user).can_edit(), f"{user} may not edit {page}")
    latest = page.get_latest_revision()
    if base_revision_id is not None and latest is not None and latest.pk != base_revision_id:
        raise StaleRevision(
            f"page {page.pk} has a newer revision ({latest.pk}) than the one edited ({base_revision_id})"
        )
    draft = page.get_latest_revision_as_object()
    apply_fields(draft, fields)
    if body is not None:
        draft.body = clean_body(draft, body)
    return save_draft(draft, user)


@transaction.atomic
def publish_now(page, user):
    """Publish the latest revision now — a future go-live time on it is cleared."""
    _require(page.permissions_for_user(user).can_publish(), f"{user} may not publish {page}")
    revision = page.get_latest_revision()
    draft = page.get_latest_revision_as_object()
    if revision is None or (draft.go_live_at and draft.go_live_at > timezone.now()):
        draft.go_live_at = None
        revision = save_draft(draft, user)
    revision.publish(user=user, skip_permission_checks=True)
    return revision


@transaction.atomic
def schedule(page, user, go_live_at, expire_at=None):
    """Publish the latest revision at `go_live_at`: Wagtail holds it until
    `publish_scheduled` (Celery beat, cms/tasks.py) finds it due."""
    _require(page.permissions_for_user(user).can_publish(), f"{user} may not publish {page}")
    if go_live_at <= timezone.now():
        raise ValidationError({"go_live_at": ["a schedule is in the future; publish now instead"]})
    draft = page.get_latest_revision_as_object()
    draft.go_live_at = go_live_at
    if expire_at is not None:
        draft.expire_at = expire_at
    revision = save_draft(draft, user)
    revision.publish(user=user, skip_permission_checks=True)
    return revision


@transaction.atomic
def unschedule(page, user):
    _require(page.permissions_for_user(user).can_unschedule(), f"{user} may not unschedule {page}")
    revision = page.scheduled_revision
    if revision is not None:
        revision.approved_go_live_at = None
        revision.save(user=user, update_fields=["approved_go_live_at"])
    return revision


@transaction.atomic
def unpublish(page, user):
    _require(page.permissions_for_user(user).can_unpublish(), f"{user} may not unpublish {page}")
    page.unpublish(user=user)


@transaction.atomic
def revert(page, revision, user):
    """A new draft revision with an old revision's content. Never publishes."""
    _require(page.permissions_for_user(user).can_edit(), f"{user} may not edit {page}")
    return save_draft(revision.as_object(), user, previous_revision=revision)
