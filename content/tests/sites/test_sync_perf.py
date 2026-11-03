"""How much a sync costs (W1-5: SITES-01, CONTENT-04, OPS-06, EXT-10), as
query counts and page loads, never wall-clock: a first sync stays within a
bound per document whatever the site's size (one link index per site, not a
scan of the site per link); a second sync of unchanged files runs the same
fixed number of queries at any size (nothing is indexed again); and the graph
a sync leaves is the one the old full pass over every page built, resolved the
way the old resolver resolved each link."""

from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from wagtail.models import Page

from cms.models import BasePage, SiteRootPage
from graph.models import Edge
from graph.services import index_page, internal_links
from importers.jekyll import import_site
from importers.models import ImportedSource

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "jekyll" / "site"

pytestmark = pytest.mark.django_db


def make_site(root: Path, n: int) -> Path:
    """A site of `n` documents and a hub that links to every one of them before
    they exist (it is read first): each document links back, ahead and three on
    by permalink and wikilink, and the first names a page that is not there yet."""
    docs = root / "_docs"
    docs.mkdir(parents=True)
    (root / "_config.yml").write_text("title: Generated\ncollections:\n  docs:\n    output: true\n")
    hub = " ".join(f"[[doc-{i:03}]]" for i in range(n))
    (docs / "000-hub.md").write_text(f"---\ntitle: Hub\npermalink: /docs/hub/\n---\n\n{hub}\n")
    for i in range(n):
        later = " and [later](/docs/new/)" if i == 0 else ""
        two = " and [two](/docs/two/)" if i == 5 else ""
        body = (
            f"See [back](/docs/{(i - 1) % n}/), [ahead](/docs/{(i + 1) % n}/) and [[doc-{(i + 3) % n:03}]]{later}{two}."
        )
        (docs / f"doc-{i:03}.md").write_text(
            f"---\ntitle: Doc {i}\npermalink: /docs/{i}/\ntags: [t{i % 3}]\n---\n\n{body}\n"
        )
    return root


@pytest.fixture
def page_loads(monkeypatch):
    """Every page row the code under test turns into a model instance."""
    loads = []
    original = Page.from_db.__func__

    def counting(cls, db, field_names, values):
        loads.append(cls)
        return original(cls, db, field_names, values)

    monkeypatch.setattr(Page, "from_db", classmethod(counting))
    return loads


def first_sync(tmp_path, n, page_loads):
    site = make_site(tmp_path / f"site-{n}", n)
    page_loads.clear()
    with CaptureQueriesContext(connection) as queries:
        report = import_site(site, f"generated-{n}")
    assert not report.errors and len(report.created) == n + 1, report.errors
    return site, len(queries), len(page_loads)


# ── a first sync ───────────────────────────────────────────────────────────


def test_a_first_sync_stays_within_a_bound_per_document_whatever_the_size(tmp_path, page_loads):
    """Before, every link loaded every page of the site and the second pass
    indexed every page again: 31 documents cost 6,453 queries and 6,313 page
    loads (204 a document, against 95 for 11). Now a page is loaded a fixed
    number of times whatever its site's size; the queries left are Wagtail's
    own for a new page (its revision, search entry, log and references)."""
    _, small_queries, small_loads = first_sync(tmp_path, 10, page_loads)
    _, big_queries, big_loads = first_sync(tmp_path, 30, page_loads)
    assert big_queries <= 31 * 190 and big_loads <= 31 * 16, (big_queries, big_loads)
    # Per document: twenty more documents cost twenty times one document's bound, no more.
    assert big_queries - small_queries <= 20 * 185 and big_loads - small_loads <= 20 * 16, (small_queries, small_loads)


def test_the_fixture_site_imports_within_its_query_budget(django_assert_max_num_queries):
    """Its 8 documents took 1,878 queries before."""
    with django_assert_max_num_queries(8 * 220):
        report = import_site(FIXTURE, "fixture")
    assert not report.errors and len(report.created) == 8


# ── a second sync of unchanged files ───────────────────────────────────────


@pytest.mark.parametrize("n", [10, 30])
def test_a_second_sync_of_unchanged_files_runs_a_fixed_number_of_queries(n, tmp_path, page_loads):
    site, _, _ = first_sync(tmp_path, n, page_loads)
    page_loads.clear()
    with CaptureQueriesContext(connection) as queries:
        again = import_site(site, f"generated-{n}")
    assert again.created == again.updated == [] and len(again.unchanged) == n + 1
    # The site root is the one page it reads: no page of a document is loaded, none is indexed. (Eight statements
    # with the savepoints of the site root's and the collection's own short transactions.)
    assert len(queries) <= 8 and len(page_loads) <= 1, [q["sql"] for q in queries.captured_queries]


# ── the graph it leaves ────────────────────────────────────────────────────


def edges() -> set:
    return set(
        Edge.objects.values_list("src_ct", "src_id", "rel", "dst_ct", "dst_id", "source", "weight", "confidence")
    )


def full_pass(site_key):
    """What the import's second pass did before: index every live page again."""
    for source in ImportedSource.objects.filter(site_key=site_key).select_related("page"):
        page = source.page.specific
        if page.live:
            index_page(page)


def old_resolver(page, href):
    """The resolver every link went through before (graph/services.py at d3817a5f), kept here as the reference."""
    root = SiteRootPage.objects.ancestor_of(page, inclusive=True).first()
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


def assert_links_resolve_as_before(site_key):
    want = set()
    for source in ImportedSource.objects.filter(site_key=site_key).select_related("page"):
        page = source.page.specific
        if not page.live:
            continue
        for href in internal_links(page):
            target = old_resolver(page, href)
            if target is not None and target.pk != page.pk:
                want.add((page.pk, target.pk))
    have = set(Edge.objects.filter(rel="links_to").values_list("src_id", "dst_id"))
    assert have == want and want, (have - want, want - have)


def test_the_graph_is_the_one_a_full_pass_builds(tmp_path):
    """A first sync, then a second that adds a page an unchanged page already
    linked to and moves a permalink two unchanged pages name: the links of the
    pages that name what changed follow, and nothing else is indexed again."""
    site = make_site(tmp_path / "site", 8)
    import_site(site, "graph")
    synced = edges()
    assert_links_resolve_as_before("graph")
    full_pass("graph")
    assert edges() == synced
    (site / "_docs" / "doc-new.md").write_text("---\ntitle: New\npermalink: /docs/new/\n---\n\nBack to [[doc-000]].\n")
    two = site / "_docs" / "doc-002.md"
    two.write_text(two.read_text().replace("permalink: /docs/2/", "permalink: /docs/two/"))
    again = import_site(site, "graph")
    assert again.created == ["_docs/doc-new.md"] and again.updated == ["_docs/doc-002.md"]
    synced = edges()
    assert_links_resolve_as_before("graph")
    full_pass("graph")
    assert edges() == synced


def test_the_fixture_sites_graph_is_the_one_a_full_pass_builds():
    import_site(FIXTURE, "fixture")
    synced = edges()
    assert_links_resolve_as_before("fixture")
    full_pass("fixture")
    assert edges() == synced
