"""Front-matter line surgery (sites/frontmatter.py, PLAN G4): the Rails
catalog's `test_front_matter.rb`, test for test — parsing, the surgery table,
quoting by YAML's rules, refusing to guess, and the round-trip property over
real front matter from the sister sites (tests/fixtures/front_matter/)."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml

from sites import frontmatter as fm

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "front_matter"


# ── parse ──────────────────────────────────────────────────────────────────


def test_parse_extracts_keys_body_and_raw_values():
    doc = fm.parse(
        "---\ntitle: Hello\ndate: '2025-11-29T16:46:02.000Z'\nn: 3\ndraft: false\ntags: [a]\n---\nBody line\n"
    )
    assert doc.data == {"title": "Hello", "date": "2025-11-29T16:46:02.000Z", "n": 3, "draft": False, "tags": ["a"]}
    assert doc.body == "Body line\n"
    assert doc.raw == "title: Hello\ndate: '2025-11-29T16:46:02.000Z'\nn: 3\ndraft: false\ntags: [a]\n"
    assert doc.raw_values == {"title": "Hello", "date": "2025-11-29T16:46:02.000Z", "n": "3", "draft": "false"}
    assert (doc.fence_style, doc.newline, doc.bom, doc.errors, doc.front_matter) == ("---", "\n", False, [], True)


def test_unquoted_dates_are_typed_but_raw_values_keep_the_text():
    doc = fm.parse("---\ndate: 2025-09-03T12:00:00.000Z\nday: 2026-01-01\n---\n")
    assert isinstance(doc.data["date"], datetime)
    assert type(doc.data["day"]) is date
    assert doc.raw_values == {"date": "2025-09-03T12:00:00.000Z", "day": "2026-01-01"}


def test_bom_crlf_and_dot_fence():
    doc = fm.parse("﻿---\r\ntitle: A\r\n...\r\nBody\r\n")
    assert doc.bom and doc.newline == "\r\n" and doc.fence_style == "..."
    assert doc.data == {"title": "A"} and doc.body == "Body\r\n"


@pytest.mark.parametrize("text", ["Body\n", "---\ntitle: x\nno closing fence\n", ""])
def test_no_block_and_unclosed_block_are_not_front_matter(text):
    doc = fm.parse(text, strict=True)
    assert not doc.front_matter and doc.data == {} and doc.body == text


def test_empty_block_is_an_empty_mapping():
    doc = fm.parse("---\n---\nBody\n", strict=True)
    assert doc.front_matter and doc.data == {}


def test_symbol_looking_scalars_stay_strings():
    assert fm.parse("---\ntitle: :wave\ntags:\n- :ok\n---\n").data == {"title": ":wave", "tags": [":ok"]}


def test_a_collection_as_a_key_is_read_like_jekyll_reads_it():
    """`date: {{date}}` is a mapping whose key is a mapping; Jekyll reads it, so does this."""
    doc = fm.parse("---\ntitle: T\ndate: {{date}}\n---\n", strict=True)
    assert doc.data["title"] == "T" and isinstance(doc.data["date"], dict)


@pytest.mark.parametrize(
    "text, name",
    [
        ("---\ntitle: [x\n---\n", "ParserError"),
        ("---\nx: !ruby/object:Object {}\n---\n", "ConstructorError"),
        ("---\n- a\n- b\n---\n", "NotAMapping"),
    ],
)
def test_lenient_parse_reports_errors_instead_of_raising(text, name):
    doc = fm.parse(text)
    assert doc.data == {} and doc.errors[0].startswith(f"{name}: ")


def test_strict_parse_raises_the_yaml_error():
    with pytest.raises(yaml.YAMLError):
        fm.parse("---\ntitle: [x\n---\n", strict=True)
    with pytest.raises(yaml.constructor.ConstructorError):
        fm.parse("---\nx: !ruby/object:Object {}\n---\n", strict=True)
    with pytest.raises(fm.NotAMapping):
        fm.parse("---\njust a string\n---\n", strict=True)


# ── the surgery ────────────────────────────────────────────────────────────

CASES = [
    (
        "rewrites one scalar, keeps comments and the closing fence",
        "---\ntitle: Hello\n# keep me\nauthor: rhea\n---\nBody\n",
        {"title": "World"},
        "---\ntitle: World\n# keep me\nauthor: rhea\n---\nBody\n",
    ),
    (
        "inserts a missing key before the closing fence",
        "---\ntitle: Hello\n---\nBody\n",
        {"status": "draft"},
        "---\ntitle: Hello\nstatus: draft\n---\nBody\n",
    ),
    (
        "inserts after the last content line, before trailing blanks",
        "---\ntitle: Hello\n# tail comment\n\n---\nBody\n",
        {"status": "draft"},
        "---\ntitle: Hello\n# tail comment\nstatus: draft\n\n---\nBody\n",
    ),
    ("fills an empty block", "---\n---\nBody\n", {"title": "T"}, "---\ntitle: T\n---\nBody\n"),
    ("adds a block to a file without one", "Body\n", {"title": "T"}, "---\ntitle: T\n---\nBody\n"),
    (
        "replaces a whole indented block sequence",
        "---\ntags:\n  - a\n  - b\n# c\nnext: 1\n---\n",
        {"tags": ["x"]},
        "---\ntags:\n  - x\n# c\nnext: 1\n---\n",
    ),
    (
        "keeps an aligned block sequence and its item quotes",
        "---\ntags:\n- '1100'\n- vcs\nn: 1\n---\n",
        {"tags": ["1010", "vcs"]},
        "---\ntags:\n- '1010'\n- vcs\nn: 1\n---\n",
    ),
    (
        "keeps a flow sequence flow, quoting items by YAML rules",
        "---\ntags: [a, b]\n---\n",
        {"tags": ["c", "d, e", "yes", "007"]},
        '---\ntags: [c, "d, e", "yes", "007"]\n---\n',
    ),
    (
        "replaces a folded block scalar and leaves the blank line after it",
        "---\nd: >-\n  text\n  more\n\nnext: 1\n---\n",
        {"d": "new"},
        "---\nd: new\n\nnext: 1\n---\n",
    ),
    (
        "replaces a wrapped plain scalar",
        "---\ndescription: one\n  two\ndate: '2026-07-15'\n---\n",
        {"description": "short"},
        "---\ndescription: short\ndate: '2026-07-15'\n---\n",
    ),
    (
        "replaces a wrapped quoted scalar, keeping its quote style",
        "---\nexcerpt: 'one\n  two'\nn: 1\n---\n",
        {"excerpt": "three"},
        "---\nexcerpt: 'three'\nn: 1\n---\n",
    ),
    (
        "replaces a nested mapping with all its lines",
        "---\nseo:\n  title: a\n  tags:\n  - b\nx: 1\n---\n",
        {"seo": {"title": "c"}},
        "---\nseo:\n  title: c\nx: 1\n---\n",
    ),
    (
        "writes a multi-line string as a literal block",
        "---\nx: 1\n---\n",
        {"note": "line1\nline2\n"},
        "---\nx: 1\nnote: |\n  line1\n  line2\n---\n",
    ),
    (
        "deletes a key and every duplicate of it",
        "---\ndraft: true\nx: 1\ndraft: false\n---\n",
        {"draft": None},
        "---\nx: 1\n---\n",
    ),
    ("deletes a key together with its block", "---\ntags:\n- a\n- b\nx: 1\n---\n", {"tags": None}, "---\nx: 1\n---\n"),
    ("deleting a key that is not there changes nothing", "---\nx: 1\n---\n", {"y": None}, "---\nx: 1\n---\n"),
    (
        "setting a duplicated key rewrites the one the parser reads",
        "---\nt: a\nt: b\n---\n",
        {"t": "c"},
        "---\nt: a\nt: c\n---\n",
    ),
    ("NULL writes an explicit null", "---\nx: 1\n---\n", {"x": fm.NULL}, "---\nx:\n---\n"),
    ("an empty string is written quoted, not as null", "---\nx: 1\n---\n", {"x": ""}, '---\nx: ""\n---\n'),
    (
        "keeps CRLF line endings on new and rewritten lines",
        "---\r\ntitle: A\r\n---\r\nBody\r\n",
        {"title": "B", "tags": ["a"]},
        "---\r\ntitle: B\r\ntags:\r\n  - a\r\n---\r\nBody\r\n",
    ),
    ("keeps a BOM and edits the block after it", "﻿---\ntitle: A\n---\n", {"title": "B"}, "﻿---\ntitle: B\n---\n"),
    ("keeps a `...` closing fence", "---\ntitle: A\n...\nBody\n", {"title": "B"}, "---\ntitle: B\n...\nBody\n"),
    (
        "a raw date equal to the file is not a change",
        "---\ndate: 2025-09-03T12:00:00.000Z\n---\n",
        {"date": "2025-09-03T12:00:00.000Z"},
        "---\ndate: 2025-09-03T12:00:00.000Z\n---\n",
    ),
    (
        "a single-quoted date stays single-quoted",
        "---\ndate: '2025-11-29T16:46:02.000Z'\n---\n",
        {"date": "2025-12-01T00:00:00.000Z"},
        "---\ndate: '2025-12-01T00:00:00.000Z'\n---\n",
    ),
    (
        "a plain date given back as text stays a plain date",
        "---\ndate: 2025-09-03\n---\n",
        {"date": "2025-10-03"},
        "---\ndate: 2025-10-03\n---\n",
    ),
    (
        "a boolean given back as text stays a boolean",
        "---\ndraft: false\n---\n",
        {"draft": "true"},
        "---\ndraft: true\n---\n",
    ),
    (
        "dates, times and numbers are written as YAML reads them",
        "---\nx: 1\n---\n",
        {"at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "day": date(2026, 1, 2), "f": 1.5},
        "---\nx: 1\nat: 2026-01-02T03:04:05Z\nday: 2026-01-02\nf: 1.5\n---\n",
    ),
]


@pytest.mark.parametrize("what, text, changes, expected", CASES, ids=[c[0] for c in CASES])
def test_surgery_table(what, text, changes, expected):
    output = fm.update_keys(text, changes)
    assert output == expected
    fm.parse(output, strict=True)


def test_an_empty_or_equal_change_set_returns_the_text_itself():
    text = "---\ntitle: Hello\n---\nBody\n"
    assert fm.update_keys(text, {}) is text
    assert fm.update_keys(text, {"title": "Hello"}) is text


QUOTING = {
    "plain words": "plain words",
    "a:b": "a:b",
    "Yes": '"Yes"',
    "no": '"no"',
    "on": '"on"',
    "off": '"off"',
    "null": '"null"',
    "~": '"~"',
    "true": '"true"',
    "2026": '"2026"',
    "007": '"007"',
    "1.5": '"1.5"',
    "1:30": '"1:30"',
    "2026-01-01": '"2026-01-01"',
    "[Draft] Terminal": '"[Draft] Terminal"',
    "*wildcard*": '"*wildcard*"',
    "&anchor": '"&anchor"',
    "!tag": '"!tag"',
    "@handle": '"@handle"',
    "`tick`": '"`tick`"',
    "% pct": '"% pct"',
    "#{x}": '"#{x}"',
    "a: b": '"a: b"',
    "a #b": '"a #b"',
    " lead": '" lead"',
    "trail ": '"trail "',
    "- item": '"- item"',
    "? q": '"? q"',
    ":wave:": '":wave:"',
    'mid\\slash "q"': 'mid\\slash "q"',
    '"q" back\\slash': '"\\"q\\" back\\\\slash"',
    "tab\there": '"tab\\there"',
    "bell\a": '"bell\\u0007"',
}


@pytest.mark.parametrize("value, written", QUOTING.items())
def test_scalars_are_quoted_by_yaml_rules(value, written):
    output = fm.update_keys("---\nx: 1\n---\n", {"k": value})
    assert output == f"---\nx: 1\nk: {written}\n---\n"
    assert yaml.safe_load("".join(output.splitlines(keepends=True)[1:-1]))["k"] == value


@pytest.mark.parametrize(
    "text, changes",
    [
        ("---\ntitle: x\nno closing fence\n", {"title": "y"}),
        ("---\ntitle: [x\n---\n", {"title": "y"}),
        ("---\n{a: 1}\n---\n", {"b": 2}),
        ("---\n- a\n---\n", {"b": 2}),
    ],
)
def test_refuses_to_guess(text, changes):
    with pytest.raises(fm.EditError):
        fm.update_keys(text, changes)


def test_dump_builds_a_block():
    assert fm.dump({"title": "Yes", "date": date(2026, 1, 2)}) == '---\ntitle: "Yes"\ndate: 2026-01-02\n---\n'


# ── real front matter from the sister sites ────────────────────────────────

SENTINEL = "zer0-sentinel"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def as_changes(data):
    return {k: fm.NULL if v is None else v for k, v in data.items()}


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.md")), ids=lambda p: p.name)
def test_every_fixture_round_trips(path):
    text = path.read_text(encoding="utf-8")
    doc = fm.parse(text, strict=True)
    assert doc.data
    assert fm.update_keys(text, as_changes(doc.data)) == text, "a no-op must be byte-identical"
    for key, value in doc.data.items():
        moved = fm.update_keys(text, {key: SENTINEL})
        back = fm.update_keys(moved, {key: fm.NULL if value is None else value})
        assert fm.same_value(doc.data, fm.parse(back, strict=True).data), f"{key} did not re-emit"
        assert fm.update_keys(text, {key: None}) == fm.update_keys(back, {key: None}), f"{key} moved other lines"


def test_lifehacker_flow_lists_and_sources():
    text = fixture("lifehacker-wire-dispatch.md")
    out = fm.update_keys(
        text, {"tags": ["news", "ai"], "sources": ["https://example.com/a", "https://example.com/b?x=1#frag"]}
    )
    assert "\ntags: [news, ai]\n" in out
    assert "\nsources:\n  - https://example.com/a\n  - https://example.com/b?x=1#frag\n---\n" in out
    assert "\ncategories: [The Wire]\n" in out
    assert out.endswith("---\nStub body copied for tests; the front matter above is real.\n")
    assert fm.parse(out).data["sources"] == ["https://example.com/a", "https://example.com/b?x=1#frag"]


def test_it_journey_wrapped_scalars_and_aligned_lists():
    out = fm.update_keys(
        fixture("it-journey-quest-report.md"), {"description": "One line now.", "tags": ["walkthrough", "0101"]}
    )
    assert "\ndescription: One line now.\ndate: '2026-07-15T12:13:59.000Z'\n" in out
    assert "\ntags:\n- walkthrough\n- '0101'\nrender_with_liquid: false\n" in out
    doc = fm.parse(out, strict=True)
    assert doc.data["tags"][-1] == "0101" and doc.data["date"] == "2026-07-15T12:13:59.000Z"


def test_it_journey_nested_maps():
    text = fixture("it-journey-quest.md")
    original = fm.parse(text).data
    deps = {"required_quests": [], "unlocks_quests": ["/quests/1010/elk-stack/"]}
    data = fm.parse(fm.update_keys(text, {"quest_dependencies": deps, "prerequisites": None}), strict=True).data
    assert data["quest_dependencies"] == deps and "prerequisites" not in data
    rest = {k: v for k, v in original.items() if k not in ("quest_dependencies", "prerequisites")}
    assert {k: v for k, v in data.items() if k != "quest_dependencies"} == rest


def test_block_lists_and_typed_dates():
    text = fixture("theme-docs-post.md")
    doc = fm.parse(text)
    assert fm.update_keys(text, {"date": doc.raw_values["date"], "lastmod": doc.raw_values["lastmod"]}) is text
    out = fm.update_keys(text, {"tags": ["jekyll", "themes"], "lastmod": "2026-09-14T00:00:00.000Z"})
    assert "\ntags:\n  - jekyll\n  - themes\ndate: 2025-01-01T08:00:00.000Z\n" in out
    assert "\nlastmod: 2026-09-14T00:00:00.000Z\n" in out
    assert isinstance(fm.parse(out).data["lastmod"], datetime)


def test_it_journey_nulls():
    text = fixture("it-journey-note-nulls.md")
    out = fm.update_keys(text, {"excerpt": None})
    assert "\nexcerpt:" not in out and out == text.replace("excerpt: null\n", "")
