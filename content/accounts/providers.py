"""Third-party sign-in from the environment: what `SOCIALACCOUNT_PROVIDERS` and
`OIDC_GROUP_MAP` are, read by the settings (config/settings/base.py) before
Django starts — so nothing here imports a model.

**OpenID Connect, one allauth app per IdP.** `OIDC_PROVIDERS` names the IdPs
(comma-separated ids, e.g. `okta,entra`); each id's variables say the rest:

    OIDC_<ID>_SERVER_URL      the issuer; its /.well-known/openid-configuration is read
    OIDC_<ID>_CLIENT_ID       the client this platform is at the IdP
    OIDC_<ID>_CLIENT_SECRET   its secret (optional for a public client with PKCE)
    OIDC_<ID>_NAME            the button's label (default: the id)
    OIDC_<ID>_SCOPES          extra scopes, comma-separated (e.g. `groups`), beside openid, profile and email
    OIDC_<ID>_PKCE            true to send PKCE (default true)

`<ID>` is the id in upper case with `-` as `_`. A named IdP without a server
URL or a client id stops the platform from starting, naming the variable — a
sign-in button that cannot work is worse than none.

**GitHub** is one app when `GITHUB_LOGIN_CLIENT_ID` and
`GITHUB_LOGIN_CLIENT_SECRET` are set (an OAuth app whose callback is
`/accounts/github/login/callback/`).

**Groups.** `OIDC_GROUP_MAP` is a JSON object from a value of the IdP's groups
claim to the Wagtail group (or list of groups) it grants, e.g.
`{"cms-editors": "Editors", "cms-leads": ["Editors", "Moderators"]}`;
accounts/groups.py applies it at every sign-in through an IdP.

None of these set: local accounts only. No value here is ever logged.
"""

import json
import re

from django.core.exceptions import ImproperlyConfigured

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def oidc_apps(environ) -> list[dict]:
    """The allauth `openid_connect` apps `OIDC_PROVIDERS` names, in its order."""
    apps = []
    for provider_id in [p.strip() for p in environ.get("OIDC_PROVIDERS", "").split(",") if p.strip()]:
        if not _ID.match(provider_id):
            raise ImproperlyConfigured(f"OIDC_PROVIDERS: {provider_id!r} is not an id (lower case, digits and -)")
        prefix = f"OIDC_{provider_id.upper().replace('-', '_')}_"
        server_url, client_id = environ.get(prefix + "SERVER_URL", ""), environ.get(prefix + "CLIENT_ID", "")
        for name, value in ((prefix + "SERVER_URL", server_url), (prefix + "CLIENT_ID", client_id)):
            if not value:
                raise ImproperlyConfigured(f"OIDC_PROVIDERS names {provider_id}, but {name} is not set")
        scopes = [s.strip() for s in environ.get(prefix + "SCOPES", "").split(",") if s.strip()]
        apps.append(
            {
                "provider_id": provider_id,
                "name": environ.get(prefix + "NAME") or provider_id,
                "client_id": client_id,
                "secret": environ.get(prefix + "CLIENT_SECRET", ""),
                "settings": {
                    "server_url": server_url,
                    "oauth_pkce_enabled": _flag(environ.get(prefix + "PKCE"), True),
                    **({"scope": ["openid", "profile", "email", *scopes]} if scopes else {}),
                },
            }
        )
    return apps


def socialaccount_providers(environ) -> dict:
    """`SOCIALACCOUNT_PROVIDERS` for the IdPs and the GitHub app the environment configures."""
    providers: dict = {"openid_connect": {"APPS": oidc_apps(environ)}}
    client_id, secret = environ.get("GITHUB_LOGIN_CLIENT_ID", ""), environ.get("GITHUB_LOGIN_CLIENT_SECRET", "")
    if client_id or secret:
        if not (client_id and secret):
            raise ImproperlyConfigured(
                "GitHub sign-in needs both GITHUB_LOGIN_CLIENT_ID and GITHUB_LOGIN_CLIENT_SECRET"
            )
        providers["github"] = {
            "APPS": [{"client_id": client_id, "secret": secret}],
            # The verified addresses, so an address GitHub vouches for is one allauth can trust.
            "SCOPE": ["read:user", "user:email"],
        }
    else:
        providers["github"] = {"APPS": []}
    return providers


def group_map(text: str) -> dict[str, list[str]]:
    """`OIDC_GROUP_MAP` parsed: each claim value to the list of Wagtail group names it grants."""
    if not text.strip():
        return {}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ImproperlyConfigured(f"OIDC_GROUP_MAP is not JSON: {e.msg} at {e.pos}") from e
    if not isinstance(raw, dict):
        raise ImproperlyConfigured("OIDC_GROUP_MAP is a JSON object from a claim value to a group or a list of groups")
    mapped = {}
    for claim, groups in raw.items():
        names = [groups] if isinstance(groups, str) else groups
        if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
            raise ImproperlyConfigured(f"OIDC_GROUP_MAP[{claim!r}] is a group name or a list of group names")
        mapped[str(claim)] = names
    return mapped
