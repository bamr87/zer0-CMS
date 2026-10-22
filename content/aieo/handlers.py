"""What AIEO's runs do in the worker — run kinds of the AI layer's `assistant` agent (`ai.handlers.register`), so
each model call is a step of the run with its tokens and cost, under the definition's limits, and the run is
followed on `/api/v2/agent-runs/<id>/stream/` like any other:

* `aieo.audit` — read what the audit names (a text as kept; a page's latest revision, if its starter still edits
  it; a URL through `research.fetch`, robots.txt first; a site crawled through the same fetcher), score every
  document with the heuristics, and — when a model's evaluation was asked for — have the bundled evaluator score the
  first one with AIEO's system prompt, rubric and the library's patterns; a provider that fails leaves the heuristic
  score in place and says why (`fallback`). A visual audit adds a screenshot (aieo/visual.py) the evaluator sees.
* `aieo.rewrite` — optimize (enhance or expand), scrub, rewrite or apply a pattern with the bundled assistant for
  it; on a page the rewrite is proposed there, block by block, through the tool registry (`content.propose_edit` as
  this agent for the person who asked), all of it or none; on a pasted text it is the run's output, a draft to read.
* `aieo.citation` — ask one engine (a provider) one tracked question through the citation probe, and record
  whether its answer cites the domain.

What a run names is asked again here, as for every AI run: the row must still be its starter's to use (`owned`),
the assistant visible to them (`used`), a page one they may edit. A run that ends without succeeding — even one
refused before reaching its handler — leaves its audit or check failed with the run's error (`settle`).
"""

import copy

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from agents.models import AgentRun
from agents.registry import ToolContext, registry
from ai import providers, rendering
from ai.handlers import Persona, generate, owned, register, used
from ai.models import Assistant
from ai.providers.base import InvalidOutput, ProviderError
from ai.services import acting_for, check_page, stable_id
from research import fetch

from . import crawl, parser, scoring, services, visual
from .models import Audit, CitationCheck, CitationQuery, Pattern, library

PROPOSE = "content.propose_edit"
SCREENSHOT = (
    "\n\n## Screenshot\n\nA screenshot of the live page is attached. Use it to evaluate visual layout, design "
    "quality, information hierarchy, readability, and UX signals that affect AI citability. Include a "
    "`visual_analysis` section in your response."
)


def _assistant(key: str, run: AgentRun) -> Assistant:
    row = Assistant.objects.filter(public_id=stable_id("bundled-assistant", key)).first()
    if row is None:
        raise ValueError(f"the bundled assistant {key!r} is missing: run manage.py migrate")
    return used(row, run)


# ── audits ─────────────────────────────────────────────────────────────────


def _documents(audit: Audit, run: AgentRun) -> tuple[list[dict], dict]:
    """What the audit reads — [{url, title, content, format, error}] — and, for a site, how it was crawled."""
    if audit.kind == Audit.TEXT:
        return [{"url": "", "title": audit.title, "content": audit.content, "format": audit.format}], {}
    if audit.kind == Audit.PAGE:
        if audit.page_id is None:
            raise ValueError("the page this audit was of is gone")
        page = services.editable(run.started_by, audit.page)
        return [{"url": page.full_url or "", "title": page.title, "content": services.page_markdown(page)}], {}
    if audit.kind == Audit.URL:
        if fetch.robots(audit.url) == fetch.DISALLOWED:
            raise fetch.FetchError("the site's robots.txt asks robots not to fetch this page")
        got = fetch.get(audit.url)
        if got.status >= 400:
            raise fetch.FetchError(f"the site answered HTTP {got.status}")
        kind = got.content_type.split(";", 1)[0].strip().lower()
        if kind in crawl.HTML:
            body = got.text()
            soup = BeautifulSoup(body, "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else ""
            return [{"url": got.url, "title": title, "content": body, "format": Audit.HTML}], {}
        if kind.startswith("text/"):
            return [{"url": got.url, "title": "", "content": fetch.decode(got.body, got.charset)}], {}
        raise fetch.FetchError(f"{kind or 'this'} is not a web page or text")
    found = crawl.crawl(audit.url, max_pages=audit.max_pages)
    documents = [
        {"url": p.url, "title": p.title, "content": p.html, "format": Audit.HTML, "error": p.error, "how": p.source}
        for p in found.pages
    ]
    if not any(not d["error"] for d in documents):
        first = documents[0]["error"] if documents else "nothing to crawl"
        raise fetch.FetchError(f"no page of the site could be read: {first}")
    links = crawl.link_map(found.pages, audit.url)
    return documents, {"discovery": found.discovery, "robots": found.robots, "link_map": links}


def _evaluate(run, ctx, audit: Audit, parsed: dict, patterns: list[dict], extra: dict, png: bytes | None) -> dict:
    """A model's evaluation, as a score: the bundled evaluator, its schema rebuilt from the library's patterns."""
    assistant = _assistant(services.EVALUATOR, run)
    persona = Persona.of(assistant)
    if audit.provider:
        persona.provider = audit.provider
    persona.schema = scoring.evaluation_schema(persona.schema or {}, patterns)
    persona.render_template = ""
    request = rendering.prompt(persona.prompt_template, scoring.evaluation_prompt(parsed, patterns))
    content = request
    if png is not None:
        sees = "vision" in providers.get(persona.provider or providers.default_slug()).capabilities
        content = [{"type": "text", "text": request + SCREENSHOT}, visual.image_part(png)] if sees else request
    out = generate(run, ctx, persona, [{"role": "user", "content": content}])
    return scoring.from_evaluation(out["json"], parsed, patterns, provider=out["provider"], model=out["model"], **extra)


def _page_summary(doc: dict, result: dict | None) -> dict:
    row = {"url": doc.get("url", ""), "title": doc.get("title", ""), "found_by": doc.get("how", "seed")}
    if result is None:
        return {**row, "error": doc.get("error", ""), "score": None, "grade": "", "word_count": 0}
    return {
        **row,
        "error": "",
        "score": result["score"],
        "grade": result["grade"],
        "word_count": result["word_count"],
        "scoring_method": result["scoring_method"],
        "gaps": len(result["gaps"]),
        "dimensions": result["dimensions"],
    }


@register("aieo.audit")
def audit(run: AgentRun, ctx: ToolContext) -> dict:
    row = owned(Audit, run.input.get("audit"), run, edit=True)
    Audit.objects.filter(pk=row.pk).update(status=Audit.RUNNING, error="")
    patterns = library()
    extra = services.signals(row.site)
    try:
        documents, site = _documents(row, run)
    except fetch.FetchError as e:  # what could not be fetched is the audit's answer, said plainly
        Audit.objects.filter(pk=row.pk).update(status=Audit.FAILED, error=str(e), updated_at=timezone.now())
        raise
    scored = []
    for doc in documents:
        if doc.get("error"):
            scored.append((doc, None, None))
            continue
        parsed = parser.parse(doc["content"], doc.get("format", Audit.MARKDOWN))
        scored.append((doc, parsed, scoring.heuristic(parsed, patterns, **extra)))
    lead = next(i for i, (_, parsed, _) in enumerate(scored) if parsed is not None)
    doc, parsed, result = scored[lead]
    notes, png, shot = {}, None, ""
    if row.visual:
        try:
            png = visual.capture(doc["url"] or row.url)
            shot = default_storage.save(f"aieo/screenshots/{row.public_id}.png", ContentFile(png))
        except visual.Unavailable as e:
            notes["visual"] = str(e)
    if row.method == Audit.AI:
        try:
            result = _evaluate(run, ctx, row, parsed, patterns, extra, png)
        except (ProviderError, InvalidOutput) as e:
            notes["fallback"] = f"the model's evaluation failed, so the heuristics scored it: {e}"
    scored[lead] = (doc, parsed, result)
    pages = [_page_summary(d, r) for d, _, r in scored] if row.kind == Audit.SITE else []
    score = result["score"]
    if row.kind == Audit.SITE:
        read = [p["score"] for p in pages if p["score"] is not None]
        score = round(sum(read) / len(read), 1)
        notes["site"] = {**site, "pages": len(read), "unread": len(pages) - len(read)}
    with transaction.atomic():
        fresh = Audit.objects.select_for_update().get(pk=row.pk)
        fresh.status, fresh.error = Audit.READY, ""
        fresh.score, fresh.grade = score, scoring.grade(score)
        fresh.scoring_method = result["scoring_method"]
        fresh.result = {**result, **notes}
        fresh.pages = pages
        fresh.content_hash = parsed.get("content_hash", "")
        fresh.title = fresh.title or doc.get("title", "")[:500]
        fresh.screenshot = shot or fresh.screenshot
        fresh.audited_at = timezone.now()
        fresh.save()
        fresh.benchmark = services.benchmark(fresh)
        fresh.save(update_fields=["benchmark"])
    return {"audit": str(row.public_id), "score": score, "grade": fresh.grade, "scoring_method": fresh.scoring_method}


# ── rewrites ───────────────────────────────────────────────────────────────


def _propose(run: AgentRun, ctx: ToolContext, page, operations, rationale: str) -> list[int]:
    """Every operation as a suggestion on `page`, through the registry as this agent acting for the run's starter,
    each call a step of the run — all of them, or (a refusal) none."""
    proposer = copy.copy(ctx.agent)  # this call may use the one propose tool its definition lists, and nothing else
    proposer.tools = [tool for tool in ctx.agent.tools or [] if tool == PROPOSE]
    acting = acting_for(ToolContext(user=ctx.user, agent=proposer, run=run, trigger=ctx.trigger, extra=ctx.extra))
    made = []
    with transaction.atomic():
        for op, block_id, block in operations:
            args = {"page_id": page.pk, "op": op, "rationale": rationale[:2000]}
            if block_id:
                args["block_id"] = block_id
            if block is not None:
                args["block"] = block
            made.append(registry.call(PROPOSE, args, acting)["suggestion_id"])
    return made


@register("aieo.rewrite")
def rewrite(run: AgentRun, ctx: ToolContext) -> dict:
    mode, style = run.input.get("mode", "optimize"), run.input.get("style", "preserve")
    assistant = _assistant(services.MODES[mode], run)
    page = run.target
    patterns = library()
    if page is not None:
        page = services.editable(run.started_by, page)
        check_page(run.started_by, page, acting_for(ctx))
        title, body = page.title, services.page_markdown(page, title=False).strip()
        extra = services.signals(page.get_site())
        before = scoring.score(f"# {title}\n\n{body}\n", "markdown", patterns, **extra)
    else:
        title, body, extra = "", run.input.get("content", ""), {}
        before = scoring.score(body, "markdown", patterns)
    if mode in ("optimize", "expand"):
        request = services.optimization_prompt(body, before["gaps"], style, expand=mode == "expand")
    elif mode == "pattern":
        pattern = Pattern.objects.filter(name=run.input.get("pattern"), enabled=True).first()
        if pattern is None:
            raise ValueError(f"the pattern {run.input.get('pattern')!r} is not in the library")
        request = services.pattern_prompt(body, pattern.as_spec(), style)
    else:
        request = f"Content:\n{body}"
    if title:
        request = f"The page is titled {title!r}; its title is not part of the content.\n\n{request}"
    persona = Persona.of(assistant)
    out = generate(run, ctx, persona, [{"role": "user", "content": rendering.prompt(persona.prompt_template, request)}])
    markdown = services.without_title(out["markdown"], title) if title else out["markdown"].strip()
    if not markdown:
        raise InvalidOutput("the rewrite came back empty")
    after = scoring.score(f"# {title}\n\n{markdown}\n" if title else markdown, "markdown", patterns, **extra)
    made = []
    if page is not None:
        blocks = page.get_latest_revision_as_object().body.get_prep_value()
        operations = services.proposals(list(blocks), markdown)
        why = {"optimize": "optimized for AI citability", "expand": "expanded for AI citability"}.get(mode, mode)
        if mode == "pattern":
            why = f"applied the {run.input.get('pattern')} pattern"
        made = _propose(run, ctx, page, operations, f"AIEO {why} (score {before['score']} → {after['score']})")
    return {
        "markdown": markdown,
        "mode": mode,
        "score_before": before["score"],
        "score_after": after["score"],
        "uplift": round(after["score"] - before["score"], 1),
        "gaps": before["gaps"][:10],
        "provider": out["provider"],
        "model": out["model"],
        "suggestions": made,
    }


# ── citations ──────────────────────────────────────────────────────────────


@register("aieo.citation")
def citation(run: AgentRun, ctx: ToolContext) -> dict:
    check = CitationCheck.objects.select_related("query").get(public_id=run.input.get("check"))
    query = owned(CitationQuery, check.query.public_id, run)
    persona = Persona.of(used(Assistant.objects.get(public_id=run.input.get("assistant")), run))
    persona.provider = check.engine
    out = generate(run, ctx, persona, [{"role": "user", "content": f"Question: {query.prompt}"}])
    data = out["json"]
    found = services.cited(query.domain, data["answer"], data["sources"])
    CitationCheck.objects.filter(pk=check.pk).update(
        status=CitationCheck.READY,
        model=out["model"][:255],
        answer=data["answer"],
        sources=data["sources"],
        error="",
        **found,
    )
    return {"check": str(check.public_id), "engine": check.engine, **found}


def review(run: AgentRun, ctx: ToolContext) -> dict:
    """The citability review (the `aieo` agent's handler, a workflow task): the page's latest revision scored with
    the heuristics, passed at `AIEO_REVIEW_MIN_SCORE` or above, its worst gaps as the comments."""
    page = run.target.specific
    result = scoring.score(services.page_markdown(page), "markdown", library(), **services.signals(page.get_site()))
    floor = settings.AIEO_REVIEW_MIN_SCORE
    passed = result["score"] >= floor
    comments = [] if passed else [{"text": f"{g['category']}: {g['description']}"[:2000]} for g in result["gaps"][:5]]
    summary = f"citability {result['score']} ({result['grade']}); a page passes at {floor:g}"
    registry.call("review.submit_verdict", {"passed": passed, "summary": summary, "comments": comments}, ctx)
    return {"score": result["score"], "grade": result["grade"]}


def settle(sender, run: AgentRun, **kwargs) -> None:
    """An audit or a citation check left waiting by a run that ended without succeeding takes the run's error."""
    if run.status == AgentRun.SUCCEEDED or (run.input or {}).get("kind") not in ("aieo.audit", "aieo.citation"):
        return
    error = run.error or f"the run was {run.status}"
    Audit.objects.filter(run=run, status__in=(Audit.PENDING, Audit.RUNNING)).update(
        status=Audit.FAILED, error=error, updated_at=timezone.now()
    )
    CitationCheck.objects.filter(run=run, status=CitationCheck.QUEUED).update(status=CitationCheck.FAILED, error=error)
