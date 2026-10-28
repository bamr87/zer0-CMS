"""zer0 doctor in Python (sites/doctor.py, PLAN G4) against the Ruby doctor it
replaces.

The parity tests build each scenario of the Rails catalog's `test_doctor.rb`
(tests/sites/doctor_scenarios.py) and the three fixture sites, run the doctor,
and compare with what the Ruby doctor recorded on the very same files
(tests/fixtures/doctor/ruby-recording.json), finding for finding — check,
severity, rule, file, line, evidence and fingerprint — except:

* the rules ADR 0006 drops: the theme check's `theme-not-zer0` and
  `no-theme-overrides`, and the theme schema's `missing-key:*` warnings;
* `config-unreadable`, the theme check's one generic rule, is now the
  `config` check's (so its fingerprint has the new check id);
* a YAML or JSON syntax error's evidence is the parser's wording (PyYAML's,
  Python's json), compared by rule, file and line;
* `vendored-linkedin-publisher` names the lane that replaces a per-site
  publisher, `manage.py linkedin` (the Ruby doctor named `zer0-cms linkedin`,
  deleted with rails/), so it too is compared by rule, file and line.

The rest ports `test_doctor.rb`'s assertions, and adds the generic content
check that replaced the theme schema: required fields from the site's own
content types, and zer0.json against schemas/zer0.schema.json.
"""

import hashlib
import io
import json
from datetime import date
from pathlib import Path

import pytest

from sites import doctor

from .doctor_scenarios import ALIGNED, SCENARIOS, aligned, build, digest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
RECORDING = json.loads((FIXTURES / "doctor" / "ruby-recording.json").read_text())
RECORDED_ON = date(2026, 10, 22)
NEW_RULES = ("zer0-json-schema",)
SYNTAX = (
    "front matter:",
    "_config.yml does not parse:",
    "zer0.json is not valid JSON(C):",
    "not valid YAML:",
    "not strict YAML:",
)


def comparable(f: dict) -> str:
    f = dict(f)
    if f["check_id"] == "theme":  # its one generic rule moved to the config check
        f["check_id"] = "config"
        f["fingerprint"] = doctor.finding("config", f["severity"], f["rule"], f["evidence"], file=f["file"])[
            "fingerprint"
        ]
    if f["evidence"].startswith(SYNTAX) or f["rule"] == "vendored-linkedin-publisher":
        f.pop("evidence"), f.pop("fingerprint")
    return json.dumps(f, sort_keys=True)


def assert_matches_ruby(root: Path, recorded: dict):
    python = doctor.run(root, today=RECORDED_ON).findings
    kept = [f for f in recorded["findings"] if not f.get("dropped")]
    assert sorted(map(comparable, (f for f in python if f["rule"] not in NEW_RULES))) == sorted(map(comparable, kept))
    assert (0 if not any(f["severity"] == "error" for f in python) else 1) == (
        0 if not any(f["severity"] == "error" for f in kept) else 1
    ), "the exit status follows the errors that are left"


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_each_scenario_matches_the_ruby_doctor(name, tmp_path):
    recorded = RECORDING["scenarios"][name]
    assert recorded["digest"] == digest(SCENARIOS[name]), "the scenario changed since the Ruby doctor recorded it"
    build(tmp_path, SCENARIOS[name])
    assert_matches_ruby(tmp_path, recorded)


@pytest.mark.parametrize("name", sorted(RECORDING["fixtures"]))
def test_each_fixture_site_matches_the_ruby_doctor(name):
    assert_matches_ruby(FIXTURES / name, RECORDING["fixtures"][name])


def test_the_recording_shows_what_was_dropped():
    dropped = {
        f["rule"] if not f["rule"].startswith("missing-key:") else "missing-key:*"
        for site in [*RECORDING["scenarios"].values(), *RECORDING["fixtures"].values()]
        for f in site["findings"]
        if f.get("dropped")
    }
    assert dropped == {"theme-not-zer0", "no-theme-overrides", "missing-key:*"}


# ── test_doctor.rb, ported ─────────────────────────────────────────────────


def site(tmp_path, files) -> Path:
    build(tmp_path, files)
    return tmp_path


def rules(report, severity=None):
    return sorted(f["rule"] for f in report.findings if severity is None or f["severity"] == severity)


def test_an_aligned_site_is_clean(tmp_path):
    report = doctor.run(site(tmp_path, aligned()), today=RECORDED_ON)
    assert report.findings == [] and report.ok


def test_distribution_check(tmp_path):
    report = doctor.run(site(tmp_path / "invalid", SCENARIOS["distribution-invalid"]), today=RECORDED_ON)
    assert [r for r in rules(report, "error") if "distribution" in r] == ["distribution-config-invalid"]
    assert "distribution-config" in rules(report, "warning") and not report.ok
    for name, rule in (
        ("distribution-ledger", "distribution-ledger-unreadable"),
        ("distribution-outside", "distribution-config-invalid"),
    ):
        assert rule in rules(doctor.run(site(tmp_path / name, SCENARIOS[name]), today=RECORDED_ON), "error")
    vendored = doctor.run(site(tmp_path / "vendored", SCENARIOS["distribution-vendored"]), today=RECORDED_ON)
    found = next(f for f in vendored.findings if f["rule"] == "vendored-linkedin-publisher")
    assert (found["severity"], found["file"]) == ("warning", "scripts/features/linkedin/posts.py")


def test_the_linkedin_api_version_window_follows_the_date(tmp_path):
    root = site(tmp_path, SCENARIOS["distribution-valid"])
    assert doctor.run(root, today=date(2026, 9, 1)).findings == []
    assert "distribution-config" in rules(doctor.run(root, today=date(2027, 6, 1)), "warning")  # aging
    assert "distribution-config-invalid" in rules(doctor.run(root, today=date(2027, 8, 1)), "error")  # sunset


def test_config_check(tmp_path):
    broken = doctor.run(site(tmp_path / "broken", SCENARIOS["config-broken"]))
    found = next(f for f in broken.findings if f["rule"] == "config-unreadable")
    assert (found["check_id"], found["severity"], found["file"], found["line"]) == ("config", "error", "_config.yml", 1)
    assert "config-unreadable" in rules(doctor.run(site(tmp_path / "missing", SCENARIOS["config-missing"])), "error")
    # The theme a site renders with is not the doctor's business any more (ADR 0006 decision 4).
    assert rules(doctor.run(site(tmp_path / "other", SCENARIOS["theme-other"]))) == []


def test_image_engine_check(tmp_path):
    report = doctor.run(site(tmp_path, SCENARIOS["image-engine"]))
    assert rules(report, "error") == ["vendored-preview-fork"] * 3
    assert rules(report, "warning") == ["gemfile-missing-image-generator", "no-preview-images-config"]
    assert sorted(f["file"] for f in report.findings if f["severity"] == "error") == [
        "_plugins/preview_generator.rb",
        "_plugins/preview_image_generator.rb",
        "scripts/lib/preview_generator.py",
    ]


def test_a_namesake_that_does_not_read_preview_images_is_not_a_fork(tmp_path):
    assert "vendored-preview-fork" not in rules(doctor.run(site(tmp_path, SCENARIOS["image-engine-namesake"])))


def test_cms_check(tmp_path):
    assert rules(doctor.run(site(tmp_path / "a", SCENARIOS["cms-missing"]))) == ["no-zer0-json"]
    folder = doctor.run(site(tmp_path / "b", SCENARIOS["cms-folder-missing"]))
    assert rules(folder, "error") == ["content-folder-missing"]
    assert rules(folder, "warning") == ["zer0-json-no-schema"]
    assert rules(doctor.run(site(tmp_path / "c", SCENARIOS["cms-jsonc"]))) == ["zer0-json-schema"]  # `a` is no setting
    assert rules(doctor.run(site(tmp_path / "d", SCENARIOS["cms-invalid"])), "error") == ["zer0-json-invalid"]


@pytest.mark.parametrize("name", ["fleet-wrapped", "fleet-duplicate", "fleet-list", "fleet-alias"])
def test_fleet_check_is_strict(tmp_path, name):
    assert rules(doctor.run(site(tmp_path, SCENARIOS[name])), "error") == ["fleet-manifest-invalid"]


def test_a_missing_fleet_manifest_is_fine(tmp_path):
    assert rules(doctor.run(site(tmp_path, SCENARIOS["fleet-missing"]))) == []


def test_content_check(tmp_path):
    report = doctor.run(site(tmp_path, SCENARIOS["content"]))
    broken = next(f for f in report.findings if f["rule"] == "front-matter-invalid")
    assert (broken["severity"], broken["file"], broken["line"]) == ("error", "pages/_posts/2026-01-03-broken.md", 2)


# ── the generic content check (what replaced the theme schema) ─────────────

TYPED = {
    **ALIGNED,
    "zer0.json": json.dumps(
        {
            "$schema": "https://example.com/zer0.schema.json",
            "contentFolders": [
                {"path": "[[workspace]]/pages/_posts", "contentTypes": ["post"]},
            ],
            "contentTypes": [
                {
                    "name": "post",
                    "fields": [
                        {"name": "title", "type": "string", "required": True},
                        {"name": "summary", "type": "string", "required": True},
                        {
                            "name": "teaser",
                            "type": "string",
                            "required": True,
                            "when": {"fieldRef": "x", "operator": "eq", "value": 1},
                        },
                        {
                            "name": "seo",
                            "type": "fields",
                            "fields": [{"name": "title", "type": "string", "required": True}],
                        },
                    ],
                },
                {"name": "note", "fields": [{"name": "source", "type": "string", "required": True}]},
                {"name": "default", "fields": [{"name": "title", "type": "string", "required": True}]},
            ],
        }
    ),
    "pages/_posts/2026-01-02-thin.md": "---\ntitle: Thin\nsummary: ''\n---\nBody\n",
    "pages/_posts/2026-01-04-note.md": "---\ntitle: N\ntype: note\n---\n",
}


def test_required_fields_come_from_the_sites_own_content_types(tmp_path):
    report = doctor.run(site(tmp_path, TYPED))
    missing = sorted(
        (f["file"], f["rule"], f["evidence"]) for f in report.findings if f["rule"].startswith("missing-key:")
    )
    assert missing == [
        ("pages/_posts/2026-01-01-hello.md", "missing-key:seo.title", "post requires seo.title"),
        ("pages/_posts/2026-01-01-hello.md", "missing-key:summary", "post requires summary"),
        ("pages/_posts/2026-01-02-thin.md", "missing-key:seo.title", "post requires seo.title"),
        ("pages/_posts/2026-01-02-thin.md", "missing-key:summary", "post requires summary"),
        ("pages/_posts/2026-01-04-note.md", "missing-key:source", "note requires source"),
    ]
    assert all(f["severity"] == "warning" for f in report.findings) and report.content_types == 3


def test_validation_off_means_no_required_fields(tmp_path):
    data = json.loads(TYPED["zer0.json"])
    data["validation"] = {"enabled": False}
    report = doctor.run(site(tmp_path, {**TYPED, "zer0.json": json.dumps(data)}))
    assert not [f for f in report.findings if f["rule"].startswith("missing-key:")]


def test_zer0_json_is_checked_against_the_platform_schema(tmp_path):
    data = {
        "$schema": "x",
        "contentFolders": [{"path": "[[workspace]]/pages/_posts"}],
        "contentTypes": [{"fields": []}],
    }
    report = doctor.run(site(tmp_path, {**ALIGNED, "zer0.json": json.dumps(data)}))
    found = [f for f in report.findings if f["rule"] == "zer0-json-schema"]
    assert (
        len(found) == 1
        and "contentTypes/0" in found[0]["evidence"]
        and "'name' is a required property" in found[0]["evidence"]
    )


# ── shape and command line ─────────────────────────────────────────────────


def test_findings_shape_and_fingerprint():
    found = doctor.finding("cms", "warning", "no-zer0-json", "no zer0.json", file="zer0.json")
    assert list(found) == ["check_id", "severity", "file", "line", "rule", "evidence", "fingerprint"]
    assert found["fingerprint"] == hashlib.sha1(b"cms|no-zer0-json|zer0.json|no zer0.json").hexdigest()[:12]


def test_command_line_formats_and_exit_codes(tmp_path):
    bad = site(tmp_path / "bad", aligned(**{"zer0.json": "not json"}))
    out = io.StringIO()
    assert doctor.main([str(bad), "--format", "findings"], stdout=out) == 1
    assert [json.loads(line)["rule"] for line in out.getvalue().splitlines()] == ["zer0-json-invalid"]
    out = io.StringIO()
    assert doctor.main([str(bad)], stdout=out) == 1
    assert "  cms           1 error(s), 0 warning(s)" in out.getvalue()
    assert out.getvalue().rstrip().endswith("result: 1 error(s), 0 warning(s)")
    assert doctor.main([str(site(tmp_path / "good", aligned()))], stdout=io.StringIO()) == 0
    with pytest.raises(SystemExit) as exited:
        doctor.main(["--format", "xml", str(tmp_path)])
    assert exited.value.code == 2


def test_the_distribution_check_as_the_lane_ported_it(tmp_path):
    """The Ruby doctor's `check_distribution` (test_doctor.rb) as the distribution lane's own tests ported it, over
    the doctor that runs it."""

    def findings(root):
        return [f for f in doctor.run(root, today=RECORDED_ON).findings if f["check_id"] == "distribution"]

    def site(block=None, **files):
        root = tmp_path / f"s{len(list(tmp_path.iterdir()))}"
        root.mkdir()
        zer0 = '{\n  // console dialect\n  "$schema": "https://example.com/zer0.schema.json",\n}\n'
        if block is not None:
            zer0 = zer0.replace('"$schema"', f'"distribution": {{ "linkedin": {block} }},\n  "$schema"')
        (root / "zer0.json").write_text(zer0)
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        return root

    def rules(found, severity=None):
        return sorted(f["rule"] for f in found if severity in (None, f["severity"]))

    valid = '{ "author": "urn:li:organization:1", "siteUrl": "https://example.test", "ledger": "log.json" }'
    assert findings(site(valid)) == [] and findings(site()) == []
    bad = findings(site('{ "author": "urn:li:company:1", "publishAllow": true }'))
    assert rules(bad, "error") == ["distribution-config-invalid"] and "distribution-config" in rules(bad, "warning")
    assert "distribution-ledger-unreadable" in rules(findings(site(valid, **{"log.json": "{ not json"})), "error")
    assert "distribution-config-invalid" in rules(
        findings(site('{ "author": "urn:li:person:x", "queue": "../outside" }')), "error"
    )
    vendored = findings(site(**{"scripts/features/linkedin/posts.py": "# publisher\n"}))
    assert [(f["severity"], f["file"], f["check_id"], len(f["fingerprint"])) for f in vendored] == [
        ("warning", "scripts/features/linkedin/posts.py", "distribution", 12)
    ]
