"""Agent users and their permissions: `agent:<slug>` in `Agents`.

Every agent is an ordinary, active, non-staff, non-superuser Django user
with an unusable password. It belongs to the `Agents` group (a marker) and
to its own `agent:<slug>` group, which carries what the agent may do in
Wagtail's own terms: page permissions (`add`/`change`, never `publish`, at the
root unless narrowed) and collection permissions for images. Because tools
check permissions as that user, narrowing a group's page permissions to a
section is how an editor confines an agent — no harness code involved.

`ensure_principal` is idempotent. It runs after every `migrate` for the
standard agents (the plan's data migration, done at `post_migrate` because
Wagtail's permission rows do not exist until then) and from `sync_agents` for
every definition on disk.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

AGENTS_GROUP = "Agents"
STANDARD_AGENTS = {
    # The four the plan names (M9); every other definition gets the defaults
    # of its role from ROLE_PERMISSIONS when `sync_agents` provisions it.
    # slug: (page permissions, image permissions)
    "drafter": (("add_page", "change_page"), ("add_image", "choose_image")),
    "editor": (("change_page",), ("choose_image",)),
    "seo": (("change_page",), ("choose_image",)),
    "review": ((), ()),
}
ROLE_PERMISSIONS = {
    "author": (("change_page",), ("choose_image",)),
    "review": ((), ()),
    "enrich": (("change_page",), ("change_image", "choose_image")),
}
LEGACY_IMPORT_USER = "legacy:import"


def _permission(model, codename: str) -> Permission:
    # get_for_model and get_or_create, because at post_migrate time Django
    # may not have created this app's content types and permissions yet.
    ct = ContentType.objects.get_for_model(model, for_concrete_model=False)
    perm, _ = Permission.objects.get_or_create(content_type=ct, codename=codename, defaults={"name": codename})
    return perm


@transaction.atomic
def ensure_principal(slug: str, page_perms=None, image_perms=None, role=None):
    """Create or refresh `agent:<slug>` and its group; returns the user."""
    from wagtail.images import get_image_model
    from wagtail.models import Collection, GroupCollectionPermission, GroupPagePermission, Page

    image_model = get_image_model()

    defaults = STANDARD_AGENTS.get(slug) or ROLE_PERMISSIONS.get(role or "author")
    page_perms = defaults[0] if page_perms is None else tuple(page_perms)
    image_perms = defaults[1] if image_perms is None else tuple(image_perms)

    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=f"agent:{slug}", defaults={"is_active": True, "is_staff": False, "is_superuser": False}
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    if user.is_superuser or user.is_staff:
        # Never: an agent that inherited admin rights is a permission leak.
        user.is_superuser = False
        user.is_staff = False
        user.save(update_fields=["is_superuser", "is_staff"])

    marker, _ = Group.objects.get_or_create(name=AGENTS_GROUP)
    own, own_created = Group.objects.get_or_create(name=f"agent:{slug}")
    user.groups.add(marker, own)

    if own_created:
        # Only on first creation: after that, an editor owns the group's
        # permissions and re-running sync must not widen what they narrowed.
        root = Page.get_first_root_node()
        if root is not None:
            for codename in page_perms:
                GroupPagePermission.objects.get_or_create(group=own, page=root, permission=_permission(Page, codename))
        root_collection = Collection.get_first_root_node()
        if root_collection is not None:
            for codename in image_perms:
                GroupCollectionPermission.objects.get_or_create(
                    group=own, collection=root_collection, permission=_permission(image_model, codename)
                )
        # Wagtail checks the model-level image permission too.
        for codename in image_perms:
            own.permissions.add(_permission(image_model, codename))
    return user


def ensure_legacy_import_user():
    """The author of revisions the importers recreate from history."""
    User = get_user_model()
    user, created = User.objects.get_or_create(username=LEGACY_IMPORT_USER, defaults={"is_active": False})
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def ensure_standard_principals(**kwargs):
    for slug in STANDARD_AGENTS:
        ensure_principal(slug)
    ensure_legacy_import_user()


def is_agent_user(user) -> bool:
    return bool(
        user is not None
        and user.is_authenticated
        and user.is_active
        and not user.is_superuser
        and user.username.startswith("agent:")
    )
