{
    "title": "The JSON dialect",
    "description": "Hugo-style JSON front matter: a bare object at the top of the file, closed by its matching brace — even when a } sits inside a string.",
    "slug": "json-dialect",
    "date": "2026-07-22",
    "draft": false,
    "tags": ["mcp", "jekyll"],
    "categories": ["tech"],
    "weight": 50,
    "featured": false
}

# The JSON dialect

No fence at all. The block ends at the brace that matches the first one, which is why the `}` inside the description above does not end it early.

The four-space indentation is not decorative: it is what keeps `tools/unwrap-prose.py` from folding this block onto one line, since the house prose rule only knows the `---` and `+++` fences.
