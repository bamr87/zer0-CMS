"""Rules-based review agents: brand and accessibility.

`brand` runs the brand guard (suggestions/guard.py, the extension's rules,
with the active brand rules and the page's site's own; not the built-in bans on
a chapter whose book or site switched them off) over every text in the page's
latest revision and fails the page on any error-level finding. `a11y` fails on an image block with no alternative text
(neither the block's `alt` nor the image's `ai_alt`), a Markdown image with an
empty `![]()`, and a heading that skips a level. Both end, like any review,
by calling `review.submit_verdict`.
"""

import re

from suggestions.guard import builtin_bans, extra_patterns, page_findings, site_of, text_of

from ..registry import registry

MD_IMAGE_NO_ALT = re.compile(r"!\[\s*\]\(")
MD_HEADING = re.compile(r"^(#{1,6})\s", re.M)


def _page(run):
    return run.target.get_latest_revision_as_object()


def brand(run, ctx):
    page = _page(run)
    extra = extra_patterns(site_of(run.target))  # the active brand rules and the page's site's own
    builtin = builtin_bans(run.target)
    comments = []
    for field in ("title", "seo_title", "search_description", "ai_summary"):
        for f in page_findings(getattr(page, field, "") or "", extra, builtin=builtin):
            if f["level"] == "error":
                comments.append({"text": f"{field}: {f['message']}"})
    for block in page.body:
        raw = block.block.get_prep_value(block.value)
        for f in page_findings(text_of(raw), extra, builtin=builtin):
            if f["level"] == "error":
                comments.append({"block_id": block.id, "text": f["message"]})
    passed = not comments
    summary = "brand guard: clean" if passed else f"brand guard: {len(comments)} banned phrase(s)"
    registry.call("review.submit_verdict", {"passed": passed, "summary": summary, "comments": comments}, ctx)
    return {"findings": len(comments)}


def a11y(run, ctx):
    page = _page(run)
    comments = []
    last_level = 1
    for block in page.body:
        if block.block_type == "image":
            image = block.value.get("image")
            if not (block.value.get("alt") or getattr(image, "ai_alt", "")):
                comments.append({"block_id": block.id, "text": "image has no alternative text"})
        elif block.block_type == "heading":
            level = int(block.value.get("level", 2))
            if level > last_level + 1:
                comments.append({"block_id": block.id, "text": f"heading jumps from H{last_level} to H{level}"})
            last_level = level
        elif block.block_type == "markdown":
            if MD_IMAGE_NO_ALT.search(block.value):
                comments.append({"block_id": block.id, "text": "Markdown image with empty alt text"})
            for hashes in MD_HEADING.findall(block.value):
                level = len(hashes)
                if level > last_level + 1:
                    comments.append({"block_id": block.id, "text": f"heading jumps from H{last_level} to H{level}"})
                last_level = level
    passed = not comments
    summary = "accessibility: clean" if passed else f"accessibility: {len(comments)} problem(s)"
    registry.call("review.submit_verdict", {"passed": passed, "summary": summary, "comments": comments}, ctx)
    return {"findings": len(comments)}
