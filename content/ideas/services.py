"""What the ideas app does: every command, so its views stay thin (TARGET.md
§ Rules that keep models and views manageable).

- **Capture** an idea from anywhere — the studio, the editor, later the
  extension — optionally from AIEO's topic template.
- **Brainstorm**: a conversation with the bundled Brainstormer (or another
  assistant), through `ai.services.post_message`, so the reply is a run of the
  `assistant` agent whose result is validated against the idea-list schema;
  a person **keeps** the ideas they want from a reply — nothing becomes an
  idea unseen.
- **Cluster and de-duplicate** by meaning: every idea's vector is stored in
  `graph.Embedding` by a worker (`ideas.tasks.embed_idea`, through the
  provider registry when `EMBEDDING_BACKEND` names one, the deterministic
  hashing embedder otherwise), and clusters and likely duplicates are read
  from the stored vectors — no model call in the request, and on Postgres the
  pairs are compared by pgvector in the database (`alike`). A person
  **merges** a duplicate.
- **Promote** an idea to a brief (the AI layer's; its sources become the
  brief's citations, which its writer reads), an article draft or a book
  draft (`cms.services.create_draft`: a draft, never published).
"""

import math
from collections import defaultdict
from itertools import combinations

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction

from ai import services as ai
from ai.models import Assistant, Brief, Conversation, Message, usable
from api.pages import service_errors
from cms import services as cms
from cms.models import ArticlePage, BookPage, stable_hash
from graph.embeddings import get_embedder
from graph.models import Embedding
from graph.services import embed_object
from ops.errors import Conflict, Forbidden, Invalid, Unavailable
from research.models import Citation, Source, placement

from .models import Idea, Vote

BRAINSTORMER, WRITER = "brainstormer", "article-writer"
KINDS = {
    "angles": "angles to take",
    "headlines": "headlines",
    "outlines": "outlines (each a working title and its sections, as a list)",
}
TEMPLATES = {
    # AIEO's topic template (apps/aieo/frontend/src/pages/TopicsPage.tsx), its front matter as the idea's fields.
    "topic": "## Why this topic matters\n\n_The angle, the audience, and why an AI engine would cite a page about it._"
    "\n\n## Key questions to answer\n\n- \n\n## Notes\n",
}
CLUSTER_LIMIT = 300  # ideas compared at once


def bundled(key: str, user) -> Assistant:
    row = Assistant.objects.filter(public_id=ai.stable_id("bundled-assistant", key)).first()
    if row is None:
        raise Unavailable(f"the bundled assistant {key!r} is missing: run manage.py migrate")
    if not usable(row, user):
        raise Forbidden(f"the {row.name} assistant is not one {user} may use")
    return row


def _changing(idea: Idea, user):
    if not idea.can_edit(user):
        raise Forbidden(f"idea {idea.public_id} is not {user}'s to change")
    return idea


# ── capturing and voting ───────────────────────────────────────────────────


def capture(user, text: str, *, board=None, url: str = "", tags=(), template: str = "") -> Idea:
    """An idea from a line or a few: the first line is its title, the rest its notes (or a template's)."""
    lines = text.strip().splitlines()
    if not lines:
        raise Invalid("an idea needs a title")
    if template and template not in TEMPLATES:
        raise Invalid(f"no template {template!r}; there is {', '.join(TEMPLATES)}")
    notes = "\n".join(lines[1:]).strip() or TEMPLATES.get(template, "")
    idea = Idea.objects.create(
        owner=user,
        board=board,
        title=lines[0].strip()[:255],
        notes=notes,
        url=url,
        origin=Idea.CAPTURED,
        **placement(user, board),
    )
    if tags:
        idea.tags.add(*tags)
    return idea


def vote(idea: Idea, user, *, up: bool = True) -> None:
    """One vote per person; voting again changes nothing, and a vote can be taken back."""
    if up:
        Vote.objects.get_or_create(idea=idea, user=user)
    else:
        Vote.objects.filter(idea=idea, user=user).delete()


# ── brainstorming ──────────────────────────────────────────────────────────


def brainstorm(user, prompt: str, *, kind="angles", count=8, board=None, conversation=None, sources=(), assistant=None):
    """Ask an assistant for ideas: a message in a brainstorm conversation (a new one, or the session to continue)
    whose reply — a run — lists ideas to keep. Returns (conversation, message, reply, run)."""
    if not prompt.strip():
        raise Invalid("a brainstorm needs something to think about")
    if kind not in KINDS:
        raise Invalid(f"brainstorm {', '.join(KINDS)}; not {kind!r}")
    assistant = assistant or bundled(BRAINSTORMER, user)
    if conversation is None:
        title = f"Brainstorm: {prompt.strip()[:120]}"
        conversation = Conversation.objects.create(owner=user, title=title, assistant=assistant)
    elif not conversation.can_edit(user):
        raise Forbidden(f"conversation {conversation.public_id} is not {user}'s to continue")
    parts = [f"Brainstorm {count} {KINDS[kind]} for: {prompt.strip()}"]
    if board is not None:
        parts.append(
            f"They are for the board “{board.name}”" + (f": {board.description}" if board.description else ".")
        )
        taken = list(board.ideas.values_list("title", flat=True)[:50])
        if taken:
            parts.append("Already on the board, so do not repeat these:\n" + "\n".join(f"- {t}" for t in taken))
    for source in sources:
        parts.append(f"From the research — {source.title or source.url}:\n{(source.summary or source.text)[:800]}")
    message, reply, run = ai.post_message(conversation, user=user, text="\n\n".join(parts), assistant=assistant)
    return conversation, message, reply, run


@transaction.atomic
def keep(message: Message, *, user, picks=None, board=None) -> list[Idea]:
    """The ideas a person keeps from a brainstorm's reply (all of them when `picks` is None), skipping titles the
    board — or the inbox — already has."""
    if message.role != Message.ASSISTANT or message.status != Message.COMPLETED:
        raise Conflict("keep ideas from a brainstorm's finished reply")
    found = (message.result or {}).get("ideas") if isinstance(message.result, dict) else None
    if not isinstance(found, list):
        raise Invalid("that reply holds no list of ideas")
    picks = range(len(found)) if picks is None else picks
    if any(not 0 <= i < len(found) for i in picks):
        raise Invalid(f"pick ideas 0 to {len(found) - 1}")
    mine = Idea.objects.visible_to(user).filter(board=board)
    seen = {title.lower() for title in mine.values_list("title", flat=True)}
    kept = []
    for i in dict.fromkeys(picks):
        item = found[i] if isinstance(found[i], dict) else {}
        title = str(item.get("title") or "").strip()[:255]
        if not title or title.lower() in seen:
            continue
        idea = Idea.objects.create(
            owner=user,
            board=board,
            title=title,
            notes=str(item.get("notes") or ""),
            origin=Idea.BRAINSTORMED,
            source_message=message,
            **placement(user, board),
        )
        if item.get("kind"):
            idea.tags.add(str(item["kind"])[:100])
        seen.add(title.lower())
        kept.append(idea)
    return kept


# ── clustering and de-duplication ──────────────────────────────────────────


def embed(idea: Idea) -> bool:
    """Store the idea's vector; True when it was computed (its text changed)."""
    text = f"{idea.title}\n{idea.notes}"
    _, computed = embed_object(idea, text, stable_hash([idea.title, idea.notes]), "idea")
    return computed


def clusters(ideas, *, threshold: float | None = None, duplicate: float | None = None) -> dict:
    """Groups of ideas that mean much the same (single-link at `threshold`), the pairs similar enough to be one
    idea (at `duplicate`), and the ideas not embedded yet — all from the stored vectors."""
    threshold = settings.IDEAS_CLUSTER_THRESHOLD if threshold is None else threshold
    duplicate = settings.IDEAS_DUPLICATE_THRESHOLD if duplicate is None else duplicate
    ideas = list(ideas[:CLUSTER_LIMIT])
    by_pk = {idea.pk: idea for idea in ideas}
    pairs, embedded = alike(list(by_pk), min(threshold, duplicate))
    parent = {pk: pk for pk in embedded}

    def root(pk):
        while parent[pk] != pk:
            parent[pk] = parent[parent[pk]]
            pk = parent[pk]
        return pk

    for a, b, similarity in pairs:
        if similarity >= threshold:
            parent[root(a)] = root(b)
    groups = defaultdict(list)
    for idea in ideas:
        if idea.pk in embedded:
            groups[root(idea.pk)].append(idea)
    close = ((by_pk[a], by_pk[b], round(similarity, 4)) for a, b, similarity in pairs if similarity >= duplicate)
    return {
        "clusters": [group for group in groups.values() if len(group) > 1],
        "duplicates": sorted(close, key=lambda pair: -pair[2]),
        "pending": [idea for idea in ideas if idea.pk not in embedded],
    }


ALIKE_SQL = """
    SELECT a.object_id, b.object_id, 1 - (a.vector <=> b.vector)
    FROM {table} a JOIN {table} b
      ON b.content_type_id = a.content_type_id AND b.model = a.model AND b.object_id > a.object_id
    WHERE a.content_type_id = %s AND a.model = %s
      AND a.object_id = ANY(%s::bigint[]) AND b.object_id = ANY(%s::bigint[])
      AND 1 - (a.vector <=> b.vector) >= %s
    ORDER BY 1, 2
"""


def alike(ids: list[int], floor: float) -> tuple[list[tuple[int, int, float]], set[int]]:
    """(id, id, cosine similarity) of every pair of these ideas whose stored vectors are at least `floor` alike, and
    the ids that have a vector. On Postgres pgvector compares them in the database; elsewhere (SQLite, tests) each
    vector is made a unit vector once and every pair is one `math.sumprod`."""
    stored = Embedding.objects.filter(
        content_type=ContentType.objects.get_for_model(Idea), model=get_embedder().model, object_id__in=ids
    )
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                ALIKE_SQL.format(table=Embedding._meta.db_table),
                [ContentType.objects.get_for_model(Idea).pk, get_embedder().model, ids, ids, floor],
            )
            pairs = [(a, b, float(similarity)) for a, b, similarity in cursor.fetchall()]
        return pairs, set(stored.values_list("object_id", flat=True))
    units = {pk: unit(vector) for pk, vector in stored.values_list("object_id", "vector")}
    pairs = ((a, b, math.sumprod(units[a], units[b])) for a, b in combinations(sorted(units), 2))
    return [pair for pair in pairs if pair[2] >= floor], set(units)


def unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(math.sumprod(vector, vector))
    return [x / norm for x in vector] if norm else vector


@transaction.atomic
def merge(keep_: Idea, other: Idea, *, user) -> Idea:
    """Fold `other` into `keep_`: its notes, tags, sources and votes come along, then it goes."""
    if keep_.pk == other.pk:
        raise Invalid("an idea cannot be merged into itself")
    for row in (keep_, other):
        _changing(row, user)
    if other.notes.strip():
        keep_.notes = f"{keep_.notes.rstrip()}\n\nMerged from “{other.title}”:\n\n{other.notes.strip()}".strip()
    keep_.tags.add(*other.tags.names())
    keep_.sources.add(*other.sources.all())
    other.votes.exclude(user__in=keep_.votes.values("user")).update(idea=keep_)
    keep_.brief = keep_.brief or other.brief
    keep_.page = keep_.page or other.page
    keep_.save()
    other.delete()
    return keep_


# ── promotion ──────────────────────────────────────────────────────────────


def brief_prompt(idea: Idea) -> str:
    tags = ", ".join(sorted(idea.tags.names()))
    parts = [
        f"Write a piece from this idea.\n\nIdea: {idea.title}",
        idea.notes.strip(),
        f"Tags: {tags}" if tags else "",
    ]
    return "\n\n".join(p for p in parts if p)


@transaction.atomic
def promote(idea: Idea, *, user, to: str, parent=None, assistant=None, generate: bool = False):
    """An idea becomes a brief (with its sources cited; written now when asked), an article draft or a book draft.
    Returns (idea, brief or None, page or None, run or None). Nothing is published."""
    _changing(idea, user)
    brief = page = run = None
    sources = list(Source.objects.visible_to(user).filter(ideas=idea))  # cited by the person who promotes it
    if to == "brief":
        brief = Brief.objects.create(
            owner=user,
            site=placement(user, idea)["site"],
            title=idea.title[:255],
            prompt=brief_prompt(idea),
            assistant=assistant or bundled(WRITER, user),
            parent=parent,
        )
        for source in sources:
            Citation.objects.get_or_create(
                source=source, brief=brief, page=None, quote=None, defaults={"created_by": user}
            )
        idea.brief = brief
        if generate:
            run = ai.generate_brief(brief, user=user)
    elif to in ("article", "book"):
        if parent is None:
            raise Invalid("choose where the draft goes: a parent page")
        body = [{"type": "markdown", "value": idea.notes.strip()}] if idea.notes.strip() else None
        with service_errors():
            page = cms.create_draft(
                parent, ArticlePage if to == "article" else BookPage, user, fields={"title": idea.title}, body=body
            )
        for source in sources:
            Citation.objects.get_or_create(
                source=source, page=page, brief=None, quote=None, defaults={"created_by": user}
            )
        idea.page = page
    else:
        raise Invalid("promote an idea to a brief, an article or a book")
    idea.status = Idea.PROMOTED
    idea.save()
    return idea, brief, page, run
