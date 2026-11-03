"""The platform's reading of a site's Front Matter content model
(sites/content_model.py) against the extension's.

The cases are src/test/fixtures/golden/content-model/cases.json, which
src/test/fixtures/golden/generate.py writes from this module and
src/test/golden.test.ts holds the extension's `getContentTypes`,
`resolveContentType` and `validateFields` to. Here the module is held to the
same file, so a change to either side that the other does not make fails one
of the two suites. The first case site is a trimmed copy of lifehacker.dev's
zer0.json.
"""

import copy
import json
from pathlib import Path

import pytest

from sites import content_model

REPO = Path(__file__).resolve().parents[3]
CASES = json.loads((REPO / "src/test/fixtures/golden/content-model/cases.json").read_text())
SCHEMA = json.loads((REPO / "schemas/zer0.schema.json").read_text())


def case(name: str) -> dict:
    return next(site for site in CASES["sites"] if site["name"] == name)


def field_names(fields: list, parents: tuple = ()) -> list:
    out = []
    for f in fields:
        out.append(".".join((*parents, f["name"])))
        if f["type"] == "fields":
            out += field_names(f.get("fields") or [], (*parents, f["name"]))
    return out


def test_field_types_and_operators_are_the_schemas_enums():
    assert list(content_model.FIELD_TYPES) == SCHEMA["definitions"]["fieldType"]["enum"]
    assert list(content_model.WHEN_OPERATORS) == SCHEMA["definitions"]["whenClause"]["properties"]["operator"]["enum"]


def test_lifehacker_hack_inlines_news_core_and_resolves_by_folder():
    site = content_model.model(case("lifehacker")["zer0"], CASES["root"])
    hack = next(t for t in site.types if t["name"] == "hack")
    assert [f["name"] for f in hack["fields"]] == [
        *("title", "description", "date", "excerpt", "tags", "preview"),  # news-core, in the group's order
        *("categories", "author", "permalink", "featured"),
    ]
    assert [f["name"] for f in hack["fields"] if f.get("required")] == [
        *("title", "description", "date", "excerpt", "tags", "categories", "author")
    ]
    rel = "pages/_posts/hacks/2026-09-02-thin.md"
    data = {"title": "T", "description": "  ", "date": "2026-09-02", "excerpt": "<failed to process>", "tags": []}
    assert content_model.resolve(site, rel, data)["name"] == "hack"
    assert content_model.missing_fields(site, hack, data) == ["description", "excerpt", "tags", "categories", "author"]
    # The deepest folder wins: a post loose in pages/_posts is a field note, a page under pages a page.
    assert content_model.resolve(site, "pages/_posts/2026-09-04-loose.md", {})["name"] == "field-note"
    assert content_model.resolve(site, "pages/about.md", {})["name"] == "page"


def test_the_overlays_type_key_resolves_a_file_only_where_zer0_json_names_the_overlay():
    named = case("lifehacker")["zer0"]
    site = content_model.model(named, CASES["root"])
    assert site.type_key == "fmContentType"
    assert content_model.resolve(site, "pages/_docs/landing.md", {"fmContentType": "page"})["name"] == "page"
    assert content_model.resolve(site, "pages/_docs/landing.md", {"fmContentType": "page", "type": "hack"})["name"] == (
        "hack"
    ), "the file's own `type` comes first"
    bare = content_model.model({**named, "platform": {"id": "jekyll", "overlay": None}}, CASES["root"])
    assert bare.type_key is None
    assert content_model.resolve(bare, "pages/_docs/landing.md", {"fmContentType": "page"})["name"] == "doc"
    hugo = {"id": "hugo", "overrides": {"frontMatter": {"typeKey": "kind"}}}
    assert content_model.type_key({"id": "hugo"}) == "type" and content_model.type_key(hugo) == "kind"


@pytest.mark.parametrize("name", [site["name"] for site in CASES["sites"]])
def test_validation_matches_the_extension_golden(name):
    golden = case(name)
    site = content_model.model(golden["zer0"], CASES["root"])
    assert {t["name"]: field_names(t["fields"]) for t in site.types} == golden["types"]
    for file in golden["files"]:
        ctype = content_model.resolve(site, file["path"], file["data"])
        answer = {"type": ctype["name"], "missing": content_model.missing_fields(site, ctype, file["data"])}
        assert answer == {"type": file["type"], "missing": file["missing"]}, file["path"]


def test_inlining_is_new_idempotent_and_safe_from_a_group_that_contains_itself():
    rules = case("rules")["zer0"]
    before = copy.deepcopy(rules)
    site = content_model.model(rules, CASES["root"])
    article = next(t for t in site.types if t["name"] == "article")
    assert content_model.inline_field_collections(article["fields"], site.groups) == article["fields"]
    assert rules == before, "reading a zer0.json never changes it"
    assert "looped" in field_names(article["fields"]) and "again" not in field_names(article["fields"])


def test_coercion_drops_what_the_extension_drops():
    data = {
        "contentTypes": [
            {"fields": []},
            {
                "name": "t",
                "fields": [
                    {"name": "json", "type": "json", "required": True},  # D6 dropped the type
                    {"type": "string"},
                    {"name": "kept", "type": "string", "required": "yes", "when": {"operator": "eq"}},
                ],
            },
        ],
    }
    site = content_model.model(data, "/site")
    assert [(t["name"], t["fields"]) for t in site.types] == [("t", [{"name": "kept", "type": "string"}])]
    assert site.declared == 1


def test_a_when_compares_as_javascript_does():
    shown = {"name": "x", "type": "string", "when": {"fieldRef": "n", "operator": "eq", "value": 1}}
    field = content_model.model({"contentTypes": [{"name": "t", "fields": [shown]}]}, "/").types[0]["fields"][0]
    assert content_model.evaluate_when(field, {"n": 1}, [field])
    assert not content_model.evaluate_when(field, {"n": True}, [field]), "true === 1 is false"
    assert not content_model.evaluate_when(field, {"n": "1"}, [field])
    assert not content_model.evaluate_when(field, {}, [field]), "undefined === 1 is false"
    assert content_model.is_empty(field, " \t") and not content_model.is_empty(field, 0)
    assert not content_model.is_empty({"name": "b", "type": "boolean"}, False)
