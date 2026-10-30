"""`manage.py aieo`: AIEO's CLI and root scripts on the platform — a file scored with no database, a URL audited
through the guarded fetcher, a list of sites audited together into AIEO's JSON layout and reports, a site crawled
into an offline snapshot, reports from AIEO's JSON results, the headless runner over Markdown picked by globs or a
git diff (its rewrites written to proposed/ for a person, never in place), and the prompt importer that keeps a
person's change unless told otherwise."""

import json
import re
import shutil
import subprocess
from io import StringIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from aieo.models import Audit, Pattern

from .conftest import at

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"


def run(*args) -> str:
    out = StringIO()
    call_command("aieo", *args, stdout=out, stderr=StringIO())
    return out.getvalue()


def test_a_file_is_scored_with_the_heuristics_and_no_database(db):
    printed = run("audit", str(FIXTURES / "article.md"))
    assert "Score: 52.0/100  Grade: D  [heuristic]" in printed and "Dimensions: aieo 52.0" in printed
    data = json.loads(run("audit", str(FIXTURES / "article.md"), "--json"))
    assert data["score"] == 52.0 and data["pattern_scores"]["faq_injection"]["detected"]
    assert not Audit.objects.exists()


def test_a_url_is_fetched_through_the_guard_and_ai_records_an_audit(db, fake, web):
    web.get(at("/")).respond(
        200, text="<h1>Backups</h1><p>Copies of a site.</p>", headers={"Content-Type": "text/html"}
    )
    web.get(at("/robots.txt")).respond(404)
    assert "Grade: F" in run("audit", "https://example.com/")
    from .conftest import answer, evaluation

    fake.script = [answer(evaluation(0.9, penalties=0))]
    printed = run("audit", "https://example.com/", "--ai")
    row = Audit.objects.get()
    assert row.origin == "cli" and row.scoring_method == "ai" and row.score == 90.0 and "Score: 90.0/100" in printed
    with pytest.raises(CommandError):
        run("audit", "http://10.0.0.5/")


def test_a_list_of_sites_is_audited_together_into_aieos_layout_and_reports(db, fake, web, tmp_path):
    web.get(at("/robots.txt")).respond(404)
    web.get(at("/")).respond(
        200, text="<h1>Home</h1><p>We back up sites. Is it enough?</p>", headers={"Content-Type": "text/html"}
    )
    web.get(at("/gone")).respond(404)
    sites = tmp_path / "sites.txt"
    sites.write_text("https://example.com/\n# a comment\nhttps://example.com/gone\n")
    printed = run("batch-audit", "--sites", str(sites), "--heuristic", "--output", str(tmp_path / "out"))
    assert "batch " in printed and "HTTP 404" in printed
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert [(s["url"], s["status"]) for s in summary] == [
        ("https://example.com/", "success"),
        ("https://example.com/gone", "error"),
    ]
    site = json.loads((tmp_path / "out" / "example_com" / "example_com.json").read_text())
    assert site["grade"] and site["pattern_scores"] and site["scoring_method"] == "heuristic"
    assert "# AIEO Audit Report: example.com" in (tmp_path / "out" / "example_com" / "example_com.md").read_text()
    assert "| Failed | 1 |" in (tmp_path / "out" / "REPORT.md").read_text()


def test_a_site_is_crawled_into_an_offline_snapshot(db, web, tmp_path):
    web.get(at("/robots.txt")).respond(404)
    web.get(at("/sitemap.xml")).respond(404)
    for feed in ("/feed.xml", "/atom.xml", "/feed/", "/rss.xml"):
        web.get(at(feed)).respond(404)
    page = '<html><head><title>{0}</title></head><body><h1>{0}</h1><a href="/a/">a</a></body></html>'
    web.get(at("/")).respond(200, text=page.format("Home"), headers={"Content-Type": "text/html"})
    web.get(at("/a/")).respond(200, text=page.format("A"), headers={"Content-Type": "text/html"})
    printed = run("crawl", "https://example.com/", "--output", str(tmp_path))
    assert "Discovery: links  Pages: 2 (2 ok)" in printed
    snapshot = json.loads((tmp_path / "snapshot.json").read_text())
    assert [p["title"] for p in snapshot["pages"]] == ["Home", "A"] and snapshot["robots"] == "absent"
    assert (
        "## Home" in (tmp_path / "snapshot.md").read_text()
        and "https://example.com/a/" in (tmp_path / "snapshot.txt").read_text()
    )


def test_reports_are_written_from_aieos_json_results_as_aieo_wrote_them(db, tmp_path):
    run("report", "--input", str(settings.REPO_ROOT / "apps" / "aieo" / "reports"), "--output", str(tmp_path))
    golden = HERE / "golden" / "reports"
    stamp = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")  # when it was written: now here, noon in the recording
    for written in [tmp_path / "REPORT.md", tmp_path / "soprisaccounting_com" / "soprisaccounting_com.md"]:
        assert stamp.sub("…", written.read_text()) == stamp.sub("…", (golden / written.name).read_text())
    with pytest.raises(CommandError):
        run("report")


def _repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "node_modules").mkdir()
    shutil.copy(FIXTURES / "article.md", root / "docs" / "article.md")
    shutil.copy(FIXTURES / "thin.md", root / "README.md")
    (root / "node_modules" / "skip.md").write_text("# Skipped")
    return root


def test_the_headless_runner_scores_markdown_picked_by_globs_and_writes_its_report(db, tmp_path):
    root, out = _repo(tmp_path), tmp_path / "artifacts"
    run("run", "--root", str(root), "--output-dir", str(out))
    report = (out / "REPORT.md").read_text()
    assert "| `docs/article.md` | success | 52.0 | D |" in report and "README.md" in report and "skip.md" not in report
    result = json.loads((out / "results" / "docs__article.md.json").read_text())
    assert result["score"] == 52.0 and result["gaps"]
    dry = run("run", "--root", str(root), "--glob", "docs/*.md", "--dry-run")
    assert [r["file"] for r in json.loads(dry)] == ["docs/article.md"]


def test_the_headless_runner_follows_a_git_diff_and_proposes_rewrites_never_in_place(db, fake, tmp_path):
    root, out = _repo(tmp_path), tmp_path / "artifacts"
    git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
    subprocess.run([*git[:1], "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run([*git, "-C", str(root), "add", "."], check=True)
    subprocess.run([*git, "-C", str(root), "commit", "-qm", "base"], check=True)
    (root / "docs" / "new.md").write_text("# New\n\nA new page about backups.\n")
    subprocess.run([*git, "-C", str(root), "add", "."], check=True)
    subprocess.run([*git, "-C", str(root), "commit", "-qm", "new"], check=True)
    fake.script = [{"text": "# New\n\nA new page about backups, defined and dated (2026)."}]
    run(
        "run",
        "--root",
        str(root),
        "--git-diff-base",
        "HEAD~1",
        "--mode",
        "enhance",
        "--write-proposed",
        "--output-dir",
        str(out),
    )
    proposed = out / "proposed" / "docs" / "new.md"
    assert proposed.read_text() == "# New\n\nA new page about backups, defined and dated (2026)."
    assert (root / "docs" / "new.md").read_text() == "# New\n\nA new page about backups.\n"  # never in place
    result = json.loads((out / "results" / "docs__new.md.json").read_text())
    assert result["score_after"] >= result["score_before"] and "optimized_content" not in result
    assert "| `docs/new.md` | success |" in (out / "REPORT.md").read_text()


def test_the_prompt_importer_keeps_a_persons_change_unless_forced(db, tmp_path):
    copy = tmp_path / "prompts"
    shutil.copytree(settings.BASE_DIR / "aieo" / "data" / "prompts", copy)
    path = copy / "patterns" / "faq_injection.md"
    path.write_text(path.read_text().replace("weight: 15", "weight: 25"))
    assert "0 created, 1 updated, 0 conflicts" in run("import-prompts", "--path", str(copy))
    assert Pattern.objects.get(name="faq_injection").weight == 25
    Pattern.objects.filter(name="faq_injection").update(weight=7)  # a person's change here
    path.write_text(path.read_text().replace("weight: 25", "weight: 30"))
    assert "1 conflicts" in run("import-prompts", "--path", str(copy))
    assert Pattern.objects.get(name="faq_injection").weight == 7
    assert "1 updated" in run("import-prompts", "--path", str(copy), "--force")
    assert Pattern.objects.get(name="faq_injection").weight == 30
