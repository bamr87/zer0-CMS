"""What research's runs do in the worker: summaries, cited answers, fact-checks
and web searches — run kinds of the AI layer's `assistant` agent
(`ai.handlers.register`), generated through `ai.handlers.generate` with a
bundled assistant's persona, so every model call is a step of the run with its
tokens and cost, under the definition's limits.

Every result is something a person reviews: a summary, the entities and the
passages worth quoting arrive on the source; an answer cites its sources by
label and each quote is checked against the source's own text (`verified`); a
fact-check's findings are kept on the check, and the ones with a correction
become suggestions on the draft from the assistant agent, for the editor to
accept or reject. What a run uses is asked again here, as for every AI run:
the rows must still be its starter's to use, and the draft one they may edit.
"""

import time
from dataclasses import asdict

from django.utils import timezone
from django.utils.html import escape

from agents.models import AgentRun, AgentStep
from agents.registry import ToolContext
from ai import providers
from ai.handlers import Persona, generate, owned, register, used
from ai.models import Assistant
from ai.services import check_provider
from cms.models import POLICY_ORDER, POLICY_SUGGEST
from graph.embeddings import tokens
from suggestions.services import SuggestionError, propose

from . import services
from .models import Collection, FactCheck, Question, Source, placement
from .tasks import embed_source, fetch_source

TEXT_LIMIT = 40_000  # characters of a source a summary reads


def _persona(run: AgentRun) -> Persona:
    return Persona.of(used(owned(Assistant, run.input.get("assistant"), run), run))


def _sources(labelled: dict, words: set) -> str:
    return "\n\n".join(
        f"[{label}] {s.title or s.url or 'Untitled'} — {s.url or 'no URL'}\n"
        + "\n…\n".join(services.passages(s, words))
        for label, s in labelled.items()
    )


@register("research.summarize")
def summarize(run: AgentRun, ctx: ToolContext) -> dict:
    source = owned(Source, run.input.get("source"), run, edit=True)
    clipped = len(source.text) > TEXT_LIMIT
    text = source.text[:TEXT_LIMIT] + ("\n\n[The rest of the source is left out.]" if clipped else "")
    request = f"Title: {source.title or 'Untitled'}\nURL: {source.url or 'none'}\n\n{text}"
    result = generate(run, ctx, _persona(run), [{"role": "user", "content": request}])
    data = result["json"]
    Source.objects.filter(pk=source.pk).update(
        summary=result["markdown"], entities=data["entities"], highlights=data["quotes"], updated_at=timezone.now()
    )
    services.queue(embed_source, source.pk)  # its vector reads the summary too
    return {**result, "source": str(source.public_id)}


@register("research.answer")
def answer(run: AgentRun, ctx: ToolContext) -> dict:
    question = owned(Question, run.input.get("question"), run, edit=True)
    persona = _persona(run)
    pool = services.visible_sources(run.started_by, question.collection).filter(status=Source.READY)
    labelled = {f"S{i}": s for i, s in enumerate(services.ranked(pool, question.text), start=1)}
    if not labelled:
        Question.objects.filter(pk=question.pk).update(answer="None of the sources speaks to this question.")
        return {"text": "", "markdown": "", "sources": []}
    request = f"Question: {question.text}\n\nSources:\n\n{_sources(labelled, set(tokens(question.text)))}"
    result = generate(run, ctx, persona, [{"role": "user", "content": request}])
    cited = []
    for citation in result["json"]["citations"]:
        label = citation["source"].strip("[] ")
        source = labelled.get(label)
        if source is not None:
            cited.append(
                {
                    "label": label,
                    "source": str(source.public_id),
                    "title": source.title or source.url,
                    "quote": citation["quote"],
                    "verified": services.same_words(citation["quote"], source.text),
                }
            )
    Question.objects.filter(pk=question.pk).update(
        answer=result["json"]["answer"], citations=cited, updated_at=timezone.now()
    )
    return {**result, "sources": [str(s.public_id) for s in labelled.values()]}


def _replacement(block: dict, correction: str) -> dict:
    """The block as the correction would have it, in its own type's shape."""
    if block["type"] == "markdown":
        return {"type": "markdown", "value": correction}
    if block["type"] == "paragraph":
        return {"type": "paragraph", "value": f"<p>{escape(correction)}</p>"}
    return {"type": block["type"], "value": {**block["value"], "text": correction}}


@register("research.fact_check")
def fact_check(run: AgentRun, ctx: ToolContext) -> dict:
    check = owned(FactCheck, run.input.get("fact_check"), run, edit=True)
    page = check.page.specific
    if not page.permissions_for_user(run.started_by).can_edit():
        raise PermissionError(f"page {page.pk} is not one {run.started_by} may edit")
    persona = _persona(run)
    blocks = {b["label"]: b for b in services.draft_blocks(page)}
    words = set(tokens(" ".join(b["text"] for b in blocks.values())))
    labelled = {
        f"S{i}": s
        for i, s in enumerate(services.checked_sources(run.started_by, page, check.collection)[: services.TOP], start=1)
    }
    draft = "\n".join(f"[{label}] {b['text']}" for label, b in blocks.items())
    request = f'Draft "{page.title}":\n\n{draft}\n\nSources:\n\n{_sources(labelled, words)}'
    result = generate(run, ctx, persona, [{"role": "user", "content": request}])
    proposes = POLICY_ORDER.index(page.effective_policy(ctx.policy)) >= POLICY_ORDER.index(POLICY_SUGGEST)
    findings = []
    for item in result["json"]["findings"]:
        block = blocks.get(item["block"].strip("[] "))
        sources = [labelled[s.strip("[] ")] for s in item["sources"] if s.strip("[] ") in labelled]
        finding = {
            **{key: item[key] for key in ("claim", "verdict", "explanation", "correction")},
            "block": block["id"] if block else "",
            "sources": [{"id": str(s.public_id), "title": s.title or s.url} for s in sources],
            "suggestion": None,
            "error": "",
        }
        if block is not None and item["verdict"] != "supported" and item["correction"].strip() and proposes:
            named = ", ".join(s.title or s.url for s in sources) or "its sources"
            try:
                finding["suggestion"] = propose(
                    target=page,
                    op="replace",
                    user=ctx.user,
                    run=run,
                    agent=run.agent,
                    block_id=block["id"],
                    payload=_replacement(block, item["correction"].strip()),
                    rationale=f"Fact-check ({item['verdict']}): {item['claim']} — {item['explanation']} (from {named})",
                ).pk
            except SuggestionError as e:
                finding["error"] = str(e)
        findings.append(finding)
    FactCheck.objects.filter(pk=check.pk).update(
        summary=result["json"]["summary"], findings=findings, updated_at=timezone.now()
    )
    return {**result, "suggestions": [f["suggestion"] for f in findings if f["suggestion"]]}


@register("research.search")
def search(run: AgentRun, ctx: ToolContext) -> dict:
    person = run.started_by
    collection = owned(Collection, run.input["collection"], run) if run.input.get("collection") else None
    provider = providers.get(check_provider(run.input.get("provider", "")))
    started = time.monotonic()
    found = provider.search(run.input["query"], max_results=int(run.input.get("max_results") or 5))
    results = [asdict(hit) for hit in found.data or []]
    AgentStep.objects.create(
        run=run,
        idx=run.next_step_index(),
        kind=AgentStep.LLM,
        name=f"web_search · {found.model or provider.name}",
        args={"query": run.input["query"]},
        result={"results": results},
        latency_ms=int((time.monotonic() - started) * 1000),
        tokens=found.tokens,
        cost_usd=found.cost_usd,
    )
    run.tokens += found.tokens
    run.cost_usd += found.cost_usd
    run.llm_backend = provider.name
    run.save(update_fields=["tokens", "cost_usd", "llm_backend"])
    kept = []
    for hit in found.data or []:
        if not hit.url.startswith(("http://", "https://")):
            continue
        if Source.objects.visible_to(person).filter(url=hit.url, collection=collection).exists():
            continue
        source = Source.objects.create(
            owner=person,
            kind=Source.URL,
            url=hit.url[:2000],
            title=hit.title[:500],
            collection=collection,
            status=Source.PENDING,
            metadata={"search": {"query": run.input["query"], "snippet": hit.snippet, "published": hit.published}},
            **placement(person, collection),
        )
        services.queue(fetch_source, source.pk)
        kept.append(str(source.public_id))
    return {"query": run.input["query"], "results": results, "sources": kept}
