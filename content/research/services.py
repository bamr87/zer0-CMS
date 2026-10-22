"""What the research library does: every command, so its views, tasks and run
handlers stay thin (TARGET.md § Rules that keep models and views manageable).

Nothing here reaches the network or a model inside a request. Capturing a URL
saves the source as `pending` and queues its fetch (`research.tasks`), which
asks robots.txt and goes through the guarded fetcher (research/fetch.py); a
feed is refreshed by Celery beat or on request; summaries, cited answers,
fact-checks and web searches are runs of the AI layer's `assistant` agent
(research/handlers.py), started through `ai.services.start` after the checks
the AI layer makes — the rows are the person's to use, the provider is enabled
and in budget. An upload is read in the request: a PDF, plain text or
Markdown, within `RESEARCH_UPLOAD_MAX_BYTES`. A fact-check's findings become
suggestions on the draft for a person to accept: nothing here changes a page.

Retrieval (`ranked`, `passages`) is by the sources' stored vectors
(`graph.Embedding`, pgvector on Postgres) and then by shared words, so it works
on SQLite and in tests with the deterministic hashing embedder too.
"""

import logging
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.html import strip_tags

from agents.models import AgentRun
from ai import providers
from ai.models import Assistant, ProviderConfig, usable
from ai.services import check_provider, provider_slug, run_assistant, stable_id, start
from cms.models import stable_hash
from graph.embeddings import get_embedder, tokens
from graph.models import Embedding
from graph.services import embed_object, knn
from ops.errors import Forbidden, Invalid, Unavailable

from . import fetch
from .models import Citation, FactCheck, FeedSubscription, Question, Source, placement

log = logging.getLogger(__name__)

SUMMARIZER, ANSWERER, FACT_CHECKER, BRIEF_WRITER = (
    "source-summarizer",
    "research-answerer",
    "fact-checker",
    "research-brief-writer",
)
PASSAGE = 900  # characters in a passage a run reads
TOP = 6  # sources a run reads at most
NEW_ITEMS = 50  # feed items taken in one refresh at most
CHECKED_TYPES = ("markdown", "paragraph", "heading", "quote")


def bundled(key: str, user) -> Assistant:
    """A bundled assistant of this app, if `user` may use it."""
    row = Assistant.objects.filter(public_id=stable_id("bundled-assistant", key)).first()
    if row is None:
        raise Unavailable(f"the bundled assistant {key!r} is missing: run manage.py migrate")
    if not usable(row, user):
        raise Forbidden(f"the {row.name} assistant is not one {user} may use")
    return row


def queue(task, pk) -> None:
    transaction.on_commit(lambda: task.delay(pk))


def visible_sources(user, collection=None):
    rows = Source.objects.visible_to(user)
    return rows.filter(collection=collection) if collection is not None else rows


# ── gathering ──────────────────────────────────────────────────────────────


def capture_url(user, url: str, *, collection=None, title: str = "") -> Source:
    """A web page to fetch: saved now as `pending`, fetched by a worker."""
    from .tasks import fetch_source

    url = url.strip()
    try:
        fetch.refuse_private_literal(url)
    except fetch.Blocked as e:
        raise Invalid(str(e)) from e
    source = Source.objects.create(
        owner=user,
        kind=Source.URL,
        url=url,
        title=title[:500],
        collection=collection,
        status=Source.PENDING,
        **placement(user, collection),
    )
    queue(fetch_source, source.pk)
    return source


def capture_again(source: Source) -> Source:
    """Fetch a web page source again (a page that changed, or a fetch that failed)."""
    from .tasks import fetch_source

    source.status, source.error = Source.PENDING, ""
    source.save(update_fields=["status", "error", "updated_at"])
    queue(fetch_source, source.pk)
    return source


def add_note(user, text: str, *, collection=None, title: str = "") -> Source:
    if not text.strip():
        raise Invalid("a note needs text")
    first = next(line.strip() for line in text.splitlines() if line.strip())
    return Source.objects.create(
        owner=user,
        kind=Source.NOTE,
        title=(title or first)[:500],
        text=text.strip(),
        collection=collection,
        **placement(user, collection),
    )


def upload(user, file, *, collection=None, title: str = "") -> Source:
    """A document — PDF, plain text or Markdown — read now, kept as its text."""
    if file.size > settings.RESEARCH_UPLOAD_MAX_BYTES:
        raise Invalid(f"a document is at most {settings.RESEARCH_UPLOAD_MAX_BYTES} bytes")
    body = file.read()
    try:
        found = fetch.extract(body, file.content_type or "", filename=file.name or "")
    except fetch.FetchError as e:
        raise Invalid(str(e)) from e
    return Source.objects.create(
        owner=user,
        kind=Source.DOCUMENT,
        title=(title or found.title or file.name or "Document")[:500],
        author=found.author[:255],
        text=found.text,
        metadata={**found.metadata, "file_name": file.name, "bytes": len(body), "content_type": file.content_type},
        fetched_at=timezone.now(),
        collection=collection,
        **placement(user, collection),
    )


def fetch_into(source: Source) -> Source:
    """Fetch a URL source (in a worker): robots.txt first, then the page through the guard, extracted. A refusal or a
    failure is recorded on the source, which can be fetched again."""
    Source.objects.filter(pk=source.pk).update(status=Source.FETCHING, error="")
    verdict = fetch.UNKNOWN
    try:
        verdict = fetch.robots(source.url)
        if verdict == fetch.DISALLOWED:
            raise fetch.FetchError("the site's robots.txt asks robots not to fetch this page")
        got = fetch.get(source.url)
        if got.status >= 400:
            raise fetch.FetchError(f"the site answered HTTP {got.status}")
        found = fetch.extract(got.body, got.content_type, url=got.url, charset=got.charset)
    except fetch.FetchError as e:
        source.status, source.error = Source.FAILED, str(e)
    except Exception as e:  # noqa: BLE001 — an unreadable page is recorded on the source, never left fetching
        log.exception("fetching source %s failed", source.pk)
        source.status, source.error = Source.FAILED, f"the page could not be read: {type(e).__name__}"
    else:
        source.text, source.status, source.error = found.text, Source.READY, ""
        source.title = source.title or found.title[:500]
        source.author = source.author or found.author[:255]
        source.site_name, source.published, source.language = (
            found.site_name[:255],
            found.published[:40],
            found.language[:16],
        )
        extra = {"final_url": got.url, "content_type": got.content_type, "bytes": len(got.body)}
        source.metadata = {**source.metadata, **found.metadata, **extra}
        source.fetched_at = timezone.now()
    source.robots = verdict
    source.save()
    return source


def subscribe(user, url: str, *, collection=None, title: str = "", interval_minutes: int = 60) -> FeedSubscription:
    from .tasks import refresh_feed

    try:
        fetch.refuse_private_literal(url.strip())
    except fetch.Blocked as e:
        raise Invalid(str(e)) from e
    feed = FeedSubscription.objects.create(
        owner=user,
        url=url.strip(),
        title=title[:500],
        collection=collection,
        interval_minutes=interval_minutes,
        **placement(user, collection),
    )
    queue(refresh_feed, feed.pk)
    return feed


def refresh(feed: FeedSubscription) -> int:
    """Read a feed (in a worker) and keep its new items as sources; returns how many were new. A feed that has not
    changed (`304`) costs nothing; a failure is recorded on the subscription and tried again on schedule."""
    now, new = timezone.now(), 0
    asked = {"If-None-Match": feed.etag} if feed.etag else {}
    if feed.modified:
        asked["If-Modified-Since"] = feed.modified
    try:
        got = fetch.get(feed.url, headers=asked)
        if got.status >= 400:
            raise fetch.FetchError(f"the feed answered HTTP {got.status}")
        if got.status != 304:
            title, items = fetch.entries(got.body)
            for item in [i for i in items if i["guid"]][:NEW_ITEMS]:
                url = item["url"] if item["url"].startswith(("http://", "https://")) else ""
                _, created = Source.objects.get_or_create(
                    feed=feed,
                    guid=item["guid"],
                    defaults={
                        "owner": feed.owner,
                        "kind": Source.FEED,
                        "url": url[:2000],
                        "title": item["title"],
                        "author": item["author"],
                        "published": item["published"],
                        "text": item["text"],
                        "fetched_at": now,
                        "collection": feed.collection,
                        "site": feed.site,
                        "visibility": feed.visibility,
                    },
                )
                new += created
            feed.title = feed.title or title[:500]
            feed.etag, feed.modified = got.headers.get("etag", "")[:255], got.headers.get("last-modified", "")[:64]
        feed.error = ""
    except fetch.FetchError as e:
        feed.error = str(e)
    feed.last_checked_at, feed.next_check_at = now, now + timedelta(minutes=feed.interval_minutes)
    feed.save()
    return new


def due_feeds():
    now = timezone.now()
    return FeedSubscription.objects.filter(active=True).filter(
        Q(next_check_at__isnull=True) | Q(next_check_at__lte=now)
    )


def searcher(slug: str = "") -> str:
    """A provider that can search the web: the one asked for; else the default, else the first enabled one that can
    and has a credential to do it with."""
    enabled = ProviderConfig.objects.filter(enabled=True).values_list("slug", flat=True)
    for candidate in dict.fromkeys([slug] if slug else [providers.default_slug(), *enabled]):
        try:
            adapter = providers.get(candidate)
        except (ImportError, providers.ProviderError):
            continue  # a slug the registry cannot build cannot search
        ready = candidate == slug or not adapter.credential_env or adapter.credential_source()
        if "search" in adapter.capabilities and ready:
            return check_provider(candidate)
    raise Invalid("no provider here can search the web: configure one that can (anthropic), or capture pages by URL")


def search_web(user, query: str, *, collection=None, max_results: int = 5, provider: str = "") -> AgentRun:
    """A web search through a provider's own search tool, as a run; each result becomes a source to fetch."""
    if not query.strip():
        raise Invalid("a search needs words to search for")
    data = {
        "kind": "research.search",
        "query": query.strip(),
        "collection": str(collection.public_id) if collection else None,
        "provider": searcher(provider),
        "max_results": max_results,
    }
    return start(user, data)


# ── the AI steps ───────────────────────────────────────────────────────────


def summarize(source: Source, *, user) -> AgentRun:
    """A summary, the entities it names and passages worth quoting, as a run; the person reviews what arrives."""
    if not source.can_edit(user):
        raise Forbidden(f"source {source.public_id} is not {user}'s to change")
    if not source.text.strip():
        raise Invalid("the source has no text to summarize yet")
    assistant = bundled(SUMMARIZER, user)
    provider_slug(assistant)
    data = {"kind": "research.summarize", "source": str(source.public_id), "assistant": str(assistant.public_id)}
    run = start(user, data, target=source)
    Source.objects.filter(pk=source.pk).update(summary_run=run)
    source.summary_run = run
    return run


def ask(user, text: str, *, collection=None) -> Question:
    """A question to answer from the sources (a collection's, or all the person sees), with citations."""
    if not text.strip():
        raise Invalid("a question needs words")
    if not visible_sources(user, collection).filter(status=Source.READY).exists():
        raise Invalid("there are no sources to answer from yet")
    assistant = bundled(ANSWERER, user)
    provider_slug(assistant)
    question = Question.objects.create(
        owner=user, collection=collection, text=text.strip(), **placement(user, collection)
    )
    data = {"kind": "research.answer", "question": str(question.public_id), "assistant": str(assistant.public_id)}
    question.run = start(user, data)
    question.save(update_fields=["run"])
    return question


def checked_sources(user, page, collection=None):
    """What a draft is checked against: the sources it cites, and a collection's."""
    which = Q(pk__in=Citation.objects.filter(page=page).values("source"))
    if collection is not None:
        which |= Q(collection=collection)
    return Source.objects.visible_to(user).filter(which, status=Source.READY)


def draft_blocks(page) -> list[dict]:
    """The latest revision's checkable blocks: label, id, type, value and plain text."""
    found = []
    for block in page.get_latest_revision_as_object().body.get_prep_value():
        value = block.get("value")
        if block.get("type") not in CHECKED_TYPES:
            continue
        text = value if isinstance(value, str) else (value or {}).get("text", "")
        text = strip_tags(text).strip() if block["type"] == "paragraph" else str(text).strip()
        if text:
            found.append(
                {"label": f"B{len(found) + 1}", "id": block["id"], "type": block["type"], "value": value, "text": text}
            )
    return found


def fact_check(page, *, user, collection=None) -> FactCheck:
    """Check a draft's claims against its sources, as a run; its findings become suggestions on the draft."""
    page = page.specific
    if not page.permissions_for_user(user).can_edit():
        raise Forbidden(f"{user} may not edit that page")
    if not draft_blocks(page):
        raise Invalid("the draft has no text to check")
    if not checked_sources(user, page, collection).exists():
        raise Invalid("cite sources on the draft, or choose a collection, to check it against")
    assistant = bundled(FACT_CHECKER, user)
    provider_slug(assistant)
    check = FactCheck.objects.create(owner=user, page=page, collection=collection)
    data = {"kind": "research.fact_check", "fact_check": str(check.public_id), "assistant": str(assistant.public_id)}
    check.run = start(user, data, target=page)
    check.save(update_fields=["run"])
    return check


def research_brief(collection, *, user, topic: str) -> AgentRun:
    """A research brief on a topic (intent, keywords, angles, outline, links — AIEO's), from a collection's sources,
    as a run of the bundled writer; the person reads it and may keep it as a note."""
    if not topic.strip():
        raise Invalid("a research brief needs a topic")
    sources = list(visible_sources(user, collection).filter(status=Source.READY)[:TOP])
    words = set(tokens(topic))
    notes = "\n\n".join(f"[{s.title or s.url}] {s.url}\n{' … '.join(passages(s, words, 1))}" for s in sources)
    prompt = f"Topic: {topic.strip()}" + (f"\n\nWhat the research holds so far:\n\n{notes}" if notes else "")
    return run_assistant(bundled(BRIEF_WRITER, user), user=user, prompt=prompt)


# ── citing ─────────────────────────────────────────────────────────────────


def cite(user, source: Source, *, page=None, brief=None, quote=None, note: str = "") -> Citation:
    """A page or a brief cites a source (or one of its quotes): the person may change what cites it."""
    if (page is None) == (brief is None):
        raise Invalid("a source is cited by a page or by a brief")
    if quote is not None and quote.source_id != source.pk:
        raise Invalid("that quote is from another source")
    if page is not None and not page.permissions_for_user(user).can_edit():
        raise Forbidden(f"{user} may not edit that page")
    if brief is not None and not brief.can_edit(user):
        raise Forbidden(f"brief {brief.public_id} is not {user}'s to change")
    citation, _ = Citation.objects.get_or_create(
        source=source, quote=quote, page=page, brief=brief, defaults={"note": note, "created_by": user}
    )
    return citation


def brief_sources(sender, brief, **kwargs) -> str:
    """`ai.handlers.brief_context`: the sources a brief cites — those its owner may see — for its writer to read."""
    if brief.owner_id is None:
        return ""
    cited = Citation.objects.filter(brief=brief).values("source")
    sources = list(Source.objects.visible_to(brief.owner).filter(pk__in=cited)[:TOP])
    if not sources:
        return ""
    parts = [f"- {s.title or s.url}{f' ({s.url})' if s.url else ''}: {(s.summary or s.text)[:1500]}" for s in sources]
    return "Research to draw on — cite it where you use it:\n\n" + "\n\n".join(parts)


# ── retrieval ──────────────────────────────────────────────────────────────


def embed(source: Source) -> bool:
    """Store the source's vector for retrieval; True when it was computed (the text changed)."""
    if source.status != Source.READY or not (source.text or source.summary).strip():
        return False
    text = "\n".join([source.title, source.summary, source.text[:6000]])
    _, computed = embed_object(source, text, stable_hash([source.title, source.summary, source.text]), "source")
    return computed


def forget(sender, instance, **kwargs) -> None:
    """A deleted row's vector goes with it (post_delete)."""
    Embedding.objects.filter(content_type=ContentType.objects.get_for_model(sender), object_id=instance.pk).delete()


def chunks(text: str, size: int = PASSAGE) -> list[str]:
    """Paragraphs packed into passages of at most `size` characters (a longer paragraph is cut)."""
    found, current = [], ""
    for paragraph in (p.strip() for p in re.split(r"\n\s*\n|\n", text or "") if p.strip()):
        while len(paragraph) > size:
            found.append(paragraph[:size])
            paragraph = paragraph[size:]
        if current and len(current) + len(paragraph) + 1 > size:
            found.append(current)
            current = ""
        current = f"{current}\n{paragraph}".strip()
    return [*found, current] if current else found


def overlap(text: str, words: set) -> int:
    return len(words & set(tokens(text)))


def passages(source: Source, words: set, limit: int = 2) -> list[str]:
    """The `limit` passages of a source that share most words with the question, in the source's order."""
    found = chunks(source.text or source.summary)
    best = sorted(range(len(found)), key=lambda i: (-overlap(found[i], words), i))[:limit]
    return [found[i] for i in sorted(best)]


def ranked(rows, query: str, k: int = TOP) -> list[Source]:
    """The `k` sources most like `query`: by stored vector first, then by shared words, and when nothing is alike
    (a question in other words than its sources'), the newest — the answerer says when they do not answer it."""
    ids = list(rows.values_list("pk", flat=True)[:2000])
    if not ids:
        return []
    chosen = [pk for pk, score in knn(get_embedder().embed(query), kind="source", k=k, only_ids=ids) if score > 0]
    if len(chosen) < k:
        words = set(tokens(query))
        rest = rows.exclude(pk__in=chosen).only("pk", "title", "summary", "text")
        scored = sorted(
            ((overlap(f"{s.title}\n{s.summary}\n{s.text}", words), s.pk) for s in rest), key=lambda t: (-t[0], t[1])
        )
        chosen += [pk for score, pk in scored if score > 0][: k - len(chosen)]
    chosen = chosen or list(rows.order_by("-created_at").values_list("pk", flat=True)[:k])
    found = Source.objects.in_bulk(chosen)
    return [found[pk] for pk in chosen if pk in found]


def squashed(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def same_words(quote: str, text: str) -> bool:
    """Whether `quote` is in `text`, whitespace and case aside."""
    return bool(squashed(quote)) and squashed(quote) in squashed(text)
