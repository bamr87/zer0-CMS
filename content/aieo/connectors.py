"""AIEO's data connectors, for real: GA4's top pages, Search Console's queries and DataForSEO's search results for a
site (in AIEO they returned placeholder rows).

Each is a small client of the vendor's documented REST API over httpx, run only in a worker (aieo/tasks.py), and
each result is kept as a `ConnectorData` row, which is what priorities and the performance agent read — a sync is
a cache, as AIEO's `.cache/` files were. The hosts are fixed — every URL is a constant of this module, Google's or
DataForSEO's — never a URL a person gave. The credentials are the connector's, decrypted only here and never logged:

* GA4 and Search Console take a Google service account's JSON key; the client signs a JWT (PyJWT, RS256) and
  trades it for an access token at Google's token endpoint (`google_token`) — always `TOKEN_URI`, whatever the
  key's own `token_uri` says, since the key is what a person pasted — and the service account must be added as a
  user of the GA4 property or the Search Console site;
* DataForSEO takes `login:password` (HTTP basic auth).

Tests answer every request with recorded HTTP (respx).
"""

import json
import time
from datetime import date, timedelta
from urllib.parse import quote

import httpx
import jwt
from django.conf import settings

from .models import Connector, ConnectorData

TOKEN_URI = "https://oauth2.googleapis.com/token"
GA4 = "https://analyticsdata.googleapis.com/v1beta/properties/{property}:runReport"
GSC = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
DATAFORSEO = "https://api.dataforseo.com/v3/serp/google/organic/live/regular"
SCOPES = {
    Connector.GA4: "https://www.googleapis.com/auth/analytics.readonly",
    Connector.GSC: "https://www.googleapis.com/auth/webmasters.readonly",
}
REPORTS = {Connector.GA4: "top_pages", Connector.GSC: "queries", Connector.DATAFORSEO: "serp"}


class ConnectorError(Exception):
    """A connector could not be read; the message says why, for the person who configured it."""


def _client() -> httpx.Client:
    return httpx.Client(timeout=settings.AIEO_CONNECTOR_TIMEOUT, trust_env=False)


def _answer(response: httpx.Response, what: str) -> dict:
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {})
            detail = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        except ValueError:
            detail = ""
        raise ConnectorError(f"{what} answered HTTP {response.status_code}{f': {detail}' if detail else ''}")
    return response.json()


def service_account(credential: str) -> dict:
    try:
        key = json.loads(credential)
    except ValueError as e:
        raise ConnectorError("the credential is not a service account's JSON key") from e
    if not isinstance(key, dict) or not key.get("client_email") or not key.get("private_key"):
        raise ConnectorError("the service account key needs its client_email and private_key")
    return key


def google_token(credential: str, scope: str, client: httpx.Client) -> str:
    """An access token for a service account: a signed JWT assertion traded at Google's token endpoint — `TOKEN_URI`,
    never the key's `token_uri` (the assertion's audience is `TOKEN_URI` in any case)."""
    key = service_account(credential)
    now = int(time.time())
    claims = {"iss": key["client_email"], "scope": scope, "aud": TOKEN_URI, "iat": now, "exp": now + 3600}
    try:
        assertion = jwt.encode(claims, key["private_key"], algorithm="RS256")
    except (ValueError, jwt.PyJWTError) as e:
        raise ConnectorError("the service account's private key cannot sign") from e
    grant = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
    return _answer(client.post(TOKEN_URI, data=grant), "Google's token endpoint")["access_token"]


def _window(options: dict) -> tuple[str, str]:
    days = int(options.get("days") or 28)
    end = date.today() - timedelta(days=1)
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()


def ga4_top_pages(connector: Connector, client: httpx.Client) -> list[dict]:
    """GA4's pages by sessions over the window: path, sessions, engagement rate, views."""
    prop = str(connector.options.get("property_id") or "").removeprefix("properties/")
    if not prop.isdigit():
        raise ConnectorError("set the GA4 property id (digits, from the property's settings)")
    token = google_token(connector.get_credential(), SCOPES[Connector.GA4], client)
    start, end = _window(connector.options)
    body = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "dimensions": [{"name": "pagePath"}],
        "metrics": [{"name": "sessions"}, {"name": "engagementRate"}, {"name": "screenPageViews"}],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": int(connector.options.get("limit") or 100),
    }
    found = _answer(client.post(GA4.format(property=prop), json=body, headers=_bearer(token)), "GA4")
    rows = []
    for row in found.get("rows", []):
        values = [m.get("value", "0") for m in row.get("metricValues", [])] + ["0", "0", "0"]
        rows.append(
            {
                "page": row.get("dimensionValues", [{}])[0].get("value", ""),
                "sessions": int(float(values[0])),
                "engagement_rate": round(float(values[1]), 4),
                "views": int(float(values[2])),
            }
        )
    return rows


def gsc_queries(connector: Connector, client: httpx.Client) -> list[dict]:
    """Search Console's queries and pages over the window: clicks, impressions, CTR, position."""
    site = str(connector.options.get("site_url") or "").strip()
    if not site:
        raise ConnectorError("set the Search Console property (https://example.com/ or sc-domain:example.com)")
    token = google_token(connector.get_credential(), SCOPES[Connector.GSC], client)
    start, end = _window(connector.options)
    body = {
        "startDate": start,
        "endDate": end,
        "dimensions": ["query", "page"],
        "rowLimit": int(connector.options.get("limit") or 250),
    }
    found = _answer(client.post(GSC.format(site=quote(site, safe="")), json=body, headers=_bearer(token)), "GSC")
    return [
        {
            "query": (row.get("keys") or ["", ""])[0],
            "page": (row.get("keys") or ["", ""])[1] if len(row.get("keys") or []) > 1 else "",
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
            "ctr": round(float(row.get("ctr", 0)), 4),
            "position": round(float(row.get("position", 0)), 2),
        }
        for row in found.get("rows", [])
    ]


def dataforseo_serp(connector: Connector, client: httpx.Client) -> list[dict]:
    """DataForSEO's organic results for each of the connector's keywords: rank, URL, domain, title."""
    keywords = [str(k).strip() for k in connector.options.get("keywords") or [] if str(k).strip()]
    if not keywords:
        raise ConnectorError("list the keywords to look up")
    login, _, password = connector.get_credential().partition(":")
    if not (login and password):
        raise ConnectorError("the credential is DataForSEO's login:password")
    tasks = [
        {
            "keyword": keyword,
            "location_code": int(connector.options.get("location_code") or 2840),
            "language_code": str(connector.options.get("language_code") or "en"),
            "depth": int(connector.options.get("depth") or 20),
        }
        for keyword in keywords[:10]
    ]
    found = _answer(client.post(DATAFORSEO, json=tasks, auth=(login, password)), "DataForSEO")
    rows = []
    for task in found.get("tasks") or []:
        if task.get("status_code") not in (20000, None):
            raise ConnectorError(f"DataForSEO: {task.get('status_message') or task.get('status_code')}")
        for result in task.get("result") or []:
            for item in result.get("items") or []:
                if item.get("type") == "organic":
                    rows.append(
                        {
                            "keyword": result.get("keyword", ""),
                            "rank": item.get("rank_absolute"),
                            "url": item.get("url", ""),
                            "domain": item.get("domain", ""),
                            "title": item.get("title", ""),
                        }
                    )
    return rows


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


READERS = {Connector.GA4: ga4_top_pages, Connector.GSC: gsc_queries, Connector.DATAFORSEO: dataforseo_serp}


def fetch_rows(connector: Connector) -> ConnectorData:
    """Read the connector's report and keep it (in a worker)."""
    with _client() as client:
        rows = READERS[connector.kind](connector, client)
    return ConnectorData.objects.create(connector=connector, report=REPORTS[connector.kind], rows=rows)
