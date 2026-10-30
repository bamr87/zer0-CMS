"""The structured blocks a Jekyll body's paragraphs become (P4, G2's blocks):
each one the importer cuts — a table, a typed table, a callout, an embed, a
document link, an HTML block, a Liquid template — writes its paragraph back
byte for byte, a paragraph no block writes back exactly stays Markdown, and on
every real site in the repository the cut changes nothing the body writes."""

import re
from pathlib import Path

import pytest
from django.conf import settings

from importers import frontmatter
from importers import markdown as md
from importers.jekyll import import_site
from importers.markdown import block_to_markdown, from_blocks, to_blocks
from importers.models import ImportedSource
from sites import catalog

REPO = Path(settings.REPO_ROOT)

EVERY_BLOCK = """
Intro paragraph with an {% include note.html %} inside it.

| Name | Role |
|---|---|
| Ada | engineer |
| Grace | admiral |

| Quarter | Patriots | Notes |
|---|---|---|
| 1 | 7 | opening drive |
| 2 | 14 | \\| escaped pipe |

> [!tip]- Rule of thumb
> Keep notes small.
>
> Link them.

https://www.youtube.com/watch?v=7_LPdttKXPc

[The annual report](/assets/files/report.pdf)

<div class="note">
<p>Raw HTML stays, {{ '/x/' | relative_url }} too.</p>
</div>

{% capture rules %}
- one

- two
{% endcapture %}
{% include callout.html content=rules %}

Closing paragraph.
"""


@pytest.mark.django_db
def test_every_structured_block_is_cut_and_written_back_byte_for_byte():
    blocks = to_blocks(EVERY_BLOCK)
    assert [b["type"] for b in blocks] == [
        "markdown",
        "table",
        "typed_table",
        "callout",
        "embed",
        "document",
        "raw_html",
        "liquid",
        "markdown",
    ]
    assert from_blocks(blocks) == EVERY_BLOCK
    table, typed, callout, embed, document = (b["value"] for b in blocks[1:6])
    assert table["data"] == [["Name", "Role"], ["Ada", "engineer"], ["Grace", "admiral"]]
    assert table["first_row_is_table_header"] and table["table_header_choice"] == "row"
    assert [c["type"] for c in typed["columns"]] == ["number", "number", "text"]
    assert typed["rows"][1]["values"] == ["2", "14", "\\| escaped pipe"]
    assert callout == {"kind": "tip", "fold": "-", "title": "Rule of thumb", "body": "Keep notes small.\n\nLink them."}
    assert embed == "https://www.youtube.com/watch?v=7_LPdttKXPc"
    assert document == {"title": "The annual report", "href": "/assets/files/report.pdf", "document": None}
    assert "{% endcapture %}" in blocks[7]["value"] and "- two" in blocks[7]["value"]  # a capture holds blank lines
    for block in blocks:  # each block is stored exactly as the importer cut it: re-cutting its text gives it back
        assert to_blocks(block_to_markdown(block["type"], block["value"])) == [block]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "text",
    [
        "| a | b |\n| --- | --- |\n| 1 | 2 |",  # a spaced rule: not the table block's own form
        "| a | b |\n|---|---|\n| 1 |",  # ragged
        "| a | b |\n|---|---|\n| `x|y` | 2 |",  # a pipe a code span hides from a person, not from Markdown
        "> [!note] Title\n>body without the space",
        "> [!note] Title\n> \n> trailing space on the blank line",
        "https://example.com and some words",
        "[A page, not a file](/docs/setup/)",
        "<span>inline HTML is a paragraph</span>",
        "<!-- a comment that goes on",
        "{% include toc.html %}\nthen prose",
        "{% endif %}",
        "  | indented | table |\n  |---|---|",
    ],
)
def test_a_paragraph_no_block_writes_back_exactly_stays_markdown(text):
    assert to_blocks(text) == [{"type": "markdown", "value": text}]


def _real_bodies(site: str):
    root = REPO / site
    if not (root / "_config.yml").is_file():
        pytest.skip(f"{site} is not in this checkout")
    for entry in catalog.scan(root).entries:
        if not entry.error:
            text = Path(entry.path).read_bytes().decode("utf-8")
            yield entry.relative, frontmatter.split(text)[1]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "site",
    [
        "sites/zer0-demo-garden",
        "sites/zer0-demo-cookbook",
        "sites/drsai",
        "sites/irony-works",
        pytest.param("sites/wargames", marks=pytest.mark.slow),
        pytest.param("sites/2005", marks=pytest.mark.slow),
        pytest.param("sites/zer0-pages", marks=pytest.mark.slow),
    ],
)
def test_on_the_real_sites_each_cut_is_its_own_text_and_changes_nothing_the_body_writes(site, monkeypatch):
    bodies = list(_real_bodies(site))
    cut = {rel: to_blocks(body) for rel, body in bodies}
    found = {b["type"] for blocks in cut.values() for b in blocks}
    monkeypatch.setattr(md, "structured", lambda text: [{"type": "markdown", "value": text}])
    for rel, body in bodies:
        assert from_blocks(cut[rel]) == from_blocks(to_blocks(body)), rel
        for block in cut[rel]:
            if block["type"] not in ("markdown", "heading", "code"):
                assert block_to_markdown(block["type"], block["value"]) in body, (rel, block["type"])
    assert found & {"table", "typed_table", "callout", "raw_html", "liquid"}, f"{site} has none of the blocks"


@pytest.mark.django_db
def test_an_edited_page_writes_its_other_blocks_back_byte_for_byte(tmp_path):
    from exporters.jekyll import export_site

    site = tmp_path / "site"
    (site / "_posts").mkdir(parents=True)
    (site / "_config.yml").write_text("title: Blocks\n")
    post = "_posts/2026-10-01-blocks.md"
    (site / post).write_text("---\ntitle: Blocks\ndate: 2026-10-01\n---\n" + EVERY_BLOCK)
    assert not import_site(site, "blocks").errors
    page = ImportedSource.objects.get(site_key="blocks", legacy_path=post).page.specific
    draft = page.get_latest_revision_as_object()
    draft.title = "Every block"
    draft.save_revision().publish()
    out = tmp_path / "out"
    export_site("blocks", out)
    head = "---\ntitle: Every block\ndate: 2026-10-01\n---\n"
    assert (out / post).read_text() == head + EVERY_BLOCK  # the body kept as written

    draft = page.get_latest_revision_as_object()
    body = list(draft.body.get_prep_value())
    body[-1]["value"] = "A new closing paragraph."
    draft.body = body
    draft.save_revision().publish()
    export_site("blocks", out)
    assert (out / post).read_text() == head + EVERY_BLOCK.replace("Closing paragraph.", "A new closing paragraph.")


@pytest.mark.django_db
def test_the_preview_shows_every_block_and_runs_none_of_them(tmp_path, client, editor):
    site = tmp_path / "site"
    (site / "_posts").mkdir(parents=True)
    (site / "_config.yml").write_text("title: Blocks\n")
    hostile = '<div onclick="alert(1)"><script>alert(2)</script></div>'
    (site / "_posts/2026-10-01-blocks.md").write_text(
        "---\ntitle: Blocks\ndate: 2026-10-01\n---\n" + EVERY_BLOCK + "\n" + hostile + "\n"
    )
    assert not import_site(site, "blocks").errors
    page = ImportedSource.objects.get(site_key="blocks").page.specific
    assert page.body[-1].block_type == "raw_html"
    client.force_login(editor)
    response = client.get(f"/admin/pages/{page.pk}/view_draft/")
    html = response.content.decode()
    assert response.status_code == 200 and html.count('data-block-type="') == 10
    assert re.search(r"<td\s*>\s*engineer\s*</td>", html) and "<td>14</td>" in html  # by Wagtail's table templates
    assert '<a href="https://www.youtube.com/watch?v=7_LPdttKXPc">' in html  # an embed is a link, never fetched
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in html and "<script>alert(2)" not in html  # raw HTML is source
