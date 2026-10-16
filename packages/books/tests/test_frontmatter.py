"""Front matter parsing, including the no-PyYAML fallback path."""

from __future__ import annotations

import pytest

from bookshelf import frontmatter

SAMPLE = """\
---
title: The Impairment
number: 3
ratio: 1.5
draft: true
missing: null
tags: [one, two, three]
cast:
  - Kareem Hassan
  - The CFO
quoted: "A title: with a colon"
---

Body text stays put.
"""


@pytest.fixture(params=["pyyaml", "fallback"])
def parser(request, monkeypatch):
    """Run every parsing test through both implementations."""
    if request.param == "fallback":
        monkeypatch.setattr(frontmatter, "_pyyaml", None)
    elif frontmatter._pyyaml is None:
        pytest.skip("PyYAML is not installed")
    return request.param


def test_parses_scalars_and_lists(parser):
    doc = frontmatter.parse(SAMPLE)
    assert doc.meta["title"] == "The Impairment"
    assert doc.meta["number"] == 3
    assert doc.meta["ratio"] == 1.5
    assert doc.meta["draft"] is True
    assert doc.meta["missing"] is None
    assert doc.meta["tags"] == ["one", "two", "three"]
    assert doc.meta["cast"] == ["Kareem Hassan", "The CFO"]
    assert doc.meta["quoted"] == "A title: with a colon"


def test_body_is_preserved_verbatim(parser):
    doc = frontmatter.parse(SAMPLE)
    assert doc.body == "\nBody text stays put.\n"


def test_document_without_front_matter(parser):
    doc = frontmatter.parse("# Just a heading\n")
    assert doc.meta == {}
    assert doc.has_front_matter is False
    assert doc.body == "# Just a heading\n"


def test_unclosed_front_matter_raises(parser):
    with pytest.raises(frontmatter.FrontMatterError):
        frontmatter.parse("---\ntitle: x\n\nno closing fence\n")


def test_round_trip_preserves_body_and_blank_line(parser):
    doc = frontmatter.parse(SAMPLE)
    rebuilt = frontmatter.render(doc.meta, doc.body)
    assert frontmatter.parse(rebuilt).body == doc.body
    assert rebuilt.startswith("---\ntitle: The Impairment\n")
    assert "\n---\n\nBody text stays put.\n" in rebuilt


def test_render_quotes_values_that_need_it():
    rendered = frontmatter.dumps({"a": "plain", "b": "has, comma", "c": "trailing: colon", "d": "true"})
    assert "a: plain" in rendered
    assert 'b: "has, comma"' in rendered
    assert 'c: "trailing: colon"' in rendered
    assert 'd: "true"' in rendered


# -- fallback-only behaviour ---------------------------------------------
def test_fallback_rejects_nested_mappings(monkeypatch):
    monkeypatch.setattr(frontmatter, "_pyyaml", None)
    with pytest.raises(frontmatter.FrontMatterError, match="nested mappings"):
        frontmatter.loads("outer:\n  inner: value\n")


def test_fallback_reports_the_offending_line(monkeypatch):
    monkeypatch.setattr(frontmatter, "_pyyaml", None)
    with pytest.raises(frontmatter.FrontMatterError, match="line 2"):
        frontmatter.loads("good: value\nthis line has no colon\n")


def test_fallback_strips_comments_outside_quotes(monkeypatch):
    monkeypatch.setattr(frontmatter, "_pyyaml", None)
    meta = frontmatter.loads('a: value # a comment\nb: "kept # inside"\n# whole line\nc: 1\n')
    assert meta == {"a": "value", "b": "kept # inside", "c": 1}


def test_an_unquoted_colon_is_rejected_by_both_parsers(parser):
    """The fallback must stay a strict subset: what PyYAML rejects, it rejects.

    Otherwise a book.yml passes `books validate` in a bare checkout and then
    fails in CI, where PyYAML happens to be installed.
    """
    with pytest.raises(frontmatter.FrontMatterError):
        frontmatter.loads("logline: One sentence: who wants what\n")


def test_a_colon_inside_a_url_is_fine(parser):
    assert frontmatter.loads("source: https://example.com/x\n")["source"] == "https://example.com/x"


def test_fallback_handles_quoted_commas_in_inline_lists(monkeypatch):
    monkeypatch.setattr(frontmatter, "_pyyaml", None)
    assert frontmatter.loads('t: [one, "two, still two", three]\n')["t"] == ["one", "two, still two", "three"]


def test_both_parsers_agree_on_the_sample():
    if frontmatter._pyyaml is None:
        pytest.skip("PyYAML is not installed")
    raw = frontmatter.split(SAMPLE)[0]
    assert frontmatter.loads(raw) == frontmatter._loads_subset(raw)
