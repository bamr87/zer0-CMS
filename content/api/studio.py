"""The built studio (web/studio), served by the platform at /studio/.

One origin for the studio and its API (PLAN P-D4's proposal): the session
cookie and the CSRF token work without CORS, and there is one deploy. Vite
builds the studio with its asset URLs under `/static/studio/`
(web/studio/vite.config.ts) into `STUDIO_DIST`, which settings add to
`STATICFILES_DIRS`, so WhiteNoise serves the assets like every other static
file. This view answers every /studio/ path with `index.html`: the studio's
own router owns those paths.

The page gets an enforced Content-Security-Policy with a nonce made for each
request: scripts only from this origin, and no inline style except the
`<style>` elements Mantine writes, which carry the nonce (they read it from
the `<meta property="csp-nonce">` Vite writes with a placeholder that this
view replaces). The extension's webviews need the same policy (PLAN G10), so
the studio is held to it from the start. Its one form leaves for an IdP: the
sign-in's provider button POSTs to allauth, which redirects to the IdP, and a
browser holds that redirect to `form-action` too — so the policy names this
origin and the origin of each IdP and of GitHub the environment configures
(PLAN G3), and nothing else.
"""

import json
import secrets
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse

NONCE_PLACEHOLDER = "__CSP_NONCE__"
POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'nonce-{nonce}'; img-src 'self' data: blob:; "
    "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action {form_action}; "
    "frame-ancestors 'none'"
)


@cache
def provider_origins(providers_json: str) -> tuple[str, ...]:
    """The https origins a provider sign-in redirects to: each OpenID Connect IdP's issuer, and GitHub's."""
    providers = json.loads(providers_json)
    found = []
    for app in providers.get("openid_connect", {}).get("APPS", []):
        parts = urlsplit(app["settings"]["server_url"])
        found.append(f"{parts.scheme}://{parts.netloc}")
    if providers.get("github", {}).get("APPS"):
        found.append("https://github.com")
    return tuple(dict.fromkeys(found))


def form_action() -> str:
    origins = provider_origins(json.dumps(settings.SOCIALACCOUNT_PROVIDERS, sort_keys=True))
    return " ".join(["'self'", *origins])


def studio(request, path=""):
    index = Path(settings.STUDIO_DIST) / "index.html"
    if not index.is_file():
        return HttpResponse(
            "The studio has not been built. Build it with: cd web && npm ci && npm run build\n",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    nonce = secrets.token_urlsafe(18)
    response = HttpResponse(index.read_text(encoding="utf-8").replace(NONCE_PLACEHOLDER, nonce))
    response["Content-Security-Policy"] = POLICY.format(nonce=nonce, form_action=form_action())
    response["Cache-Control"] = "no-store"
    return response
