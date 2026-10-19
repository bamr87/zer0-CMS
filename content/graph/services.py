"""Building the graph and reading it.

`index_page(page)` runs on every publish (cms/signals.py), inside the publish
transaction. It re-embeds the page if its `content_hash` changed and rebuilds
the page's structural edges from what Wagtail already knows: the tree
(`child_of`), the `ReferenceIndex` (`references` — chooser blocks and
foreign keys), internal links in Markdown and Obsidian wikilinks
(`links_to`), tags and categories (`tagged`, `in_category`, as topic
entities) and translations (`translation_of`). Structural edges are derived,
so they are deleted and rewritten; agent, editor and Rails edges are never
touched here.

Reading: `related` (vector neighbours plus one hop of edges), `semantic_search`,
`neighbors` (≤ 2 hops), `path`, and `graph_rag` — search, expand one or two
hops, rerank by similarity to the query (note §5).

Nodes are addressed as `"<kind>:<id>"`: `page:12`, `entity:7`, `image:3`.
"""

import re
from collections import deque
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.models.expressions import RawSQL
from wagtail.models import Page

from .embeddings import cosine, get_embedder
from .models import AGENT_RELS, Edge, Embedding, Entity

NODE = re.compile(r"^(page|entity|image):(\d+)$")
MD_LINK = re.compile(r"\]\((/[^)\s#?]*)[^)]*\)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


class GraphError(ValueError):
    pass


# ── nodes ──────────────────────────────────────────────────────────────────


def node_of(obj) -> str:
    if isinstance(obj, Page):
        return f"page:{obj.pk}"
    if isinstance(obj, Entity):
        return f"entity:{obj.pk}"
    return f"image:{obj.pk}"


def resolve_node(node: str):
    match = NODE.match(node or "")
    if not match:
        raise GraphError(f"a node is page:<id>, entity:<id> or image:<id>; not {node!r}")
    kind, pk = match.group(1), int(match.group(2))
    if kind == "page":
        obj = Page.objects.filter(pk=pk).first()
        obj = obj.specific if obj else None
    elif kind == "entity":
        obj = Entity.objects.filter(pk=pk).first()
    else:
        from wagtail.images import get_image_model

        obj = get_image_model().objects.filter(pk=pk).first()
    if obj is None:
        raise GraphError(f"no {node}")
    return obj


def _ct(obj) -> ContentType:
    # Pages are addressed by their base table, so an edge to page 12 is the
    # same edge whatever page type 12 is.
    return ContentType.objects.get_for_model(Page if isinstance(obj, Page) else obj)


def _node_for(ct_id: int, pk: int) -> str:
    ct = ContentType.objects.get_for_id(ct_id)
    model = ct.model_class()
    if model is not None and issubclass(model, Page):
        return f"page:{pk}"
    return f"entity:{pk}" if model is Entity else f"image:{pk}"


# ── embeddings ─────────────────────────────────────────────────────────────


def page_text(page) -> str:
    parts = [page.title, page.seo_title, page.search_description, getattr(page, "ai_summary", "")]
    for block in getattr(page, "body", []) or []:
        value = block.value
        if hasattr(value, "source"):  # RichText
            parts.append(re.sub(r"<[^>]+>", " ", value.source))
        elif isinstance(value, str):
            parts.append(value)
        elif hasattr(value, "items"):
            parts.extend(str(v) for _, v in value.items() if isinstance(v, str))
    return "\n".join(p for p in parts if p)


def embed_object(obj, text: str, content_hash: str, kind: str) -> tuple[Embedding, bool]:
    """Upsert `obj`'s vector; returns (row, recomputed)."""
    embedder = get_embedder()
    ct = _ct(obj)
    row = Embedding.objects.filter(content_type=ct, object_id=obj.pk, model=embedder.model).first()
    if row is not None and row.content_hash == content_hash:
        return row, False
    vector = embedder.embed(text)
    if row is None:
        row = Embedding(content_type=ct, object_id=obj.pk, model=embedder.model, kind=kind)
    row.dimensions = len(vector)
    row.content_hash = content_hash
    row.vector = vector
    row.save()
    return row, True


def knn(vector: list[float], *, kind: str = "page", k: int = 10, exclude=(), only_ids=None) -> list[tuple[int, float]]:
    """(object id, cosine similarity) of the k nearest stored vectors."""
    model = get_embedder().model
    qs = Embedding.objects.filter(kind=kind, model=model).exclude(object_id__in=list(exclude))
    if only_ids is not None:
        qs = qs.filter(object_id__in=list(only_ids))
    if connection.vendor == "postgresql":
        literal = "[" + ",".join(repr(float(x)) for x in vector) + "]"
        rows = qs.annotate(distance=RawSQL("vector <=> %s::vector", [literal])).order_by("distance")[:k]
        return [(r.object_id, 1.0 - float(r.distance)) for r in rows]
    scored = [(r.object_id, cosine(vector, r.vector)) for r in qs]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored[:k]


# ── structural edges ───────────────────────────────────────────────────────


def _edge(src, rel, dst, *, source, weight=1.0, confidence=1.0, run=None):
    obj, _ = Edge.objects.update_or_create(
        src_ct=_ct(src),
        src_id=src.pk,
        rel=rel,
        dst_ct=_ct(dst),
        dst_id=dst.pk,
        defaults={"weight": weight, "confidence": confidence, "source": source, "run": run, "valid_to": None},
    )
    return obj


def _topic(slug: str, name: str) -> Entity:
    entity, _ = Entity.objects.get_or_create(slug=slug[:200], defaults={"name": name[:200], "kind": "topic"})
    return entity


def site_root_of(page):
    from cms.models import SiteRootPage

    return SiteRootPage.objects.ancestor_of(page, inclusive=True).first()


def resolve_internal_link(page, href: str):
    """A Markdown link or wikilink target → a page in the same site, or None.
    Matches the Jekyll permalink in front matter, the page's URL under its site
    root, and the source path for wikilinks."""
    from cms.models import BasePage

    root = site_root_of(page)
    if root is None:
        return None
    candidates = Page.objects.descendant_of(root).specific()
    target = href.strip()
    if target.startswith("/"):
        wanted = "/" + target.strip("/") + "/"
        prefix = root.url_path.rstrip("/")
        for p in candidates:
            if not isinstance(p, BasePage):
                continue
            permalink = str((p.front_matter or {}).get("permalink", "")).strip()
            if permalink and "/" + permalink.strip("/") + "/" == wanted:
                return p
            if p.url_path.removeprefix(prefix) == wanted:
                return p
        return None
    stem = target.removesuffix(".md").strip("/")
    for p in candidates:
        legacy = getattr(p, "legacy_path", "")
        if legacy and (legacy.removesuffix(".md") == stem or legacy.removesuffix(".md").endswith("/" + stem)):
            return p
    return None


def internal_links(page) -> list[str]:
    hrefs = []
    for block in getattr(page, "body", []) or []:
        if block.block_type == "markdown":
            hrefs += MD_LINK.findall(block.value) + WIKILINK.findall(block.value)
    return hrefs


def index_page(page) -> dict:
    """Re-embed (if changed) and rebuild this page's structural edges."""
    from wagtail.models import ReferenceIndex

    _, recomputed = embed_object(page, page_text(page), page.compute_content_hash(), "page")
    Edge.objects.filter(src_ct=_ct(page), src_id=page.pk, source="structural").delete()
    count = 0
    parent = page.get_parent()
    if parent is not None and parent.depth > 1:
        _edge(page, "child_of", parent, source="structural")
        count += 1
    ReferenceIndex.create_or_update_for_object(page)
    for ref in ReferenceIndex.get_references_for_object(page):
        model = ref.to_content_type.model_class()
        if model is None:
            continue
        target = model.objects.filter(pk=ref.to_object_id).first()
        if target is not None and target.pk != page.pk:
            _edge(page, "references", target, source="structural")
            count += 1
    for href in internal_links(page):
        target = resolve_internal_link(page, href)
        if target is not None and target.pk != page.pk:
            _edge(page, "links_to", target, source="structural")
            count += 1
    tags = page.tags.all() if hasattr(page, "tags") else []
    for tag in tags:
        _edge(page, "tagged", _topic(f"tag-{tag.slug}", tag.name), source="structural")
        count += 1
    categories = page.categories.all() if hasattr(page, "categories") else []
    for category in categories:
        _edge(page, "in_category", _topic(f"category-{category.slug}", category.name), source="structural")
        count += 1
    for translation in page.get_translations():
        _edge(page, "translation_of", translation, source="structural")
        count += 1
    return {"embedded": recomputed, "edges": count}


# ── agent edges ────────────────────────────────────────────────────────────


def clean_edge(src, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise GraphError("an edge is {rel, dst, confidence}")
    rel = payload.get("rel")
    if rel not in AGENT_RELS:
        raise GraphError(f"an agent may propose {', '.join(AGENT_RELS)}; not {rel!r}")
    dst = resolve_node(payload.get("dst", ""))
    if dst.pk == src.pk and type(dst) is type(src):
        raise GraphError("an edge needs two different nodes")
    confidence = payload.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise GraphError("confidence is a number from 0 to 1")
    return {"rel": rel, "dst": node_of(dst), "confidence": float(confidence)}


def upsert_edge(src, payload: dict, *, source: str, run=None) -> Edge:
    clean = clean_edge(src, payload)
    return _edge(src, clean["rel"], resolve_node(clean["dst"]), source=source, confidence=clean["confidence"], run=run)


# ── reading ────────────────────────────────────────────────────────────────


@dataclass
class Hit:
    page: object
    score: float
    reasons: list = field(default_factory=list)


def live_page_ids():
    return set(Page.objects.live().values_list("pk", flat=True))


def semantic_search(query: str, first: int = 10, page_type: str | None = None) -> list[Hit]:
    vector = get_embedder().embed(query)
    ids = live_page_ids()
    hits = []
    for pk, score in knn(vector, k=first * 3, only_ids=ids):
        page = Page.objects.filter(pk=pk).first()
        if page is None:
            continue
        page = page.specific
        if page_type and page._meta.label != page_type:
            continue
        hits.append(Hit(page=page, score=round(score, 6), reasons=["similar"]))
        if len(hits) >= first:
            break
    return hits


STRUCTURAL_WEIGHT = {"references": 0.6, "links_to": 0.6, "viewed_together": 0.5, "child_of": 0.2, "translation_of": 0.0}


def related(page, first: int = 5, kind: str | None = None) -> list[Hit]:
    """kNN on the page's vector plus one hop of edges (and pages sharing a
    topic), merged: score = 0.6·similarity + 0.4·structure."""
    scores: dict[int, float] = {}
    reasons: dict[int, list] = {}
    live = live_page_ids()
    if kind in (None, "similar"):
        row = Embedding.objects.filter(content_type=_ct(page), object_id=page.pk, model=get_embedder().model).first()
        if row is not None:
            for pk, sim in knn(row.vector, k=first * 3, exclude=[page.pk], only_ids=live):
                scores[pk] = scores.get(pk, 0.0) + 0.6 * max(sim, 0.0)
                reasons.setdefault(pk, []).append("similar")
    if kind in (None, "structural", "behavioral"):
        page_ct = _ct(page)
        out = Edge.objects.filter(src_ct=page_ct, src_id=page.pk, dst_ct=page_ct, valid_to__isnull=True)
        back = Edge.objects.filter(dst_ct=page_ct, dst_id=page.pk, src_ct=page_ct, valid_to__isnull=True)
        for e in list(out) + list(back):
            other = e.dst_id if e.src_id == page.pk else e.src_id
            if other not in live or other == page.pk:
                continue
            if kind == "behavioral" and e.rel != "viewed_together":
                continue
            if kind == "structural" and e.rel == "viewed_together":
                continue
            scores[other] = scores.get(other, 0.0) + 0.4 * STRUCTURAL_WEIGHT.get(e.rel, 0.3) * e.weight
            reasons.setdefault(other, []).append(e.rel)
        if kind != "behavioral":
            topics = Edge.objects.filter(src_ct=page_ct, src_id=page.pk, rel__in=["tagged", "in_category"]).values_list(
                "dst_ct", "dst_id"
            )
            for dst_ct, dst_id in topics:
                for e in Edge.objects.filter(dst_ct=dst_ct, dst_id=dst_id, src_ct=page_ct).exclude(src_id=page.pk):
                    if e.src_id in live:
                        scores[e.src_id] = scores.get(e.src_id, 0.0) + 0.4 * 0.4
                        reasons.setdefault(e.src_id, []).append("shared_topic")
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:first]
    pages = {p.pk: p for p in Page.objects.filter(pk__in=[pk for pk, _ in ranked]).specific()}
    return [
        Hit(page=pages[pk], score=round(score, 6), reasons=sorted(set(reasons[pk])))
        for pk, score in ranked
        if pk in pages
    ]


def _adjacent(node: str, rel: str | None = None):
    obj = resolve_node(node)
    ct = _ct(obj)
    out = Edge.objects.filter(src_ct=ct, src_id=obj.pk, valid_to__isnull=True)
    back = Edge.objects.filter(dst_ct=ct, dst_id=obj.pk, valid_to__isnull=True)
    if rel:
        out, back = out.filter(rel=rel), back.filter(rel=rel)
    for e in out:
        yield e, _node_for(e.dst_ct_id, e.dst_id), "out"
    for e in back:
        yield e, _node_for(e.src_ct_id, e.src_id), "in"


def neighbors(node: str, rel: str | None = None, depth: int = 1) -> list[dict]:
    if not 1 <= depth <= 2:
        raise GraphError("depth is 1 or 2")
    seen = {node}
    frontier = [node]
    found = []
    for level in range(1, depth + 1):
        nxt = []
        for current in frontier:
            for edge, other, direction in _adjacent(current, rel):
                if other in seen:
                    continue
                seen.add(other)
                nxt.append(other)
                found.append(
                    {
                        "node": other,
                        "rel": edge.rel,
                        "direction": direction,
                        "via": current,
                        "depth": level,
                        "weight": edge.weight,
                        "confidence": edge.confidence,
                        "source": edge.source,
                    }
                )
        frontier = nxt
    return found


def path(a: str, b: str, max_depth: int = 4) -> list[str] | None:
    resolve_node(a)
    resolve_node(b)
    queue = deque([[a]])
    seen = {a}
    while queue:
        trail = queue.popleft()
        if trail[-1] == b:
            return trail
        if len(trail) > max_depth:
            continue
        for _, other, _ in _adjacent(trail[-1]):
            if other not in seen:
                seen.add(other)
                queue.append(trail + [other])
    return None


def graph_rag(query: str, first: int = 5, hops: int = 1) -> list[Hit]:
    """Semantic search, expand `hops` (1–2) along edges to pages, rerank every
    candidate by similarity to the query."""
    seeds = semantic_search(query, first=first)
    vector = get_embedder().embed(query)
    candidates = {h.page.pk: ["search"] for h in seeds}
    for h in seeds:
        for n in neighbors(f"page:{h.page.pk}", depth=max(1, min(hops, 2))):
            if n["node"].startswith("page:"):
                candidates.setdefault(int(n["node"].split(":")[1]), []).append(f"via:{n['rel']}")
    live = live_page_ids()
    ids = [pk for pk in candidates if pk in live]
    sims = dict(knn(vector, k=len(ids) or 1, only_ids=ids)) if ids else {}
    ranked = sorted(ids, key=lambda pk: (-sims.get(pk, 0.0), pk))[:first]
    pages = {p.pk: p for p in Page.objects.filter(pk__in=ranked).specific()}
    return [
        Hit(page=pages[pk], score=round(sims.get(pk, 0.0), 6), reasons=sorted(set(candidates[pk]))) for pk in ranked
    ]


def threshold() -> float:
    return settings.GRAPH_EDGE_AUTO_THRESHOLD
