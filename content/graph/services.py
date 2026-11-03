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

A link resolves through its site's `SiteLinks`: what every page of the site
answers to, read once from `values_list` (no page loaded). Outside an import,
`index_page` reads one for the call; an import shares one per site for the
whole run (`one_link_index_per_site`), keeps it current as it writes
(`SiteLinks.update`), and relinks then and there every live page whose links
name what moved — so a link to a page imported later in the run resolves in
that page's transaction, and nothing is indexed again when nothing changed.

Reading: `related` (vector neighbours plus one hop of edges), `semantic_search`,
`neighbors` (≤ 2 hops), `path`, and `graph_rag` — search, expand one or two
hops, rerank by similarity to the query (note §5).

Nodes are addressed as `"<kind>:<id>"`: `page:12`, `entity:7`, `image:3`.
"""

import re
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import cache

from django.apps import apps
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


def vector_of(obj) -> list[float] | None:
    """`obj`'s stored vector under the current embedder, or None."""
    row = Embedding.objects.filter(content_type=_ct(obj), object_id=obj.pk, model=get_embedder().model).first()
    return list(row.vector) if row is not None else None


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


# ── internal links ─────────────────────────────────────────────────────────


@cache
def _page_models() -> tuple:
    """The concrete page types a link can name (every `BasePage`: they carry a
    permalink, a source path and a body)."""
    from cms.models import BasePage

    return tuple(model for model in apps.get_models() if issubclass(model, BasePage))


def _target(href: str) -> tuple:
    """What a link names: a site URL (`/…`, matched with its slashes evened
    out) or, for a wikilink, a source path without `.md`."""
    target = href.strip()
    if target.startswith("/"):
        return ("url", "/" + target.strip("/") + "/")
    return ("stem", target.removesuffix(".md").strip("/"))


class SiteLinks:
    """What a Markdown link or wikilink in one site can name. A link to a URL
    matches a page's Jekyll permalink or its URL under the site root; a
    wikilink matches a page's source path without `.md`, whole or from any
    `/` on. Where two pages answer to one target, the first in tree order
    wins, as when every page of the site was scanned for every link.

    `of(root)` reads it in one query per page type. An import also asks it
    which live pages name what (read on the first change of the run), so that
    `update` can relink the pages that name a target an imported page took or
    gave up."""

    def __init__(self, root):
        self.root = root
        self.prefix = root.url_path.rstrip("/")
        self._owners: dict[tuple, dict[int, str]] = {}  # target → {page id: tree path}
        self._targets: dict[int, frozenset] = {}  # page id → what it answers to
        self._hrefs: dict[int, list] | None = None  # live page id → its links, once read
        self._named_by: dict[tuple, set] = defaultdict(set)  # target → the live pages whose links name it

    @classmethod
    def of(cls, root) -> "SiteLinks":
        links = cls(root)
        for model in _page_models():
            for row in model.objects.descendant_of(root).values_list(
                "pk", "path", "url_path", "legacy_path", "front_matter"
            ):
                links._put(*row)
        return links

    def _first(self, target) -> int | None:
        owners = self._owners.get(target)
        return min(owners, key=owners.__getitem__) if owners else None

    def resolve(self, href: str) -> int | None:
        """The id of the page `href` names, or None."""
        return self._first(_target(href))

    def _put(self, pk, path, url_path, legacy_path, front_matter) -> set:
        """Record what page `pk` answers to now; returns the targets that now resolve to another page."""
        new = set()
        permalink = str((front_matter or {}).get("permalink", "")).strip()
        if permalink:
            new.add(("url", "/" + permalink.strip("/") + "/"))
        new.add(("url", url_path.removeprefix(self.prefix)))
        if legacy_path:
            stem = legacy_path.removesuffix(".md")
            new.add(("stem", stem))
            new.update(("stem", stem[i + 1 :]) for i, char in enumerate(stem) if char == "/")
        old = self._targets.get(pk, frozenset())
        before = {target: self._first(target) for target in old | new}
        for target in old:
            owners = self._owners[target]
            owners.pop(pk, None)
            if not owners:
                del self._owners[target]
        for target in new:
            self._owners.setdefault(target, {})[pk] = path
        self._targets[pk] = frozenset(new)
        return {target for target, was in before.items() if self._first(target) != was}

    def _read_links(self, models_pks) -> None:
        """(Re)read the links of the live pages among `models_pks` ({model: ids}, or None for the whole site)."""
        if self._hrefs is None:
            self._hrefs = {}
        for model in _page_models():
            if models_pks is None:
                rows = model.objects.descendant_of(self.root).live().values_list("pk", "live", "body")
            elif models_pks.get(model):
                rows = model.objects.filter(pk__in=models_pks[model]).values_list("pk", "live", "body")
                for pk in models_pks[model]:
                    self._forget_links(pk)
            else:
                continue
            for pk, live, body in rows:
                hrefs = links_in(body) if live else []
                if hrefs:
                    self._hrefs[pk] = hrefs
                    for href in hrefs:
                        self._named_by[_target(href)].add(pk)

    def _forget_links(self, pk) -> None:
        for href in self._hrefs.pop(pk, ()):
            self._named_by[_target(href)].discard(pk)

    def update(self, pages) -> int:
        """`pages` were just written (an import's document, and a collection
        made for it): read what they answer to and link to again, and relink
        every live page whose links name a target that now resolves to another
        page. Returns how many pages were relinked."""
        by_model = defaultdict(list)
        for page in pages:
            by_model[page.specific_class].append(page.pk)
        moved = set()
        for model, pks in by_model.items():
            for row in model.objects.filter(pk__in=pks).values_list(
                "pk", "path", "url_path", "legacy_path", "front_matter"
            ):
                moved |= self._put(*row)
        if self._hrefs is None:
            if not moved:
                return 0
            self._read_links(None)
        else:
            self._read_links(by_model)
        linkers = sorted({pk for target in moved for pk in self._named_by.get(target, ())})
        for pk in linkers:
            self.relink(pk)
        return len(linkers)

    def relink(self, pk) -> None:
        """Bring one live page's `links_to` edges to what its links resolve to
        now: the edges that no longer resolve go, the new ones come."""
        ct = ContentType.objects.get_for_model(Page)
        hrefs = (self._hrefs or {}).get(pk, ())
        want = {target for href in hrefs if (target := self.resolve(href)) not in (None, pk)}
        edges = Edge.objects.filter(src_ct=ct, src_id=pk, rel="links_to", source="structural", dst_ct=ct)
        have = set(edges.values_list("dst_id", flat=True))
        if have - want:
            edges.filter(dst_id__in=have - want).delete()
        for dst in sorted(want - have):
            _link(ct, pk, dst)


_RUN: ContextVar[dict | None] = ContextVar("graph_site_links", default=None)


@contextmanager
def one_link_index_per_site():
    """Within this block every `index_page` of a site shares one `SiteLinks`
    (an import's), which the block's writer keeps current with `update`."""
    token = _RUN.set({})
    try:
        yield
    finally:
        _RUN.reset(token)


def site_links(root, *, fresh: bool = False) -> SiteLinks:
    """The links of the site under `root`: the run's (read once, or again with
    `fresh` — after a document that failed), else read for this call."""
    memo = _RUN.get()
    if memo is None:
        return SiteLinks.of(root)
    if fresh or root.pk not in memo:
        memo[root.pk] = SiteLinks.of(root)
    return memo[root.pk]


def links_in(body) -> list[str]:
    hrefs = []
    for block in body or []:
        if block.block_type == "markdown":
            hrefs += MD_LINK.findall(block.value) + WIKILINK.findall(block.value)
    return hrefs


def internal_links(page) -> list[str]:
    return links_in(getattr(page, "body", None))


def _link(ct, src_id: int, dst_id: int) -> None:
    Edge.objects.update_or_create(
        src_ct=ct,
        src_id=src_id,
        rel="links_to",
        dst_ct=ct,
        dst_id=dst_id,
        defaults={"weight": 1.0, "confidence": 1.0, "source": "structural", "run": None, "valid_to": None},
    )


def index_page(page, links: SiteLinks | None = None) -> dict:
    """Re-embed (if changed) and rebuild this page's structural edges; its
    links resolve through `links`, else its site's (`site_links`)."""
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
    hrefs = internal_links(page)
    if hrefs and links is None:
        root = site_root_of(page)
        links = site_links(root) if root is not None else None
    for href in hrefs if links is not None else ():
        target = links.resolve(href)
        if target is not None and target != page.pk:
            _link(_ct(page), page.pk, target)
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
