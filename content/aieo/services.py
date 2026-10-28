"""What AIEO does in the platform: every command, so its views, tools, tasks and `manage.py aieo` stay thin
(TARGET.md § Rules that keep models and views manageable).

Nothing here reaches the network or a model inside a request. An audit is saved as `pending` and done by a run of
the AI layer's `assistant` agent (aieo/handlers.py) — which reads a page as it is, fetches a URL or crawls a site
through the research library's guarded fetcher in the worker, scores with the heuristics, and, when a model's
evaluation was asked for, has the bundled evaluator score it with the heuristics as the fallback. Optimizing,
scrubbing and applying a pattern are runs too, whose rewrite arrives on the page as suggestions; the AIEO agents are
the AI layer's own assistant runs; a citation check is one run per engine. Connectors sync in a worker
(aieo/tasks.py). What can be answered from the database or by the analyzers alone — the pattern library, a quick
heuristic score, priorities from the last sync, share of voice — is answered here, at once.
"""

import difflib
import re
import uuid
from datetime import timedelta
from statistics import mean
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from wagtail.models import Page, Site

from agents.models import AgentRun
from ai import crypto, providers
from ai.models import Assistant, Visibility, sites_for, usable
from ai.services import check_page, check_provider, provider_slug, run_assistant, stable_id, start
from cms.models import BasePage
from graph.services import embed_object, knn
from importers.markdown import block_to_markdown, from_blocks, to_blocks
from ops.errors import Conflict, Forbidden, Invalid, Unavailable
from research import fetch

from . import analyzers, scoring
from .models import Audit, BrandContext, CitationCheck, CitationQuery, Connector, ConnectorData, Pattern, library

EVALUATOR, OPTIMIZER, SCRUBBER, REWRITER, PROBE = (
    "aieo-evaluator",
    "aieo-optimizer",
    "aieo-scrubber",
    "aieo-rewriter",
    "aieo-citation-probe",
)
MODES = {"optimize": OPTIMIZER, "expand": OPTIMIZER, "scrub": SCRUBBER, "rewrite": REWRITER, "pattern": OPTIMIZER}
MAX_TEXT = 200_000  # characters of a pasted text an audit keeps


def bundled(key: str, user) -> Assistant:
    """A bundled AIEO assistant, if `user` may use it."""
    row = Assistant.objects.filter(public_id=stable_id("bundled-assistant", key)).first()
    if row is None:
        raise Unavailable(f"the bundled assistant {key!r} is missing: run manage.py migrate")
    if not usable(row, user):
        raise Forbidden(f"the {row.name} assistant is not one {user} may use")
    return row


def context_for(site) -> BrandContext | None:
    """A site's brand context (made from the templates the first time it is read), or None for no site."""
    return BrandContext.for_site(site) if site is not None else None


def signals(site) -> dict:
    """What a site's context lends a score: its target keywords and the topics its competitors cover."""
    context = context_for(site)
    return {"keywords": context.keywords(), "competitor_topics": context.topics()} if context else {}


def page_markdown(page, *, title=True) -> str:
    """A page's latest revision as the Markdown AIEO scores: its title as the heading, then its body."""
    latest = page.get_latest_revision_as_object()
    body = from_blocks(latest.body.get_prep_value(), leading="").strip() if hasattr(latest, "body") else ""
    return f"# {latest.title}\n\n{body}\n" if title else f"{body}\n"


def editable(user, page) -> BasePage:
    page = page.specific
    if not isinstance(page, BasePage):
        raise Invalid(f"page {page.pk} is not a content page")
    if not page.permissions_for_user(user).can_edit():
        raise Forbidden(f"{user} may not edit page {page.pk}")
    return page


def _person(user) -> None:
    if user is None or not user.is_authenticated:
        raise Forbidden("sign in to use AIEO")


def _placement(user, site, visibility) -> dict:
    """An owned row's site and visibility: a site the person edits (staff: any), shared only when asked."""
    if site is not None and not (user.is_staff or user.is_superuser) and site.pk not in sites_for(user):
        raise Forbidden(f"{user} does not edit site {site.pk}")
    visibility = visibility or (Visibility.SITE if site is not None else Visibility.PRIVATE)
    if visibility == Visibility.SITE and site is None:
        raise Invalid("site visibility needs a site")
    return {"site": site, "visibility": visibility}


# ── scoring at once ────────────────────────────────────────────────────────


def quick_score(content: str, format: str = "markdown", *, site=None) -> dict:
    """The heuristic score of a text, now, with nothing recorded — what the editor shows while a person types."""
    if not content.strip():
        raise Invalid("there is nothing to score")
    if len(content) > MAX_TEXT:
        raise Invalid(f"a text is scored up to {MAX_TEXT} characters")
    return scoring.score(content, format, library(), **signals(site))


# ── audits ─────────────────────────────────────────────────────────────────


def _evaluator(user, method: str, provider: str) -> str:
    """The provider a model's evaluation would use, checked now (enabled, in budget); '' for heuristics only."""
    if method == Audit.HEURISTIC:
        return ""
    assistant = bundled(EVALUATOR, user)
    return check_provider(provider) if provider else provider_slug(assistant)


def audit(
    user,
    *,
    kind: str,
    method: str = Audit.AI,
    content: str = "",
    format: str = Audit.MARKDOWN,
    page=None,
    url: str = "",
    max_pages: int = 25,
    visual: bool = False,
    provider: str = "",
    site=None,
    visibility: str = "",
    title: str = "",
    origin: str = "api",
    batch: str = "",
    trigger: str = "rest",
) -> Audit:
    """An audit of a text, a page, a URL or a site, saved as pending; its run does the work."""
    _person(user)
    if method not in (Audit.HEURISTIC, Audit.AI):
        raise Invalid("method is heuristic or ai")
    fields = {"kind": kind, "method": method, "provider": provider, "title": title[:500], "origin": origin}
    if kind == Audit.TEXT:
        if not content.strip():
            raise Invalid("paste the text to audit")
        if len(content) > MAX_TEXT:
            raise Invalid(f"a text is audited up to {MAX_TEXT} characters")
        fields |= {"content": content, "format": format if format in (Audit.MARKDOWN, Audit.HTML) else Audit.MARKDOWN}
    elif kind == Audit.PAGE:
        if page is None:
            raise Invalid("choose the page to audit")
        page = editable(user, page)
        site = site or page.get_site()
        fields |= {"page": page, "title": title or page.title}
    elif kind in (Audit.URL, Audit.SITE):
        url = url.strip()
        try:
            fetch.refuse_private_literal(url)
        except fetch.Blocked as e:
            raise Invalid(str(e)) from e
        fields |= {"url": url, "max_pages": max(1, min(int(max_pages or 25), 200))}
        fields["visual"] = bool(visual) and kind == Audit.URL
    else:
        raise Invalid("an audit is of a text, a page, a URL or a site")
    _evaluator(user, method, provider)
    row = Audit.objects.create(owner=user, batch=batch, **fields, **_placement(user, site, visibility))
    row.run = start(user, {"kind": "aieo.audit", "audit": str(row.public_id)}, target=page, trigger=trigger)
    row.save(update_fields=["run"])
    return row


def batch_audit(user, urls: list[str], *, method: str = Audit.AI, origin="api", trigger="rest", **options) -> list:
    """One audit per URL, made together (the same `batch`), each its own run."""
    urls = [u.strip() for u in urls if u.strip() and not u.strip().startswith("#")]
    if not urls:
        raise Invalid("list at least one URL")
    if len(urls) > 100:
        raise Invalid("a batch is at most 100 sites")
    key = uuid.uuid4().hex
    with transaction.atomic():
        return [
            audit(user, kind=Audit.URL, url=u, method=method, origin=origin, batch=key, trigger=trigger, **options)
            for u in urls
        ]


def remember(row: Audit, parsed: dict) -> list[float] | None:
    """Store what an audit read as a vector (`graph.Embedding`, kind `audit`; pgvector on Postgres), for the
    semantic benchmark — AIEO's configured, never-used Qdrant, done on the platform's vectors."""
    text = parsed.get("text", "")[:6000]
    if not text.strip():
        return None
    stored, _ = embed_object(row, text, parsed.get("content_hash", ""), "audit")
    return list(stored.vector)


def benchmark(row: Audit, vector: list[float] | None = None) -> dict:
    """Where an audit stands: its percentile among the platform's audits of the same kind of thing (a page among
    pages, a site among sites); per engine, how often the AI engines asked about its domain cited it; and the
    audits closest to it in meaning, of those its owner sees, with their scores."""
    peers = Audit.objects.filter(status=Audit.READY, score__isnull=False).exclude(pk=row.pk)
    peers = peers.filter(kind__in=(Audit.SITE,) if row.kind == Audit.SITE else (Audit.TEXT, Audit.PAGE, Audit.URL))
    scores = list(peers.values_list("score", flat=True)[:5000])
    below = sum(1 for s in scores if s < (row.score or 0))
    domain = urlsplit(row.url).hostname or ""
    if row.page_id and not domain:
        domain = (row.page.get_site().hostname if row.page.get_site() else "") or ""
    engines = {}
    if domain and row.owner_id:
        checks = CitationCheck.objects.visible_to(row.owner).filter(
            status=CitationCheck.READY, query__domain__iendswith=_bare(domain)
        )
        for engine in sorted(set(checks.values_list("engine", flat=True))):
            asked = checks.filter(engine=engine)
            engines[engine] = {"checks": asked.count(), "cited": asked.filter(cited=True).count()}
            engines[engine]["rate"] = round(engines[engine]["cited"] / engines[engine]["checks"], 3)
    similar = []
    if vector is not None and row.owner_id:
        seen = Audit.objects.visible_to(row.owner).filter(status=Audit.READY).exclude(pk=row.pk)
        near = knn(vector, kind="audit", k=3, exclude=[row.pk], only_ids=list(seen.values_list("pk", flat=True)[:5000]))
        found = Audit.objects.in_bulk([pk for pk, _ in near])
        similar = [
            {
                "audit": str(found[pk].public_id),
                "target": found[pk].target,
                "score": found[pk].score,
                "similarity": round(s, 3),
            }
            for pk, s in near
            if pk in found
        ]
    return {
        "percentile": round(100 * below / len(scores), 1) if scores else None,
        "compared_with": len(scores),
        "engines": engines,
        "similar": similar,
    }


def history(user, *, page=None, url: str = ""):
    rows = Audit.objects.visible_to(user)
    if page is not None:
        rows = rows.filter(page=page)
    if url:
        rows = rows.filter(url=url)
    return rows


# ── rewrites: optimize, scrub, rewrite, apply a pattern ────────────────────


def rewrite(
    user,
    *,
    mode: str,
    page=None,
    content: str = "",
    pattern: Pattern | None = None,
    style: str = "preserve",
    trigger: str = "rest",
) -> AgentRun:
    """A rewrite as a run of the bundled assistant for `mode`: on a page its answer arrives as suggestions there
    (each changed block replaced, inserted or deleted — never written); on a pasted text it is a draft to read."""
    _person(user)
    if mode not in MODES:
        raise Invalid(f"a rewrite is one of {', '.join(MODES)}")
    if style not in ("preserve", "aggressive"):
        raise Invalid("style is preserve or aggressive")
    if mode == "pattern" and (pattern is None or not pattern.enabled):
        raise Invalid("choose an enabled pattern to apply")
    data = {"kind": "aieo.rewrite", "mode": mode, "style": style}
    if pattern is not None:
        data["pattern"] = pattern.name
    if page is not None:
        page = editable(user, page)
        check_page(user, page)
        if not page_markdown(page, title=False).strip():
            raise Invalid("the page has no text to rewrite")
    elif not content.strip():
        raise Invalid("choose a page, or paste the text to rewrite")
    elif len(content) > MAX_TEXT:
        raise Invalid(f"a text is rewritten up to {MAX_TEXT} characters")
    else:
        data["content"] = content
    provider_slug(bundled(MODES[mode], user))
    return start(user, data, target=page, trigger=trigger)


def optimization_prompt(content: str, gaps: list[dict], style: str, expand: bool) -> str:
    """The request the optimizer reads: AIEO's own (ai_service._build_optimization_prompt), enhance or expand."""
    if expand:
        listed = "\n".join(f"- {gap['description']}" for gap in gaps[:10])
        tone = (
            "Preserve the author's voice where possible while adding structured depth."
            if style == "preserve"
            else "You may substantially reshape sections for clarity and citability."
        )
        return (
            f"{scoring.prompt('optimize_expand.md')}\n\n## Scoring gaps to address (where relevant)\n"
            f"{listed or '- (none listed — still expand for structure and depth)'}\n\n## Tone\n{tone}\n\n"
            f"## Original content\n{content}\n\nReturn the full expanded markdown document only:"
        )
    listed = "\n".join(f"- {gap['description']}" for gap in gaps[:5])
    tone = (
        "Preserve the original writing style and tone."
        if style == "preserve"
        else "You may modify the writing style to maximize AIEO score."
    )
    return f"""Optimize the following content to improve its citation likelihood by AI engines.

Gaps to fix:
{listed}

{tone}

Apply these AIEO patterns:
1. Add structured data (tables, lists) where appropriate
2. Increase entity density (people, places, products, dates)
3. Add citation hooks ("According to...", "Research shows...")
4. Add recursive depth (answer follow-up questions)
5. Add temporal anchors (dates, versions)
6. Add comparison tables if comparing items
7. Add explicit definitions
8. Add step-by-step procedures if applicable
9. Add FAQ sections
10. Add meta-context explanations

Original content:
{content}

Return the optimized content:"""


def pattern_prompt(content: str, pattern: dict, style: str) -> str:
    tone = "Keep the author's voice and structure." if style == "preserve" else "You may reshape sections."
    return (
        f"Apply one AIEO pattern to the content below: {pattern['display_name']}.\n\n## The pattern\n\n"
        f"{pattern['body']}\n\n## Rules\n\nChange only what applying this pattern needs. {tone} Do not invent facts, "
        f"statistics, names or sources the content does not give.\n\n## Original content\n{content}\n\n"
        "Return the full revised markdown document only:"
    )


def proposals(blocks: list[dict], markdown: str) -> list[tuple]:
    """A rewrite of a page's body as suggestion operations, block by block: the old and new blocks are aligned by
    their Markdown (difflib), and only what changed is proposed — where a run of blocks changed, each old block is
    replaced by the new one in its place, new blocks left over are inserted after the last of them, old ones left
    over deleted. New blocks next to each other arrive as one Markdown block, so accepting them keeps their order."""
    old = [(b, block_to_markdown(b["type"], b["value"]).strip()) for b in blocks]
    old = [(b, text) for b, text in old if text]
    new = to_blocks(markdown.strip())
    texts = [block_to_markdown(b["type"], b["value"]).strip() for b in new]

    def merged(j1, j2):
        return new[j1] if j2 - j1 == 1 else {"type": "markdown", "value": "\n\n".join(texts[j1:j2])}

    found = []
    matcher = difflib.SequenceMatcher(None, [text for _, text in old], texts, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            paired = min(i2 - i1, j2 - j1)
            found += [("replace", old[i1 + k][0]["id"], new[j1 + k]) for k in range(paired)]
            if j2 - j1 > paired:
                found.append(("insert", old[i1 + paired - 1][0]["id"], merged(j1 + paired, j2)))
            found += [("delete", b["id"], None) for b, _ in old[i1 + paired : i2]]
        elif tag == "delete":
            found += [("delete", b["id"], None) for b, _ in old[i1:i2]]
        elif i1 > 0:
            found.append(("insert", old[i1 - 1][0]["id"], merged(j1, j2)))
        elif old:  # new text before the first block: it and that block become one
            joined = "\n\n".join([*texts[j1:j2], old[0][1]])
            found.append(("replace", old[0][0]["id"], {"type": "markdown", "value": joined}))
        else:
            found.append(("insert", "", merged(j1, j2)))
    return found


def without_title(markdown: str, title: str) -> str:
    """A rewrite's body: a first line that is the page's title as a heading is the title, not the body."""
    lines = markdown.strip().split("\n")
    if lines and re.match(r"^#\s+", lines[0]) and lines[0].lstrip("#").strip().lower() == title.strip().lower():
        lines = lines[1:]
    return "\n".join(lines).strip()


# ── the AIEO agents ────────────────────────────────────────────────────────


def agent_prompt(*, content: str = "", page=None, site=None, inputs: dict | None = None) -> str:
    """What an AIEO agent reads: the content (or the page's), the inputs its prompt names, and the site's context —
    AIEO's agent runner put the workspace's context files beside the content the same way."""
    text = page_markdown(page) if page is not None and not content.strip() else content
    parts = [f"## Content\n\n{text.strip()}"] if text.strip() else []
    for name, value in (inputs or {}).items():
        if str(value).strip():
            parts.append(f"## {name.replace('_', ' ').capitalize()}\n\n{str(value).strip()}")
    context = context_for(site)
    if context is not None and context.as_prompt():
        parts.append(f"## The site's context\n\n{context.as_prompt()}")
    return "\n\n".join(parts)


def run_agent(user, key: str, *, content: str = "", page=None, site=None, inputs=None, trigger="rest") -> AgentRun:
    """One of the AIEO agents on a text or a page, with the site's context: a run of its bundled assistant whose
    structured answer a person reads (and, in the editor, may land as suggestions through the AI panel)."""
    from .prompts import AGENTS

    _person(user)
    if key not in AGENTS:
        raise Invalid(f"no AIEO agent {key!r}")
    if page is not None:
        page = editable(user, page)
        site = site or page.get_site()
    prompt = agent_prompt(content=content, page=page, site=site, inputs=inputs)
    if not prompt.strip():
        raise Invalid("give the agent something to read: a text, a page or its inputs")
    return run_assistant(bundled(key, user), user=user, prompt=prompt, page=page, trigger=trigger)


# ── citations ──────────────────────────────────────────────────────────────


def _bare(domain: str) -> str:
    host = (urlsplit(domain).hostname if "//" in domain else domain.split("/")[0]) or ""
    return host.lower().removeprefix("www.")


def engines(query: CitationQuery) -> list[str]:
    return [str(e) for e in query.engines or []] or [providers.default_slug()]


def check_citations(query: CitationQuery, *, user, trigger: str = "rest") -> list[CitationCheck]:
    """Ask every engine of the query, now: a check and a run per engine (the probe answers through that provider)."""
    if not query.can_edit(user) and not usable(query, user):
        raise Forbidden(f"citation query {query.public_id} is not {user}'s to check")
    assistant = bundled(PROBE, user)
    asked = [check_provider(engine) for engine in engines(query)]
    made = []
    with transaction.atomic():
        for engine in asked:
            check = CitationCheck.objects.create(query=query, engine=engine)
            data = {"kind": "aieo.citation", "check": str(check.public_id), "assistant": str(assistant.public_id)}
            check.run = start(user, data, trigger=trigger)
            check.save(update_fields=["run"])
            made.append(check)
        now = timezone.now()
        query.last_checked_at = now
        query.next_check_at = now + timedelta(days=query.interval_days) if query.interval_days else None
        query.save(update_fields=["last_checked_at", "next_check_at", "updated_at"])
    return made


def cited(domain: str, answer: str, sources: list[dict]) -> dict:
    """Whether an engine's answer cites `domain`: a source on it (its rank is the position), or the domain named in
    the answer itself."""
    bare = _bare(domain)

    def on(url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        return bool(host) and (host == bare or host.endswith(f".{bare}"))

    urls = [s.get("url", "") for s in sources]
    hits = [u for u in urls if on(u)]
    position = next((i for i, u in enumerate(urls, start=1) if on(u)), None)
    named = bool(re.search(rf"(?<![\w.-]){re.escape(bare)}(?![\w-]|\.\w)", answer.lower()))
    return {"cited": bool(hits) or named, "position": position, "cited_urls": hits}


def due_queries():
    return CitationQuery.objects.filter(active=True, interval_days__gt=0, next_check_at__lte=timezone.now())


def claim(pk: int) -> bool:
    """Move a due query's next check on before it is asked, so a later tick never asks it twice."""
    query = CitationQuery.objects.filter(pk=pk).first()
    if query is None:
        return False
    after = timezone.now() + timedelta(days=query.interval_days or 1)
    return bool(due_queries().filter(pk=pk).update(next_check_at=after))


def share_of_voice(user, *, site=None, days: int = 90) -> dict:
    """Per engine, over the last `days`: how many checks cited the domain, and the same by week (the trend)."""
    since = timezone.now() - timedelta(days=days)
    checks = CitationCheck.objects.visible_to(user, site).filter(status=CitationCheck.READY, checked_at__gte=since)
    by_engine, weeks = {}, {}
    for engine, when, hit in checks.values_list("engine", "checked_at", "cited"):
        row = by_engine.setdefault(engine, {"engine": engine, "checks": 0, "cited": 0})
        row["checks"] += 1
        row["cited"] += 1 if hit else 0
        week = (when - timedelta(days=when.weekday())).date().isoformat()
        slot = weeks.setdefault((week, engine), {"week": week, "engine": engine, "checks": 0, "cited": 0})
        slot["checks"] += 1
        slot["cited"] += 1 if hit else 0
    for row in [*by_engine.values(), *weeks.values()]:
        row["rate"] = round(row["cited"] / row["checks"], 3)
    return {
        "days": days,
        "engines": sorted(by_engine.values(), key=lambda r: r["engine"]),
        "weeks": sorted(weeks.values(), key=lambda r: (r["week"], r["engine"])),
    }


# ── connectors and priorities ──────────────────────────────────────────────


def connector_for(site, kind: str, *, user) -> Connector:
    """A site's connector of `kind`, made (switched off, without a credential) the first time it is configured."""
    if kind not in dict(Connector.KINDS):
        raise Invalid(f"a connector is one of {', '.join(dict(Connector.KINDS))}")
    row = Connector.objects.filter(site=site, kind=kind).first() or Connector(site=site, kind=kind, enabled=False)
    if not row.can_edit(user):
        raise Forbidden(f"{user} may not configure {kind} for site {site.pk}")
    if row.pk is None:
        row.save()
    return row


def sync(connector: Connector, *, user=None) -> Connector:
    """Fetch the connector's report now, in a worker."""
    from .tasks import sync_connector

    if user is not None and not connector.can_edit(user):
        raise Forbidden(f"{user} may not sync this connector")
    if not connector.enabled:
        raise Conflict("switch the connector on before syncing it")
    if not connector.has_credential:
        raise Conflict("give the connector its credential first")
    if connector.status == Connector.SYNCING:
        raise Conflict("the connector is syncing already")
    Connector.objects.filter(pk=connector.pk).update(status=Connector.SYNCING, error="")
    connector.status = Connector.SYNCING
    transaction.on_commit(lambda: sync_connector.delay(connector.pk))
    return connector


@transaction.atomic
def rotate_credentials(**_signal) -> int:
    """Every connector's credential under the AI layer's first key, for `manage.py rotate_ai_credentials` (it sends
    `ai.crypto.credentials_rotated` in its transaction; apps.py connects this). One no key can read stops the
    rotation, naming the connector, before anything is written. How many it re-encrypted."""
    rows = list(Connector.objects.exclude(credential_encrypted="").select_related("site"))
    fresh = []
    for connector in rows:
        try:
            fresh.append(crypto.encrypt(connector.get_credential()))
        except crypto.InvalidToken as e:
            raise providers.NotConfigured(
                f"the credential of the {connector} connector was encrypted with a key that is gone: add that key to "
                "AI_CREDENTIAL_KEYS (or its SECRET_KEY to SECRET_KEY_FALLBACKS) and rotate again, or give the "
                "connector its credential again"
            ) from e
    for connector, credential in zip(rows, fresh, strict=True):
        Connector.objects.filter(pk=connector.pk).update(credential_encrypted=credential)
    return len(rows)


def latest(site, report: str, *, before=None) -> ConnectorData | None:
    """A site's last rows of a report — or the ones kept before `before` (rows are kept in the order they came)."""
    rows = ConnectorData.objects.filter(connector__site=site, report=report).order_by("-pk")
    if before is not None:
        rows = rows.filter(pk__lt=before.pk)
    return rows.first()


def priorities(site) -> dict:
    """The ranked content-update queue and the quick wins: Search Console's last rows through AIEO's opportunity
    rule — the trend is the change in impressions since the sync before, and a query that names one of the site's
    target keywords is a business priority."""
    snapshot = latest(site, "queries")
    if snapshot is None:
        return {"site": site.pk, "fetched_at": None, "queue": [], "quick_wins": []}
    before = latest(site, "queries", before=snapshot)
    previous = {(r.get("query"), r.get("page")): r for r in (before.rows if before else [])}
    keywords = [k.lower() for k in (signals(site).get("keywords") or [])]
    queue = []
    for row in snapshot.rows:
        query = str(row.get("query") or "")
        was = previous.get((row.get("query"), row.get("page")))
        impressions = int(row.get("impressions") or 0)
        trend = 0.0
        if was and was.get("impressions"):
            trend = max(-50.0, min(50.0, (impressions - int(was["impressions"])) / int(was["impressions"]) * 100))
        business = 1.0 if any(k and k in query.lower() for k in keywords) else 0.5
        scored = analyzers.opportunity(
            position=float(row.get("position") or 50),
            impressions=impressions,
            ctr=float(row.get("ctr") or 0),
            trend_delta=trend,
            business_priority=business,
        )
        queue.append(
            {
                "query": query,
                "page": row.get("page") or "",
                "clicks": int(row.get("clicks") or 0),
                "impressions": impressions,
                "ctr": float(row.get("ctr") or 0),
                "position": float(row.get("position") or 0),
                "opportunity_score": scored["score"],
                "components": scored["components"],
            }
        )
    queue.sort(key=lambda item: item["opportunity_score"], reverse=True)
    return {
        "site": site.pk,
        "fetched_at": snapshot.fetched_at,
        "queue": queue,
        "quick_wins": [q for q in queue if q["opportunity_score"] >= 60][:10],
    }


# ── the lifecycle ──────────────────────────────────────────────────────────


def lifecycle(user, site) -> dict:
    """Where a site's content is in AIEO's lifecycle — topics, research, drafts, rewrites waiting for review,
    published pages, landing pages, audits — each stage counted from the platform's own rows."""
    from ideas.models import Idea
    from research.models import Source
    from suggestions.models import Suggestion

    from .models import LandingPage

    pages = Page.objects.descendant_of(site.root_page).type(BasePage) if site is not None else Page.objects.none()
    in_site = Q(site=site) | Q(site__isnull=True)
    rewrites = Suggestion.objects.visible_to(user, site).filter(
        status=Suggestion.PENDING, run__input__kind="aieo.rewrite"
    )
    return {
        "topics": Idea.objects.visible_to(user).filter(in_site).count(),
        "research": Source.objects.visible_to(user).filter(in_site).count(),
        "drafts": pages.filter(live=False).count(),
        "rewrites": rewrites.values("run").distinct().count(),
        "review_required": Suggestion.objects.visible_to(user, site).filter(status=Suggestion.PENDING).count(),
        "published": pages.filter(live=True).count(),
        "landing_pages": LandingPage.objects.descendant_of(site.root_page).count() if site is not None else 0,
        "audits": Audit.objects.visible_to(user, site).count(),
        "average_score": _average(Audit.objects.visible_to(user, site)),
    }


def _average(rows) -> float | None:
    scores = list(rows.filter(status=Audit.READY, score__isnull=False).values_list("score", flat=True)[:1000])
    return round(mean(scores), 1) if scores else None


def site_of(site_id) -> Site | None:
    return Site.objects.filter(pk=site_id).first() if site_id else None
