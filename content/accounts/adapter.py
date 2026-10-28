"""The platform's django-allauth adapters: what allauth asks this platform
rather than its settings.

- **Agents never sign in.** An agent principal (`agent:<slug>`) acts through
  its token and the tool registry, never through a person's sign-in: its
  password is unusable, and even one given a password (or reached by a code,
  a provider or a passkey) is refused here, at every route allauth has.
- **Sign-up is closed unless the deployment opens it** (`SIGNUP_OPEN`). An
  OpenID Connect IdP an operator configured provisions its people anyway —
  that is what single sign-on is for — and their groups come from its claims
  (accounts/groups.py); GitHub, which anyone can join, follows `SIGNUP_OPEN`.
"""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings


def is_agent(user) -> bool:
    return bool(user is not None and getattr(user, "username", "").startswith("agent:"))


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request) -> bool:
        return settings.SIGNUP_OPEN

    def authenticate(self, request, **credentials):
        """A password sign-in; an agent's is wrong credentials, whatever the password."""
        user = super().authenticate(request, **credentials)
        return None if is_agent(user) else user

    def pre_login(self, request, user, **kwargs):
        """Every other route to a session — a code, a provider, a passkey — refuses an agent too."""
        if is_agent(user):
            from allauth.account.internal.stagekit import clear_login

            clear_login(request)
            return self.respond_user_inactive(request, user)
        return super().pre_login(request, user, **kwargs)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin) -> bool:
        return is_oidc(sociallogin) or settings.SIGNUP_OPEN


def is_oidc(sociallogin) -> bool:
    """Whether a sign-in came through one of the OpenID Connect IdPs (its account's `provider` is the IdP's id)."""
    return sociallogin.provider.id == "openid_connect"
