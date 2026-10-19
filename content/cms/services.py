"""Saving and publishing pages, as one transaction each.

Every writer in the content plane — the suggestion accept flow, the agent
tools, the importers — goes through these two functions rather than calling
`save_revision()` / `publish()` directly, so a revision, its log entry, the
graph rows and the outbox event either all commit or none do.
"""

from django.db import transaction


@transaction.atomic
def save_draft(page, user, log_action=True, changed=True):
    """A new draft revision authored by `user`. Validates the page first."""
    page.full_clean()
    return page.save_revision(user=user, log_action=log_action, changed=changed, clean=False)


@transaction.atomic
def publish(page, user, log_action=True):
    """A new revision authored by `user`, published."""
    revision = save_draft(page, user, log_action=log_action)
    revision.publish(user=user, log_action=log_action, skip_permission_checks=True)
    return revision
