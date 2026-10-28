"""The pages a member may post to, and aggregate statistics for the author's
own posts — nothing about who engaged.

Page roles are verified through LinkedIn rather than asserted by configuration;
a 403 answers None, not [] — "this token may not read page roles" and "this
member administers no pages" are different answers.

Both statistics endpoints return counts attached to a post: impressions,
clicks, reactions, comments, shares. Nothing here asks for a per-member record,
and `normalize` drops every field it does not name. A page's posts:
`organizationalEntityShareStatistics`, lifetime totals for up to twenty posts a
call — a post LinkedIn leaves out of the answer had no impressions and no
actions, which LinkedIn says to read as zero, and only posts this lane asked
about are filled in. A member's post: `memberCreatorPostAnalytics`, one metric
per call; `LINK_CLICKS` exists from version 202604.
"""

from dataclasses import dataclass

from . import plan, restli
from .client import HTTPError

POSTING_ROLES = ("ADMINISTRATOR", "CONTENT_ADMINISTRATOR", "DIRECT_SPONSORED_CONTENT_POSTER")
METRICS = ("impressions", "clicks", "reactions", "comments", "shares")
ORGANIZATION_FIELDS = {
    "impressions": "impressionCount",
    "clicks": "clickCount",
    "reactions": "likeCount",
    "comments": "commentCount",
    "shares": "shareCount",
}
MEMBER_QUERY_TYPES = {
    "impressions": "IMPRESSION",
    "reactions": "REACTION",
    "comments": "COMMENT",
    "shares": "RESHARE",
    "clicks": "LINK_CLICKS",
}
LINK_CLICKS_SINCE = "202604"
BATCH = 20


@dataclass
class Page:
    urn: str
    role: str
    name: str | None = None


def administered(client, count: int = 100) -> list[Page] | None:
    query = [("q", "roleAssignee"), ("state", "APPROVED"), ("count", max(1, min(int(count), 100)))]
    try:
        elements = client.json("organization_acls", query=query).get("elements") or []
    except HTTPError as e:
        if e.forbidden:
            return None
        raise
    best: dict[str, Page] = {}
    for element in elements:
        urn = element.get("organization") or element.get("organizationTarget")
        role = element.get("role")
        if plan.author_type(urn) != "organization" or role not in POSTING_ROLES:
            continue
        if urn not in best or POSTING_ROLES.index(role) < POSTING_ROLES.index(best[urn].role):
            best[urn] = Page(urn=urn, role=role)
    return list(best.values())


def organization_name(client, urn: str) -> str | None:
    if plan.author_type(urn) != "organization":
        raise ValueError(f"not an organization URN: {urn!r}")
    try:
        return client.json("organization", path={"id": urn.rsplit(":", 1)[-1]}).get("localizedName")
    except HTTPError as e:
        if e.forbidden or e.not_found:
            return None
        raise


def normalize(raw) -> dict:
    """The five counts as non-negative integers, plus `engagements` — reactions,
    comments and shares, the deliberate actions: the shape the extension's
    `normalisePerformance` produces, so performance.json reads the same."""
    clean = {}
    for metric in METRICS:
        try:
            clean[metric] = max(int((raw or {}).get(metric) or 0), 0)
        except (TypeError, ValueError):
            clean[metric] = 0
    return {**clean, "engagements": clean["reactions"] + clean["comments"] + clean["shares"]}


def for_organization(client, *, organization: str, urns) -> dict:
    if plan.author_type(organization) != "organization":
        raise ValueError(f"not an organization URN: {organization!r}")
    wanted = list(dict.fromkeys(str(u) for u in urns if plan.POST_URN.match(str(u))))
    out: dict[str, dict] = {}
    shares = [u for u in wanted if u.startswith("urn:li:share:")]
    ugc_posts = [u for u in wanted if not u.startswith("urn:li:share:")]
    for param, group in (("shares", shares), ("ugcPosts", ugc_posts)):
        for i in range(0, len(group), BATCH):
            batch = group[i : i + BATCH]
            query = [
                ("q", "organizationalEntity"),
                ("organizationalEntity", organization),
                (param, restli.listing(batch)),
            ]
            for element in client.json("organization_share_statistics", query=query).get("elements") or []:
                urn = element.get("share") or element.get("ugcPost")
                if urn in batch:
                    totals = element.get("totalShareStatistics") or {}
                    out[urn] = normalize({metric: totals.get(f) for metric, f in ORGANIZATION_FIELDS.items()})
    for urn in wanted:
        out.setdefault(urn, normalize({}))
    return out


def for_member_post(client, *, urn: str) -> dict:
    match = plan.POST_URN.match(str(urn or ""))
    if not match:
        raise ValueError(f"not a post URN: {urn!r}")
    entity = restli.record([("ugc" if match.group(1) == "ugcPost" else "share", urn)])
    raw = {}
    for metric, query_type in MEMBER_QUERY_TYPES.items():
        if metric == "clicks" and client.api_version < LINK_CLICKS_SINCE:
            continue
        query = [("q", "entity"), ("entity", entity), ("queryType", query_type), ("aggregation", "TOTAL")]
        elements = client.json("member_post_statistics", query=query).get("elements") or []
        raw[metric] = sum(int(e.get("count") or 0) for e in elements)
    return normalize(raw)
