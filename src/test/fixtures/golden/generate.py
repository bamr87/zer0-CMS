#!/usr/bin/env python3
"""Generate the golden cross-lane fixtures. Never hand-edit one of these files.

A golden here is a file written by *Python* that the TypeScript core has to
reproduce byte for byte. That is the whole point: the tests prove lane
compatibility rather than self-consistency, so a golden that a TypeScript
change "fixed" is a golden that no longer proves anything.

Two groups, with different requirements:

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

Usage, from this directory:

    python3 generate.py                          # ledger.json only
    python3 generate.py /path/to/bashconsultants # + the worklist pair
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


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


def main() -> int:
    if len(sys.argv) > 2:
        print(__doc__)
        return 2

    write_ledger()
    print("wrote", HERE / "ledger.json")

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
