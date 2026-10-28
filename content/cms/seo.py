"""The SEO and social fields a page has beyond Wagtail's own title, SEO title
and description: its canonical URL, its Open Graph title, description and
image, and `noindex` — and the front-matter key each one is in a site's file.

| Field            | Front-matter key  | Read by                                                        |
|------------------|-------------------|----------------------------------------------------------------|
| `canonical_url`  | `canonical_url`   | jekyll-seo-tag's `<link rel="canonical">`; the distribution ledger's key |
| `og_title`       | `og_title`        | the renderer (jekyll-seo-tag shares the title)                  |
| `og_description` | `og_description`  | the renderer (jekyll-seo-tag shares the description)            |
| `og_image`       | `image`           | jekyll-seo-tag's `og:image` and `twitter:image` (the zer0 sites' per-page social image; `preview` stays the teaser) |
| `noindex`        | `noindex`         | the renderer's robots meta (the zer0 front-matter vocabulary)   |

**A field is the file's until a person sets it.** Each one is null on a page
whose value is what its stored front matter says (`from_front_matter`) — every
imported page, and every page read before these fields existed, row or
revision — and holds a value only once a person sets one. `effective` is what a
page says either way; the hash (`BasePage.hashed_content`) and the exporter
(`exporters/jekyll.py`) count a field only where it differs from its file, so an
unchanged imported page still exports byte for byte and a key a person never
touched is never rewritten, whatever form it has in the file (an `image:` that
is jekyll-seo-tag's `{path: …}` mapping included). A key a field owns is no
longer raw front matter (cms/files.py).
"""

FIELDS = {
    "canonical_url": "canonical_url",
    "og_title": "og_title",
    "og_description": "og_description",
    "og_image": "image",
    "noindex": "noindex",
}
# The front-matter key each field is written to (BasePage.front_matter_fields).
KEYS = {key: name for name, key in FIELDS.items()}


def from_front_matter(front_matter) -> dict:
    """What a file's front matter says each field is: its text, or `noindex:
    true`; a key it lacks, or a value the field cannot hold, says the default."""
    fm = front_matter if isinstance(front_matter, dict) else {}
    out = {}
    for name, key in FIELDS.items():
        value = fm.get(key)
        out[name] = value is True if name == "noindex" else value if isinstance(value, str) else ""
    return out


def effective(page) -> dict:
    """The page's SEO fields: each its own value, or its file's while it has none."""
    said = from_front_matter(page.front_matter)
    return {name: said[name] if getattr(page, name) is None else getattr(page, name) for name in FIELDS}


def changed(page) -> dict:
    """The fields whose value differs from what the page's front matter says."""
    said = from_front_matter(page.front_matter)
    return {name: value for name, value in effective(page).items() if value != said[name]}
