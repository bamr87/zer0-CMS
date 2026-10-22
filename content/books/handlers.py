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

- **draft** — replaces the chapter's prose (the blocks under "Chapter Body"),
- **continue** — is added after where the prose stops,
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

from . import context, files, library

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
    rm = library.Book.read(files.book_dir(book), files.book_tree(book))
    rm_chapter = rm.chapter(chapter.number) if chapter is not None else None
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


def _heading(block, starts: tuple[str, ...]) -> bool:
    return block["type"] == "heading" and block["value"]["text"].strip().lower().startswith(starts)


def prose_blocks(blocks: list[dict]) -> tuple[int | None, list[int]]:
    """The "Chapter Body" heading's index and the blocks under it; with no such
    heading, None and the blocks outside the scaffolding (library.prose_spans, by block)."""
    for i, block in enumerate(blocks):
        if _heading(block, library.PROSE_HEADINGS):
            level, under = int(block["value"]["level"]), []
            for j in range(i + 1, len(blocks)):
                if blocks[j]["type"] == "heading" and int(blocks[j]["value"]["level"]) <= level:
                    break
                under.append(j)
            return i, under
    prose, skipping = [], None
    for i, block in enumerate(blocks):
        if block["type"] == "heading":
            level = int(block["value"]["level"])
            if skipping is None or level <= skipping:
                skipping = level if _heading(block, library.SCAFFOLD_HEADINGS) else None
        elif skipping is None:
            prose.append(i)
    return None, prose


def _rule(text: str) -> tuple[str, str]:
    """`text` without a closing horizontal rule, and the rule (with its blank line) or ''."""
    match = RULE.search(text)
    return (text[: match.start()], "\n\n" + match.group(0).strip()) if match else (text, "")


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
    heading, prose = prose_blocks(blocks)
    after = blocks[heading]["id"] if heading is not None else (blocks[-1]["id"] if blocks else "")
    if not prose:
        return [("insert", after, {"type": "markdown", "value": text})]
    if task == "draft":
        _kept, rule = _rule(blocks[prose[-1]]["value"]) if blocks[prose[-1]]["type"] == "markdown" else ("", "")
        first = blocks[prose[0]]
        return [("replace", first["id"], {"type": "markdown", "value": text + rule})] + [
            ("delete", blocks[i]["id"], None) for i in prose[1:]
        ]
    last = blocks[prose[-1]]
    if last["type"] != "markdown":
        return [("insert", last["id"], {"type": "markdown", "value": text})]
    kept, rule = _rule(last["value"])
    return [("replace", last["id"], {"type": "markdown", "value": f"{kept.rstrip()}\n\n{text}{rule}"})]


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
