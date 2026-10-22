"""What research's runs do in the worker: summaries, cited answers, fact-checks
and web searches — run kinds of the AI layer's `assistant` agent
(`ai.handlers.register`), generated through `ai.handlers.generate` with a
bundled assistant's persona, so every model call is a step of the run with its
tokens and cost, under the definition's limits.

Every result is something a person reviews: a summary, the entities and the
passages worth quoting arrive on the source; an answer cites its sources by
label and each quote is checked against the source's own text (`verified`); a
fact-check's findings are kept on the check with the sources it read, and a
block's corrections — exact words and what they should say — are made together
in the block's own value and proposed as one suggestion on the draft through
the tool registry (`content.propose_edit`, as the assistant agent, for the
person who asked), for the editor to accept or reject. What a run uses is asked
again here, as for every AI run: the rows must still be its starter's to use,
and the draft one they may edit.
"""

import copy
import time
from collections import defaultdict
from dataclasses import asdict

from django.utils import timezone

from agents.models import AgentRun, AgentStep
from agents.registry import ToolContext, ToolError, registry
from ai import providers
from ai.handlers import Persona, generate, owned, register, used
from ai.models import Assistant
from ai.services import check_provider
from graph.embeddings import tokens

from . import services
from .models import Citation, Collection, FactCheck, Question, Source, placement
from .tasks import fetch_source

TEXT_LIMIT = 40_000  # characters of a source a summary reads
PROPOSE = "content.propose_edit"  # the one tool a fact-check proposes with (agents/definitions/assistant.yaml)


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
    row = Source.objects.filter(pk=source.pk).first()  # as it is now; a source deleted meanwhile stays gone
    if row is not None:  # saved, so its vector and its search entry read the summary too
        row.summary, row.entities, row.highlights = result["markdown"], data["entities"], data["quotes"]
        row.save(update_fields=["summary", "entities", "highlights", "updated_at"])
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


@register("research.fact_check")
def fact_check(run: AgentRun, ctx: ToolContext) -> dict:
    check = owned(FactCheck, run.input.get("fact_check"), run, edit=True)
    page = check.page.specific
    if not page.permissions_for_user(run.started_by).can_edit():
        raise PermissionError(f"page {page.pk} is not one {run.started_by} may edit")
    persona = _persona(run)
    blocks = {b["label"]: b for b in services.draft_blocks(page)}
    draft = "\n".join(f"[{label}] {b['text']}" for label, b in blocks.items())
    read, left_out = services.checked_sources(run.started_by, page, check.collection, draft)
    labelled = {f"S{i}": s for i, s in enumerate(read, start=1)}
    request = f'Draft "{page.title}":\n\n{draft}\n\nSources:\n\n{_sources(labelled, set(tokens(draft)))}'
    result = generate(run, ctx, persona, [{"role": "user", "content": request}])
    findings, fixes = [], defaultdict(list)
    for item in result["json"]["findings"]:
        label = item["block"].strip("[] ")
        sources = [labelled[s.strip("[] ")] for s in item["sources"] if s.strip("[] ") in labelled]
        find, replace = item.get("find", ""), item.get("replace", "")  # a schema seeded before spans has neither
        findings.append(
            {
                **{key: item[key] for key in ("claim", "verdict", "explanation")},
                "find": find,
                "replace": replace,
                "block": blocks[label]["id"] if label in blocks else "",
                "sources": [{"id": str(s.public_id), "title": s.title or s.url} for s in sources],
                "suggestion": None,
                "error": "",
            }
        )
        if label in blocks and item["verdict"] == "contradicted" and find.strip() and find != replace:
            fixes[label].append(findings[-1])
    for label, wrong in fixes.items():
        _correct(run, ctx, page, blocks[label], wrong)
    cited = set(Citation.objects.filter(page=page).values_list("source", flat=True))
    FactCheck.objects.filter(pk=check.pk).update(
        summary=result["json"]["summary"],
        findings=findings,
        sources=[{"id": str(s.public_id), "title": s.title or s.url, "cited": s.pk in cited} for s in read],
        left_out=left_out,
        updated_at=timezone.now(),
    )
    return {**result, "suggestions": sorted({f["suggestion"] for f in findings if f["suggestion"]})}


def _correct(run: AgentRun, ctx: ToolContext, page, block: dict, wrong: list[dict]) -> None:
    """A block's corrections made together — each finding's words replaced in the block's own value, so links and
    emphasis stay — and proposed as one `replace` suggestion through the tool registry, which checks the assistant
    agent's tools, its principal's right to edit the page, the page's policy, the starter's edit right and the rate,
    and records the call as a step of the run. A correction that cannot be made, or a refusal, is kept on its
    finding for the person who reads the check."""
    value, made = block["value"], []
    for finding in wrong:
        try:
            value = services.corrected(block["type"], value, finding["find"], finding["replace"])
            made.append(finding)
        except services.Uncorrectable as e:
            finding["error"] = str(e)
    if not made:
        return
    named = ", ".join(dict.fromkeys(s["title"] for f in made for s in f["sources"])) or "its sources"
    claims = "; ".join(f"{f['claim']} — {f['explanation']}" for f in made)
    args = {
        "page_id": page.pk,
        "op": "replace",
        "block_id": block["id"],
        "block": {"type": block["type"], "value": value},
        "rationale": f"Fact-check: {claims} (from {named})"[:2000],
    }
    proposer = copy.copy(ctx.agent)  # this call may use the one propose tool its definition lists, and nothing else
    proposer.tools = [tool for tool in ctx.agent.tools or [] if tool == PROPOSE]
    tool_ctx = ToolContext(user=ctx.user, agent=proposer, run=run, trigger=ctx.trigger, on_behalf_of=run.started_by)
    try:
        suggestion, error = registry.call(PROPOSE, args, tool_ctx)["suggestion_id"], ""
    except ToolError as e:
        suggestion, error = None, e.message
    for finding in made:
        finding["suggestion"], finding["error"] = suggestion, error


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
