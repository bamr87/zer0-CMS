"""Who sees a site and who manages it — the one place sites are scoped.

A person sees the Wagtail sites whose root page they find in the studio (the
pages Wagtail's explorer would show them, `cms.services.visible_pages`): the
same rule the studio's site switcher has followed since P4. Managing a site —
registering one, syncing it, writing it back, running its doctor, changing its
registry fields and settings, and seeing and cancelling its jobs — also needs
the `sites.manage_site` permission (superusers hold every permission). Per-site
roles are G3's; until then a manager manages every site they see.
"""

from wagtail.models import Site

from cms.services import visible_pages

MANAGE = "sites.manage_site"


def visible_sites(user):
    if user is None or not user.is_authenticated:
        return Site.objects.none()
    return Site.objects.filter(root_page__in=visible_pages(user))


def manageable_sites(user):
    if user is None or not user.is_authenticated or not user.has_perm(MANAGE):
        return Site.objects.none()
    return Site.objects.all() if user.is_superuser else visible_sites(user)


def may_manage(user, site) -> bool:
    return manageable_sites(user).filter(pk=site.pk).exists()
