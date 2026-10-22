"""The `books` agent's handler: what a book task does in the worker
(agents/definitions/books.yaml points here).

A run's target is the chapter it works on (or the book, for an outline; an
eval's target is a book and `input.chapter` names the chapter by number). The
handler asks again what the service checked — the assistant is still the
starter's to use, the page is still theirs to edit, and (in `generate`) the
provider is enabled and inside its budget — then assembles the book's context from its rendered files (books/context.py) and
makes the one model call through the AI layer's `generate` (the provider
registry, the runner's loop: a step with its tokens and cost, the output schema
validated). The assistant's tools are none: the book comes in the request.

What the result becomes:

- **draft** — replaces the chapter's prose: what is under "Chapter Body", else
  what is outside the outline scaffolding — found in the text as the read model
  finds it (`library.prose_spans`), so a chapter whose sections are `#` headings
  inside one Markdown block has only its prose replaced, never its outline,
  references or navigation;
- **continue** — is added where the prose stops, before its closing rule,
- **revise** — replaces the selected passage in the block that holds it,

each as suggestions proposed through the tool registry (`content.propose_edit`,
as the agent, on behalf of the person who asked — so their edit right on the
chapter is checked too), accepted or rejected by a person like any other
agent's. **check** (structured findings), **critique** and **outline** are the
run's output, which the studio shows; an outline is applied by the person.
"""

from __future__ import annotations

import re

from agents.registry import ToolContext, registry
from ai.handlers import Persona, generate
from ai.models import Assistant, usable
from ai.services import stable_id
from cms.models import BookPage, ChapterPage
from importers.markdown import block_to_markdown

from . import context, files, library
from .services import chapter_in, read

RULE = re.compile(r"\n*^(?:-{3,}|\*{3,}|_{3,})[ \t]*\Z", re.M)


def run(run, ctx) -> dict:
    data = run.input or {}
    task = context.TASKS.get(data.get("task"))
    if task is None:
        raise ValueError(f"unknown task {data.get('task')!r} (one of {', '.join(context.TASKS)})")
    book, chapter = target(run, task)
    if data.get("assistant"):
        assistant = Assistant.objects.filter(public_id=data["assistant"]).first()
    else:
        assistant = Assistant.objects.filter(public_id=stable_id("bundled-assistant", task.assistant)).first()
    if assistant is None:
        raise ValueError(f"no assistant {data.get('assistant') or task.assistant!r}")
    if run.trigger != "eval":
        if not usable(assistant, run.started_by):
            raise PermissionError(f"assistant {assistant.public_id} is not {run.started_by}'s to use")
        page = chapter or book
        if run.started_by is None or not page.permissions_for_user(run.started_by).can_edit():
            raise PermissionError(f"page {page.pk} is not one {run.started_by} may edit")
    rm, rm_chapter = chapter_in(book, chapter) if chapter is not None else (read(book), None)
    prompt = context.request(
        rm, rm_chapter, task, instruction=data.get("instruction", ""), selection=data.get("selection", "")
    )
    out = generate(run, ctx, Persona.of(assistant), [{"role": "user", "content": prompt}])
    result = {**out, "task": task.key, "book": book.pk, "chapter": chapter.pk if chapter else None}
    if task.key in ("draft", "continue", "revise"):
        result["suggestions"] = propose(run, ctx, chapter, task.key, out["markdown"], data.get("selection", ""))
    return result


def target(run, task) -> tuple[BookPage, ChapterPage | None]:
    page = run.target.specific if run.target is not None else None
    if isinstance(page, ChapterPage):
        return page.get_parent().specific, page
    if not isinstance(page, BookPage):
        raise ValueError("a book task runs on a book or one of its chapters")
    chapter = None
    if (run.input or {}).get("chapter") is not None:
        chapter = next((c for c in files.book_chapters(page) if c.number == run.input["chapter"]), None)
        chapter = ChapterPage.objects.get(pk=chapter.pk) if chapter is not None else None
    if task.chapter and chapter is None:
        raise ValueError(f"{task.label} works on a chapter")
    return page, chapter


# ── the result as suggestions ──────────────────────────────────────────────


def prose_regions(blocks: list[dict]) -> list[tuple[int, int, int]]:
    """Where the chapter's prose is, as (block index, start, end) in each
    block's Markdown: the read model's prose spans (`library.prose_spans`, which
    reads `#` headings too) over the body as `from_blocks` joins it."""
    texts = [block_to_markdown(b["type"], b["value"]) for b in blocks]
    starts, at = [], 0
    for text in texts:
        starts.append(at)
        at += len(text) + 2  # from_blocks joins blocks with a blank line
    spans = []  # merged where they overlap (a "Body …" heading nested under "Chapter Body")
    for start, end in sorted(library.prose_spans("\n\n".join(texts))):
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
        else:
            spans.append((start, end))
    regions = []
    for start, end in spans:
        for i, text in enumerate(texts):
            lo, hi = max(start, starts[i]), min(end, starts[i] + len(text))
            if lo < hi and text[lo - starts[i] : hi - starts[i]].strip():
                regions.append((i, lo - starts[i], hi - starts[i]))
    return regions


def _rule(text: str) -> tuple[str, str]:
    """`text` without a closing horizontal rule, and the rule (with its blank line) or ''."""
    match = RULE.search(text)
    return (text[: match.start()], "\n\n" + match.group(0).strip()) if match else (text, "")


def _put(value: str, start: int, end: int, text: str) -> str:
    """`value` with its [start, end) replaced by `text`, the blank lines around that span kept."""
    span = value[start:end]
    lead, trail = span[: len(span) - len(span.lstrip())], span[len(span.rstrip()) :]
    if not text:  # cut: keep one of the separators, so what was either side stays apart
        return value[:start] + (trail or lead) + value[end:]
    return value[:start] + lead + text + trail + value[end:]


def plan(task: str, blocks: list[dict], text: str, selection: str = "") -> list[tuple[str, str, dict | None]]:
    """The edits that put `text` where the task says: (op, block id, block)."""
    text = text.strip()
    if not text:
        raise ValueError("the assistant returned no text")
    if task == "revise":
        passage = selection.strip()
        for block in blocks:
            if block["type"] == "markdown" and passage and passage in block["value"]:
                return [
                    ("replace", block["id"], {"type": "markdown", "value": block["value"].replace(passage, text, 1)})
                ]
        raise ValueError("the passage to revise is not in the chapter's latest revision")
    regions = prose_regions(blocks)
    if not regions:
        heading = next((b for b in blocks if _heading(b, library.PROSE_HEADINGS)), None)
        after = heading["id"] if heading else (blocks[-1]["id"] if blocks else "")
        return [("insert", after, {"type": "markdown", "value": text})]
    values = {i: blocks[i]["value"] for i, _s, _e in regions if blocks[i]["type"] == "markdown"}
    first, last = regions[0], regions[-1]
    if task == "draft":
        closing = _rule(values[last[0]][last[1] : last[2]].rstrip())[1] if last[0] in values else ""
        edits = [(region, text + closing if region == first else "") for region in regions]
    else:  # continue: after the prose, before the rule that closes it
        if last[0] not in values:
            return [("insert", blocks[last[0]]["id"], {"type": "markdown", "value": text})]
        kept, closing = _rule(values[last[0]][last[1] : last[2]].strip())
        edits = [(last, f"{kept.rstrip()}\n\n{text}{closing}".lstrip())]
    for (i, start, end), new in reversed(edits):  # back to front, so a block's earlier offsets stay right
        whole = i not in values or (start, end) == (0, len(values[i]))
        values[i] = None if whole and not new else new if whole else _put(values[i], start, end, new)
    return [
        ("delete", blocks[i]["id"], None)
        if values[i] is None
        else ("replace", blocks[i]["id"], {"type": "markdown", "value": values[i]})
        for i in sorted({i for (i, _s, _e), _new in edits})
    ]


def _heading(block, starts: tuple[str, ...]) -> bool:
    return block["type"] == "heading" and block["value"]["text"].strip().lower().startswith(starts)


def propose(run, ctx, chapter: ChapterPage, task: str, text: str, selection: str) -> list[int]:
    """The task's edits as suggestions on the chapter, through the registry."""
    blocks = list(chapter.get_latest_revision_as_object().body.get_prep_value())
    acting = ToolContext(
        user=ctx.user, agent=ctx.agent, run=run, trigger=ctx.trigger, extra=ctx.extra, on_behalf_of=run.started_by
    )
    rationale = f"{context.TASKS[task].label} for chapter {chapter.number}: {chapter.title}"
    ids = []
    for op, block_id, block in plan(task, blocks, text, selection):
        args = {"page_id": chapter.pk, "op": op, "rationale": rationale[:2000]}
        if block_id:
            args["block_id"] = block_id
        if block is not None:
            args["block"] = block
        ids.append(registry.call("content.propose_edit", args, acting)["suggestion_id"])
    return ids
