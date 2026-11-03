"""The doctor's `frontmatter-json-drift` warning: a site that still carries
Front Matter CMS's frontmatter.json beside its zer0.json is told each way the
two disagree, since nothing in the platform or the extension reads the first.

The fixtures are trimmed copies of what the registered sites carry: the
first in bash-365.com's shape (`default` and `posts` types, a choice draft
field, folders zer0.json moved on from), the second in lifehacker.dev's
(each type's own copy of the fields zer0.json takes from its `news-core`
field group, which is no difference once the group is inlined).
"""

import json

from sites import doctor

from .doctor_scenarios import ALIGNED, build

ZER0 = {
    "$schema": "https://example.com/zer0.schema.json",
    "contentFolders": [
        {"path": "[[workspace]]/pages/_posts", "contentTypes": ["post"]},
        {"path": "[[workspace]]/pages/_services", "contentTypes": ["service"]},
    ],
    "contentTypes": [
        {
            "name": "post",
            "fields": [
                {"name": "title", "type": "string", "required": True},
                {"name": "keywords", "type": "list"},
                {"name": "date", "type": "datetime", "required": True},
            ],
        },
        {"name": "service", "fields": [{"name": "title", "type": "string", "required": True}]},
    ],
    "draftField": {"name": "draft", "type": "boolean"},
}
FRONT_MATTER = {
    "$schema": "https://frontmatter.codes/frontmatter.schema.json",
    "frontMatter.framework.id": "jekyll",
    "frontMatter.content.draftField": {
        "name": "draft",
        "type": "choice",
        "choices": ["draft", "in progress", "published"],
    },
    "frontMatter.content.pageFolders": [
        {"title": "posts", "path": "[[workspace]]/pages/_posts", "contentTypes": ["post"]},
        {"title": "quests", "path": "[[workspace]]/pages/_quests"},
    ],
    "frontMatter.taxonomy.contentTypes": [
        {"name": "default", "fields": [{"name": "title", "type": "string"}]},
        {
            "name": "post",
            "fields": [
                {"name": "title", "type": "string"},
                {"name": "keywords", "type": "fields", "fields": []},
                {"name": "date", "type": "datetime", "required": True},
                {"name": "prerequisites", "type": "dataFile", "dataType": "quests"},
            ],
        },
    ],
}


def run(tmp_path, front_matter, zer0=ZER0):
    files = {**ALIGNED, "zer0.json": json.dumps(zer0)}
    if front_matter is not None:
        files["frontmatter.json"] = front_matter if isinstance(front_matter, str) else json.dumps(front_matter)
    build(tmp_path, files)
    return [f for f in doctor.run(tmp_path).findings if f["rule"] == "frontmatter-json-drift"]


def test_frontmatter_json_that_disagrees_with_zer0_json_is_a_finding(tmp_path):
    found = run(tmp_path, FRONT_MATTER)
    assert {(f["check_id"], f["severity"], f["file"], f["line"]) for f in found} == {
        ("cms", "warning", "frontmatter.json", None)
    }
    assert [f["evidence"] for f in found] == [
        "content type default is in frontmatter.json, not in zer0.json",
        "content type service is in zer0.json, not in frontmatter.json",
        "content type post: field prerequisites is in frontmatter.json, not in zer0.json",
        "content type post: field title is required in zer0.json, not in frontmatter.json",
        "content type post: field keywords is fields in frontmatter.json, list in zer0.json",
        "content folder pages/_quests is in frontmatter.json, not in zer0.json",
        "content folder pages/_services is in zer0.json, not in frontmatter.json",
        "draftField is draft (choice: draft, in progress, published) in frontmatter.json, draft (boolean) in zer0.json",
    ]
    assert len({f["fingerprint"] for f in found}) == len(found)


def test_a_field_group_inlined_on_one_side_is_no_difference(tmp_path):
    core = [
        {"name": "title", "type": "string", "required": True},
        {"name": "excerpt", "type": "string", "required": True},
    ]
    zer0 = {
        "$schema": "x",
        "contentFolders": [{"path": "[[workspace]]/pages/_posts", "contentTypes": ["hack"]}],
        "fieldGroups": [{"id": "news-core", "fields": core}],
        "contentTypes": [
            {"name": "hack", "fields": [{"name": "core", "type": "fieldCollection", "fieldGroup": "news-core"}]}
        ],
    }
    front_matter = {
        "frontMatter.content.pageFolders": [
            {"title": "Hacks", "path": "[[workspace]]/pages/_posts/", "contentTypes": ["hack"]}
        ],
        "frontMatter.taxonomy.contentTypes": [{"name": "hack", "fields": core}],
    }
    assert run(tmp_path, front_matter, zer0) == []


def test_an_unreadable_frontmatter_json_is_one_warning_and_none_is_none(tmp_path):
    found = run(tmp_path / "broken", "{ not json")
    assert [f["evidence"].split(":")[0] for f in found] == [
        "frontmatter.json is not valid JSON(C), so it cannot be compared"
    ]
    assert run(tmp_path / "none", None) == []
