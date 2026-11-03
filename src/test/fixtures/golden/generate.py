#!/usr/bin/env python3
"""Generate the golden cross-lane fixtures. Never hand-edit one of these files.

A golden here is a file written by *Python* that the TypeScript core has to
reproduce byte for byte. That is the whole point: the tests prove lane
compatibility rather than self-consistency, so a golden that a TypeScript
change "fixed" is a golden that no longer proves anything.

Three groups, with different requirements:

  1. **Ledger bytes** — `ledger.json`. Pure stdlib: `json.dumps` with
     `indent=2`, `sort_keys=True`, `ensure_ascii=True` plus a trailing newline,
     which is exactly what `pyJsonDump(value, {indent: 2, sortKeys: true})` in
     `core/shared/jsonio.ts` must emit. The non-ASCII URL is not decoration: it
     pins `ensure_ascii` escaping (`café` → `caf\\u00e9`) and code-point key
     ordering at the same time. Always regenerated.

  2. **Catering worklist** — `worklist.md` and its `worklist-inputs.json`.
     Written by the real `catering.build` / `catering.render` from the
     bashconsultants checkout, and inherited verbatim from BASH-CMS (our
     renderer already reproduces them). Regenerated only when a checkout is
     supplied, because reproducing them from anything else would defeat them.

  3. **Content model** — `content-model/cases.json`. Each case is a site's
     `zer0.json` and some files (a path and its front matter), with what the
     platform's reading of the Front Matter content model,
     `content/sites/content_model.py`, answers: every content type's fields
     after its field groups are inlined, the type each file resolves to, and
     the required fields it leaves empty. `golden.test.ts` holds the
     extension's `getContentTypes`, `resolveContentType` and `validateFields`
     to those answers, and `content/tests/sites/test_content_model.py` holds
     the Python to them. The first site is a trimmed copy of lifehacker.dev's
     `zer0.json`; the others exercise every rule it does not (the ten `when`
     operators, a hidden parent, a group that contains itself, a wildcard
     folder, the type key an overlay brings). Standard library only.
     Always regenerated.

Usage, from this directory:

    python3 generate.py                          # ledger.json and content-model/
    python3 generate.py /path/to/bashconsultants # + the worklist pair
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def write_ledger() -> None:
    """The ledger byte contract: `pyJsonDump(…, {indent: 2, sortKeys: true})`.

    Keyed by site-*relative* canonical URL (decision D8): `Zer0Config` carries
    no base URL, so a ledger key cannot move the day a domain does. The entry
    shape is `core/governance/ledger.ts`'s `LedgerEntry`.
    """
    ledger = {
        "_meta": {"generated_by": "zer0-cms", "schema": 1},
        "/pages/posts/corp/café-métier/": {
            "posted_at": "2026-07-30T17:29:20Z",
            "source_file": "pages/_posts/corp/2026-07-30-café-métier.md",
            "target": "jekyll",
            "type": "article",
            "urn": "jekyll:pages/_posts/corp/2026-07-30-café-métier.md",
        },
        "/pages/posts/tech/mcp-for-the-back-office/": {
            "posted_at": "2026-07-06T08:00:00Z",
            "source_file": "pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md",
            "target": "jekyll",
            "type": "article",
            "urn": "jekyll:pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md",
        },
    }
    (HERE / "ledger.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def write_worklist(repo: Path) -> int:
    """`catering.render` byte-for-byte, from the real Python lane.

    Eleven records and seven performance rows, chosen to exercise every lane
    boundary at once: health exactly 70 (in), health -1 (in — an unscored page
    is not punished for the engine's absence), a draft and a structural page
    (both out), and a stale page with engagements (Lane D). Insertion order of
    `performance` matters — topic grouping iterates the dict.
    """
    zer0_dir = repo / "prototype" / "zer0-distribute"
    if not zer0_dir.is_dir():
        print(f"error: {repo} does not look like a bashconsultants checkout")
        return 2
    sys.path.insert(0, str(zer0_dir))

    from catering import build as catering_build, render as catering_render
    from contract import Contract, ContentRecord

    def rec(path, collection, title, health, freshness, draft=False, structural=False):
        return ContentRecord(path=path, collection=collection, title=title,
                             health=health, freshness=freshness, draft=draft,
                             structural=structural)

    records = [
        rec("pages/_posts/corp/a.md", "corp", "A", 90, "fresh"),
        rec("pages/_posts/corp/b.md", "corp", "B", 85, "fresh"),
        rec("pages/_posts/corp/g.md", "corp", "G", 70, "aging"),
        rec("pages/_posts/tech/c.md", "tech", "C", 95, "fresh"),
        rec("pages/_posts/tech/c2.md", "tech", "C2", 88, "fresh"),
        rec("pages/_posts/tech/d.md", "tech", "D", -1, "fresh"),
        rec("pages/_posts/muses/e.md", "muses", "E", 80, "stale"),
        rec("pages/_posts/muses/f.md", "muses", "F", 75, "fresh"),
        rec("pages/_posts/solo/x.md", "solo", "X", 77, "fresh"),
        rec("pages/_posts/muses/h.md", "muses", "H", 88, "fresh", draft=True),
        rec("pages/index.md", "", "Home", 93, "fresh", structural=True),
    ]
    contract = Contract(root=Path("."), present=True, records=records)
    performance = {
        "pages/_posts/corp/a.md": {"impressions": 1000, "engagements": 30},
        "pages/_posts/corp/b.md": {"impressions": 1000, "engagements": 25},
        "pages/_posts/tech/c.md": {"impressions": 12000, "engagements": 700},
        "pages/_posts/tech/c2.md": {"impressions": 345, "engagements": 226},
        "pages/_posts/muses/e.md": {"impressions": 2000, "engagements": 15},
        "pages/_posts/muses/f.md": {"impressions": 1000, "engagements": 15},
        "pages/_posts/solo/x.md": {"impressions": 99999, "engagements": 5},
    }
    published = {
        "pages/_posts/corp/a.md", "pages/_posts/corp/b.md",
        "pages/_posts/tech/c.md", "pages/_posts/tech/c2.md",
        "pages/_posts/muses/e.md", "pages/_posts/muses/f.md",
        "pages/_posts/solo/x.md",
    }
    plan = catering_build(contract, performance, published)
    (HERE / "worklist.md").write_text(catering_render(plan, "2026-07-30"), encoding="utf-8")

    (HERE / "worklist-inputs.json").write_text(json.dumps({
        "records": [
            {"path": r.path, "collection": r.collection, "title": r.title,
             "health": r.health, "freshness": r.freshness,
             "draft": r.draft, "structural": r.structural}
            for r in records
        ],
        "performance": performance,
        "published": sorted(published),
        "date": "2026-07-30",
    }, indent=2) + "\n", encoding="utf-8")
    return 0


# ── the content model ───────────────────────────────────────────────────────

ROOT = "/site"

NEWS_CORE = [
    {"name": "title", "type": "string", "single": True, "required": True},
    {"name": "description", "type": "string", "required": True},
    {"name": "date", "type": "datetime", "isPublishDate": True, "default": "{{now}}", "required": True},
    {"name": "excerpt", "type": "string", "required": True},
    {"name": "tags", "type": "tags", "required": True},
    {"name": "preview", "type": "image", "isPreviewImage": True},
]
AUTHOR = {"name": "author", "type": "choice", "required": True, "default": "claude", "choices": ["amr", "claude"]}

# lifehacker.dev's zer0.json, trimmed to two sections, its docs and its pages.
LIFEHACKER = {
    "platform": {"id": "jekyll", "overlay": "zer0-mistakes"},
    "contentFolders": [
        {"title": "Hacks", "path": "[[workspace]]/pages/_posts/hacks", "contentTypes": ["hack"]},
        {"title": "Field Notes", "path": "[[workspace]]/pages/_posts/field-notes", "contentTypes": ["field-note"]},
        {"path": "[[workspace]]/pages/_posts", "contentTypes": ["field-note"], "excludeSubdir": True},
        {"title": "Docs", "path": "[[workspace]]/pages/_docs", "contentTypes": ["doc"]},
        {"title": "Pages", "path": "[[workspace]]/pages", "contentTypes": ["page"], "excludeSubdir": True},
    ],
    "fieldGroups": [{"id": "news-core", "fields": NEWS_CORE}],
    "contentTypes": [
        {
            "name": "hack",
            "fields": [
                {"name": "core", "type": "fieldCollection", "fieldGroup": "news-core"},
                {"name": "categories", "type": "categories", "required": True, "default": ["Hacks"]},
                AUTHOR,
                {"name": "permalink", "type": "string", "single": True},
                {"name": "featured", "type": "boolean"},
            ],
        },
        {
            "name": "field-note",
            "fields": [
                {"name": "core", "type": "fieldCollection", "fieldGroup": "news-core"},
                {"name": "categories", "type": "categories", "required": True, "default": ["Field Notes"]},
                AUTHOR,
                {"name": "series", "type": "string", "single": True},
            ],
        },
        {
            "name": "doc",
            "fields": [
                {"name": "title", "type": "string", "single": True, "required": True},
                {"name": "description", "type": "string", "required": True},
                {"name": "sidebar", "type": "fields", "fields": [{"name": "nav", "type": "string", "default": "tree"}]},
            ],
        },
        {
            "name": "page",
            "fields": [
                {"name": "title", "type": "string", "single": True, "required": True},
                {"name": "layout", "type": "string", "single": True, "default": "default"},
            ],
        },
    ],
    "draftField": {"name": "draft", "type": "boolean"},
    "validation": {"enabled": True},
}
def shown_when(name, ref, operator, value, kind="string"):
    """A required field shown only while `ref` compares true with `value` under `operator`."""
    when = {"fieldRef": ref, "operator": operator, "value": value}
    return {"name": name, "type": kind, "required": True, "when": when}


COMPLETE_HACK = {
    "title": "Alias your way out of it",
    "description": "Three shell aliases that save a morning.",
    "date": "2026-09-01",
    "excerpt": "Type less.",
    "tags": ["shell"],
    "categories": ["Hacks"],
    "author": "claude",
}

RULES = {
    "contentFolders": [
        {"path": "[[workspace]]/content/*/posts", "contentTypes": ["article"]},
        {"path": "[[workspace]]/content", "contentTypes": ["article", "default"]},
        {"path": "pages/_quests", "contentTypes": ["quest"]},
    ],
    "fieldGroups": [
        {"id": "seo", "fields": [{"name": "seoTitle", "type": "string", "required": True}]},
        {
            "id": "loop",
            "fields": [
                {"name": "again", "type": "fieldCollection", "fieldGroup": "loop"},
                {"name": "looped", "type": "string", "required": True},
            ],
        },
    ],
    "contentTypes": [
        {
            "name": "article",
            "fields": [
                {"name": "title", "type": "string", "required": True},
                {"name": "status", "type": "choice", "choices": ["draft", "reviewed"], "default": "draft"},
                {
                    "name": "verdict",
                    "type": "string",
                    "required": True,
                    "when": {"fieldRef": "status", "operator": "eq", "value": "reviewed"},
                },
                {
                    "name": "shout",
                    "type": "string",
                    "required": True,
                    "when": {"fieldRef": "status", "operator": "eq", "value": "REVIEWED", "caseSensitive": False},
                },
                {
                    "name": "followup",
                    "type": "string",
                    "required": True,
                    "when": {"fieldRef": "verdict", "operator": "startsWith", "value": "re"},
                },
                {
                    "name": "sidebar",
                    "type": "fields",
                    "fields": [
                        {"name": "nav", "type": "string", "required": True},
                        {"name": "seo", "type": "fieldCollection", "fieldGroup": "seo"},
                    ],
                },
                {"name": "section", "type": "heading", "title": "More"},
                {"name": "ghost", "type": "fieldCollection", "fieldGroup": "no-such-group"},
                {"name": "nothing", "type": "fieldCollection"},
                {"name": "loop", "type": "fieldCollection", "fieldGroup": "loop"},
            ],
        },
        {
            "name": "quest",
            "fields": [
                {"name": "title", "type": "string"},
                {"name": "level", "type": "number"},
                {"name": "tags", "type": "tags"},
                shown_when("boss", "level", "gte", 10),
                shown_when("mentor", "level", "lt", 3),
                shown_when("rank", "level", "gt", 99),
                shown_when("unlisted", "level", "lte", 1, kind="boolean"),
                shown_when("side", "tags", "contains", "side"),
                shown_when("main", "tags", "notContains", "side"),
                shown_when("epilogue", "title", "endsWith", "end"),
                shown_when("secret", "status", "neq", "open"),
            ],
        },
        {"name": "default", "fields": [{"name": "title", "type": "string", "required": True}]},
    ],
}

SITES = [
    {
        "name": "lifehacker",
        "about": "lifehacker.dev's shape: news-core inlined into each section, a folder each, the overlay's type key",
        "zer0": LIFEHACKER,
        "files": [
            ("pages/_posts/hacks/2026-09-01-alias.md", COMPLETE_HACK),
            (
                "pages/_posts/hacks/2026-09-02-thin.md",
                {**COMPLETE_HACK, "description": "   ", "excerpt": "<failed to process>", "tags": []},
            ),
            ("pages/_posts/field-notes/2026-09-03-note.md", {"title": "A note"}),
            ("pages/_posts/2026-09-04-loose.md", {**COMPLETE_HACK, "categories": ["Field Notes"]}),
            ("pages/_docs/guide.md", {"type": "hack", "title": "A guide that says it is a hack"}),
            ("pages/_docs/landing.md", {"fmContentType": "page", "title": "Named by the overlay's key"}),
            ("pages/_docs/unknown.md", {"fmContentType": "nope", "title": "T", "description": "D"}),
            ("pages/about.md", {"title": "About"}),
            ("notes/elsewhere.md", {}),
        ],
    },
    {
        "name": "rules",
        "about": "every rule lifehacker does not exercise: when, a hidden parent, nested groups, a cycle, a wildcard",
        "zer0": RULES,
        "files": [
            (
                "content/blog/posts/one.md",
                {"title": "One", "status": "reviewed", "verdict": "", "sidebar": {"nav": "n"}},
            ),
            ("content/blog/posts/two.md", {"title": "Two", "status": "draft", "verdict": "recommended"}),
            (
                "content/blog/posts/three.md",
                {"title": "Three", "status": "Reviewed", "verdict": "recommended", "shout": "yes",
                 "sidebar": {"nav": "t", "seoTitle": "s"}, "looped": "l"},
            ),
            (
                "content/blog/posts/four.md",
                {"title": "Four", "status": "reviewed", "verdict": "recommended", "shout": "ok",
                 "sidebar": {"nav": "t", "seoTitle": "s"}, "looped": "l"},
            ),
            ("content/blog/posts/five.md", {"title": "Five"}),
            ("content/blog/posts/six.md", {"type": "nope", "fmContentType": "quest", "title": "Six", "status": "x"}),
            ("content/index.md", {}),
            ("pages/_quests/q1.md", {"title": "The end", "level": 12, "tags": ["side"], "status": "open"}),
            ("pages/_quests/q2.md", {"level": "high", "tags": "side quest", "unlisted": False}),
            ("pages/_quests/q3.md", {"title": "Start", "level": 0, "tags": []}),
        ],
    },
    {
        "name": "no-types",
        "about": "a zer0.json that declares no content type: the built-in one, which requires nothing",
        "zer0": {"contentFolders": [{"path": "[[workspace]]/pages"}]},
        "files": [("pages/index.md", {"title": ""})],
    },
    {
        "name": "one-type",
        "about": "one content type governs every file; validation off reports nothing",
        "zer0": {
            "contentTypes": [{"name": "only", "fields": [{"name": "title", "type": "string", "required": True}]}],
            "validation": {"enabled": False},
        },
        "files": [("anywhere/at/all.md", {})],
    },
]


def field_names(fields: list, parents: tuple = ()) -> list:
    """A type's fields, depth-first, a nested one as `parent.child`."""
    out = []
    for f in fields:
        out.append(".".join((*parents, f["name"])))
        if f["type"] == "fields":
            out += field_names(f.get("fields") or [], (*parents, f["name"]))
    return out


def write_content_model() -> None:
    """What `content/sites/content_model.py` answers for each case: the platform's side of the golden."""
    sys.path.insert(0, str(REPO / "content"))
    from sites import content_model

    sites = []
    for case in SITES:
        site = content_model.model(case["zer0"], ROOT)
        files = []
        for rel, data in case["files"]:
            ctype = content_model.resolve(site, rel, data)
            missing = content_model.missing_fields(site, ctype, data)
            files.append({"path": rel, "data": data, "type": ctype["name"], "missing": missing})
        sites.append(
            {
                "name": case["name"],
                "about": case["about"],
                "zer0": case["zer0"],
                "types": {t["name"]: field_names(t["fields"]) for t in site.types},
                "files": files,
            }
        )
    out = HERE / "content-model" / "cases.json"
    out.parent.mkdir(exist_ok=True)
    golden = {"generated_by": "generate.py from content/sites/content_model.py", "root": ROOT, "sites": sites}
    out.write_text(json.dumps(golden, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) > 2:
        print(__doc__)
        return 2

    write_ledger()
    print("wrote", HERE / "ledger.json")
    write_content_model()
    print("wrote", HERE / "content-model" / "cases.json")

    if len(sys.argv) == 2:
        code = write_worklist(Path(sys.argv[1]).resolve())
        if code != 0:
            return code
        print("wrote", HERE / "worklist.md", "and", HERE / "worklist-inputs.json")
    else:
        print("worklist.md / worklist-inputs.json left alone "
              "(pass a bashconsultants checkout to regenerate them)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
