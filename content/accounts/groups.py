"""An OpenID Connect IdP's groups → Wagtail groups (`OIDC_GROUP_MAP`), at every
sign-in through that IdP.

The IdP is the source of truth for the groups the map names: a person signing
in is put in each mapped group a value of their groups claim (`OIDC_GROUPS_CLAIM`,
`groups` by default; read from the userinfo answer, then the ID token) grants,
and taken out of each mapped group it no longer grants. A group the map does
not name is never touched — what an operator gave by hand stays — and nothing
here makes anyone staff or a superuser. A mapped group that does not exist is
skipped with a warning (a typo in the map never creates a group); a sign-in
through GitHub, or with a password, changes no group.
"""

import logging

from allauth.account.signals import user_logged_in
from django.conf import settings
from django.contrib.auth.models import Group
from django.dispatch import receiver

from .adapter import is_oidc

log = logging.getLogger("accounts.groups")


def claimed_groups(extra_data: dict, claim: str) -> set[str]:
    """The values of `claim` in what the IdP answered (userinfo first, then the ID token)."""
    for part in ("userinfo", "id_token"):
        values = (extra_data.get(part) or {}).get(claim)
        if values is not None:
            return {values} if isinstance(values, str) else {str(v) for v in values}
    return set()


def sync(user, claimed: set[str], mapping: dict[str, list[str]]) -> tuple[set[str], set[str]]:
    """Make `user`'s mapped groups what `claimed` grants; returns the names added and removed."""
    managed = {name for names in mapping.values() for name in names}
    granted = {name for value in claimed for name in mapping.get(value, [])}
    existing = {group.name: group for group in Group.objects.filter(name__in=managed)}
    for missing in sorted(managed - set(existing)):
        log.warning("OIDC_GROUP_MAP names the group %r, which does not exist", missing)
    has = set(user.groups.filter(name__in=managed).values_list("name", flat=True))
    added = {name for name in granted - has if name in existing}
    removed = has - granted
    if added:
        user.groups.add(*(existing[name] for name in added))
    if removed:
        user.groups.remove(*(existing[name] for name in removed))
    return added, removed


@receiver(user_logged_in)
def sync_groups_from_the_idp(sender, request, user, sociallogin=None, **kwargs):
    if sociallogin is None or not settings.OIDC_GROUP_MAP or not is_oidc(sociallogin):
        return
    claimed = claimed_groups(sociallogin.account.extra_data or {}, settings.OIDC_GROUPS_CLAIM)
    added, removed = sync(user, claimed, settings.OIDC_GROUP_MAP)
    if added or removed:
        log.info(
            "groups from %s for %s: added %s, removed %s",
            sociallogin.account.provider,
            user.username,
            sorted(added),
            sorted(removed),
        )
