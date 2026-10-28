"""The admins' sign-in, routed to allauth.

The Wagtail admin (`/admin/login/`) and the Django admin
(`/django-admin/login/`) each have a username-and-password form of their own,
which would start a session without a second factor, an IdP or a verified
address. Both answer a person who is signed out with a redirect to the
studio's sign-in (`LOGIN_URL`, allauth's headless API), carrying the page they
were going to as `next` when it is a path on this platform; someone signed in
goes on to the admin's own view, which sends them where they were going (or
refuses them, as it always did). Local accounts sign in there too — a password,
then the second factor if they have one — so they stay the fallback when an IdP
is down.
"""

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from wagtail.admin.views.account import LoginView


def sign_in_redirect(request, default_next: str):
    target = request.GET.get(REDIRECT_FIELD_NAME, default_next)
    if not target.startswith("/") or not url_has_allowed_host_and_scheme(target, allowed_hosts=None):
        target = default_next
    return HttpResponseRedirect(f"{settings.LOGIN_URL}?{urlencode({REDIRECT_FIELD_NAME: target})}")


def wagtail_admin_login(request, *args, **kwargs):
    if not request.user.is_authenticated:
        return sign_in_redirect(request, "/admin/")
    return LoginView.as_view()(request, *args, **kwargs)


def django_admin_login(request, *args, **kwargs):
    if not request.user.is_authenticated:
        return sign_in_redirect(request, "/django-admin/")
    return admin.site.login(request, *args, **kwargs)
