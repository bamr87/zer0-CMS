"""`manage.py aieo <command>`: AIEO's CLI and root scripts on the platform (aieo/services.py), with their output:

    aieo audit FILE|URL [--format F] [--json] [--ai] [--user U]
        a file's or a page's citability score now (`aieo audit`, run_audit.py for one URL); the heuristics need no
        database, --ai records an audit and has the evaluator score it, as --user
    aieo batch-audit [--sites sites.txt] [--output DIR] [--heuristic] [--user U]
        every site of a list, audited together (run_audit.py, mcp_client_audit.py); with --output, AIEO's per-site
        JSON, summary.json and reports
    aieo crawl URL [--max-pages N] [--output DIR]
        a site crawled into an offline snapshot — snapshot.json, snapshot.md, snapshot.txt (crawl_site.py)
    aieo report (--audit ID… | --batch KEY | --site ID | --input DIR) [--output DIR]
        the per-site reports and REPORT.md (generate_reports.py) from audits here, or from AIEO's JSON results
    aieo run [--root DIR] [--glob P…] [--git-diff-base REF [--intersect-globs]] [--mode M] [--write-proposed] …
        the headless CI runner (tools/aieo_runner): Markdown selected by globs or a git diff, scored (audit-only,
        no database) or optimized (enhance, expand) into proposed/ for a person to review — never in place
    aieo import-reports [--path DIR] [--user U]
        AIEO's reports/ as audit history (idempotent)
    aieo import-prompts [--path DIR] [--force]
        a prompts directory in AIEO's layout into the pattern library and the bundled assistants

Every URL is fetched through the research library's guarded fetcher. A run a command starts (--ai, batch-audit,
run's enhance and expand) executes here, in this process, as the AI layer's runs do in a worker — so those commands
need a migrated database with the agents synced (`manage.py sync_agents --publish`).
"""

import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from wagtail.models import Site

from agents.models import AgentRun
from agents.principals import ensure_legacy_import_user
from agents.runner import execute
from ai.services import stable_id
from aieo import crawl, parser, prompts, reports, scoring, services
from aieo.models import Audit, library
from ops.errors import ApiError
from research import fetch

IGNORED = {".git", "node_modules", "venv", ".venv", "__pycache__", ".tox", "dist", "build", ".eggs"}
REPO = Path(settings.BASE_DIR).parent


def _patterns() -> list[dict]:
    """The library's patterns, or the bundled files where there is no database to read (the CI runner)."""
    try:
        return library()
    except DatabaseError:
        return list(scoring.bundled_patterns())


@contextmanager
def _here():
    """Runs a command starts execute here, in this process: queued in one transaction (so each run is linked to what
    it fills before it starts), run eagerly when it commits — and any still waiting after (inside a caller's own
    transaction, a test's) run at the end."""
    from config.celery import app

    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
    started = []
    with transaction.atomic():
        yield started
    for run in AgentRun.objects.filter(pk__in=[r.pk for r in started]):
        if not run.is_final:
            execute(run)


def _read(target: str, fmt: str) -> tuple[str, str]:
    if target.startswith(("http://", "https://")):
        try:
            got = fetch.get(target)
        except fetch.FetchError as e:
            raise CommandError(str(e)) from e
        if got.status >= 400:
            raise CommandError(f"{target} answered HTTP {got.status}")
        html = got.content_type.split(";", 1)[0].strip().lower() in crawl.HTML
        return got.text(), "html" if html else fmt
    path = Path(target)
    if not path.is_file():
        raise CommandError(f"no file {target}")
    return path.read_text(encoding="utf-8"), "html" if path.suffix.lower() in (".html", ".htm") else fmt


class Command(BaseCommand):
    help = "AIEO's commands: audit, batch-audit, crawl, report, run, import-reports, import-prompts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", default=None, help="Who audits (default: the first superuser, else legacy:import)."
        )
        sub = parser.add_subparsers(dest="command", required=True)
        audit = sub.add_parser("audit")
        audit.add_argument("target", help="A Markdown or HTML file, or an http(s) URL.")
        audit.add_argument("--format", choices=["markdown", "html"], default="markdown")
        audit.add_argument("--json", action="store_true")
        audit.add_argument("--ai", action="store_true", help="Record an audit and have the evaluator score it.")
        batch = sub.add_parser("batch-audit")
        batch.add_argument("--sites", default=str(REPO / "apps" / "aieo" / "sites.txt"))
        batch.add_argument("--output", default=None)
        batch.add_argument("--heuristic", action="store_true", help="Score with the heuristics only.")
        snapshot = sub.add_parser("crawl")
        snapshot.add_argument("url")
        snapshot.add_argument("--max-pages", type=int, default=25)
        snapshot.add_argument("--output", default="aieo-snapshot")
        report = sub.add_parser("report")
        report.add_argument("--audit", action="append", default=[], help="An audit's id (repeatable).")
        report.add_argument("--batch", default="")
        report.add_argument("--site", type=int, default=None)
        report.add_argument("--input", default=None, help="A directory of AIEO's JSON results instead.")
        report.add_argument("--output", default="aieo-reports")
        run = sub.add_parser("run")
        run.add_argument("--root", default=".")
        run.add_argument("--glob", dest="globs", action="append", default=[])
        run.add_argument("--git-diff-base", default=None)
        run.add_argument("--intersect-globs", action="store_true")
        run.add_argument("--ignore-dir", dest="ignore_dirs", action="append", default=[])
        run.add_argument("--mode", choices=["audit-only", "enhance", "expand"], default="audit-only")
        run.add_argument("--style", choices=["preserve", "aggressive"], default="preserve")
        run.add_argument("--output-dir", default="aieo-artifacts")
        run.add_argument("--write-proposed", action="store_true")
        run.add_argument("--max-files", type=int, default=0)
        run.add_argument("--dry-run", action="store_true")
        imported = sub.add_parser("import-reports")
        imported.add_argument("--path", default=str(REPO / "apps" / "aieo" / "reports"))
        imported.add_argument("--visibility", choices=["private", "shared"], default="shared")
        loaded = sub.add_parser("import-prompts")
        loaded.add_argument("--path", default=str(prompts.DATA / "prompts"))
        loaded.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        command = options["command"].replace("-", "_")
        try:
            getattr(self, f"_{command}")(options)
        except ApiError as e:
            raise CommandError(e.message) from e

    def _user(self, options):
        name = options.get("user")
        users = get_user_model().objects
        if name:
            found = users.filter(username=name).first()
            if found is None:
                raise CommandError(f"no user {name!r}")
            return found
        return users.filter(is_superuser=True, is_active=True).order_by("pk").first() or ensure_legacy_import_user()

    # ── audit ───────────────────────────────────────────────────────────────

    def _audit(self, options):
        content, fmt = _read(options["target"], options["format"])
        if options["ai"]:
            kind = Audit.URL if options["target"].startswith(("http://", "https://")) else Audit.TEXT
            where = {"url": options["target"]} if kind == Audit.URL else {"content": content, "format": fmt}
            with _here() as started:
                row = services.audit(self._user(options), kind=kind, origin="cli", trigger="manual", **where)
                started.append(row.run)
            row.refresh_from_db()
            if row.status != Audit.READY:
                raise CommandError(f"the audit {row.status}: {row.error}")
            result = {**row.result, "score": row.score, "grade": row.grade, "audit": str(row.public_id)}
        else:
            result = scoring.heuristic(parser.parse(content, fmt), _patterns())
        if options["json"]:
            self.stdout.write(json.dumps(result, indent=2, default=str))
            return
        self.stdout.write(f"Score: {result['score']}/100  Grade: {result['grade']}  [{result['scoring_method']}]")
        self.stdout.write(f"Word count: {result['word_count']}")
        dims = result.get("dimensions", {})
        self.stdout.write("Dimensions: " + ", ".join(f"{k} {v}" for k, v in dims.items()))
        for gap in result.get("gaps", [])[:5]:
            self.stdout.write(f"  - [{gap['severity']}] {gap['category']}: {gap['description'][:100]}")

    # ── batch-audit ─────────────────────────────────────────────────────────

    def _batch_audit(self, options):
        sites = Path(options["sites"])
        if not sites.is_file():
            raise CommandError(f"no sites file {sites}")
        method = Audit.HEURISTIC if options["heuristic"] else Audit.AI
        with _here() as started:
            made = services.batch_audit(
                self._user(options), sites.read_text().splitlines(), method=method, origin="cli", trigger="manual"
            )
            started += [row.run for row in made]
        rows = [Audit.objects.get(pk=row.pk) for row in made]
        self.stdout.write(f"{'URL':<44} {'Score':>6} {'Grade':>6} {'Method':>10}")
        for row in rows:
            score = f"{row.score:>6}" if row.score is not None else f"{'ERR':>6}"
            self.stdout.write(
                f"{row.url[:43]:<44} {score} {row.grade or '--':>6} {row.scoring_method or row.error[:30]:>10}"
            )
        self.stdout.write(f"batch {made[0].batch}")
        if options["output"]:
            out = Path(options["output"])
            summary = []
            for row in rows:
                data = reports.data_of(row)
                item = {k: v for k, v in data.items() if not k.startswith("_")}
                folder = out / data["_name"]
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{data['_name']}.json").write_text(json.dumps(item, indent=2, default=str))
                summary.append(
                    {
                        "url": row.url,
                        "status": item["status"],
                        "score": row.score,
                        "grade": row.grade or None,
                        "word_count": item.get("word_count"),
                        "gap_count": len(item.get("gaps", [])),
                        "method": row.scoring_method or None,
                        "error": row.error or None,
                    }
                )
            (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
            reports.write(rows, out, timezone.localtime())
            self.stdout.write(f"Results saved to: {out}")

    # ── crawl ───────────────────────────────────────────────────────────────

    def _crawl(self, options):
        found = crawl.crawl(options["url"], max_pages=max(1, options["max_pages"]))
        out = Path(options["output"])
        out.mkdir(parents=True, exist_ok=True)
        pages = []
        for page in found.pages:
            parsed = parser.parse(page.html, "html") if page.html else None
            pages.append(
                {
                    "url": page.url,
                    "title": page.title,
                    "found_by": page.source,
                    "status": page.status,
                    "error": page.error,
                    "word_count": parsed["word_count"] if parsed else 0,
                    "headers": parsed["headers"] if parsed else [],
                    "text": parsed["text"] if parsed else "",
                }
            )
        snapshot = {
            "base_url": options["url"],
            "crawled_at": timezone.now().isoformat(),
            "robots": found.robots,
            "discovery": found.discovery,
            "link_map": crawl.link_map(found.pages, options["url"]),
            "pages": pages,
        }
        (out / "snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
        sections = [f"## {p['title'] or p['url']}\n\n<{p['url']}>\n\n{p['text'] or p['error']}" for p in pages]
        (out / "snapshot.md").write_text(f"# Snapshot of {options['url']}\n\n" + "\n\n".join(sections) + "\n")
        (out / "snapshot.txt").write_text("\n\n".join(f"{p['url']}\n{p['text'] or p['error']}" for p in pages) + "\n")
        ok = sum(1 for p in pages if not p["error"])
        self.stdout.write(
            f"Site: {options['url']}  Discovery: {found.discovery['source']}  Pages: {len(pages)} ({ok} ok)"
        )
        self.stdout.write(f"Output: {out}")

    # ── report ──────────────────────────────────────────────────────────────

    def _report(self, options):
        out, now = Path(options["output"]), timezone.localtime()
        if options["input"]:
            source = Path(options["input"])
            files = sorted(p for p in source.glob("*/*.json") if p.name != "summary.json") or sorted(
                p for p in source.glob("*.json") if p.name != "summary.json"
            )
            data = []
            for path in files:
                item = json.loads(path.read_text())
                item["_name"] = path.stem
                data.append(item)
            if not data:
                raise CommandError(f"no JSON results in {source}")
            for item in data:
                (out / item["_name"]).mkdir(parents=True, exist_ok=True)
                (out / item["_name"] / f"{item['_name']}.md").write_text(reports.site_report(item, now))
            (out / "REPORT.md").write_text(reports.summary_report(data, now))
            self.stdout.write(f"{len(data)} reports and REPORT.md written to {out}")
            return
        rows = Audit.objects.exclude(status__in=(Audit.PENDING, Audit.RUNNING))
        if options["audit"]:
            rows = rows.filter(public_id__in=options["audit"])
        elif options["batch"]:
            rows = rows.filter(batch=options["batch"])
        elif options["site"]:
            site = Site.objects.filter(pk=options["site"]).first()
            if site is None:
                raise CommandError(f"no site {options['site']}")
            rows = rows.filter(site=site)
        else:
            raise CommandError("name the audits: --audit, --batch, --site, or --input")
        if not rows.exists():
            raise CommandError("no finished audits match")
        written = reports.write(list(rows), out, now)
        self.stdout.write(f"{len(written) - 1} reports and REPORT.md written to {out}")

    # ── the headless runner ─────────────────────────────────────────────────

    def _files(self, options) -> list[Path]:
        root = Path(options["root"]).resolve()
        ignored = IGNORED | set(options["ignore_dirs"])

        def kept(path: Path) -> bool:
            try:
                parts = path.resolve().relative_to(root).parts
            except ValueError:
                return False
            return path.is_file() and path.suffix.lower() == ".md" and not set(parts) & ignored

        globbed = {p.resolve() for pattern in options["globs"] or ["**/*.md"] for p in root.glob(pattern) if kept(p)}
        if options["git_diff_base"]:
            done = subprocess.run(
                ["git", "diff", "--name-only", f"{options['git_diff_base']}...HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            if done.returncode != 0:
                raise CommandError(f"git diff failed (exit {done.returncode}): {done.stderr.strip() or done.stdout}")
            changed = {(root / name).resolve() for name in done.stdout.splitlines() if name.strip().endswith(".md")}
            changed = {p for p in changed if kept(p)}
            files = (globbed & changed) if options["intersect_globs"] else changed
        else:
            files = globbed
        files = sorted(files, key=str)
        return files[: options["max_files"]] if options["max_files"] > 0 else files

    def _run(self, options):
        root = Path(options["root"]).resolve()
        files = self._files(options)
        if not files:
            raise CommandError("No markdown files matched.")
        patterns = _patterns()
        mode = options["mode"]
        user = self._user(options) if mode != "audit-only" else None
        out = Path(options["output_dir"])
        rows, failed = [], False
        for path in files:
            rel = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
            record = {"status": "success", "file": rel}
            try:
                score = scoring.heuristic(parser.parse(text, "markdown"), patterns)
                keep = ("score", "grade", "word_count", "scoring_method", "content_type", "overall_assessment")
                record |= {key: score.get(key) for key in keep}
                record |= {key: score[key] for key in ("pattern_scores", "gaps", "anti_pattern_penalties")}
                if mode != "audit-only":
                    with _here() as started:
                        run = services.rewrite(
                            user,
                            mode="expand" if mode == "expand" else "optimize",
                            content=text,
                            style=options["style"],
                            trigger="manual",
                        )
                        started.append(run)
                    run.refresh_from_db()
                    if run.status != run.SUCCEEDED:
                        raise RuntimeError(run.error or run.status)
                    record |= {key: run.output.get(key) for key in ("score_before", "score_after", "uplift")}
                    record["optimized_content"] = run.output.get("markdown", "")
            except Exception as e:  # noqa: BLE001 — one file that fails is reported with the rest, never the end of the run
                record = {"status": "error", "file": rel, "error": str(e)}
                failed = True
            rows.append(record)
            if not options["dry_run"]:
                target = out / "results" / f"{rel.replace('/', '__')}.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps({k: v for k, v in record.items() if k != "optimized_content"}, indent=2, default=str)
                )
                if options["write_proposed"] and record.get("optimized_content"):
                    proposed = out / "proposed" / rel
                    proposed.parent.mkdir(parents=True, exist_ok=True)
                    proposed.write_text(record["optimized_content"], encoding="utf-8")
            if record["status"] != "success":
                self.stderr.write(f"[error] {rel}: {record['error']}")
        summary = [
            {
                "file": r["file"],
                "status": r["status"],
                "score": r.get("score"),
                "grade": r.get("grade"),
                "gap_count": len(r.get("gaps") or []),
                "method": r.get("scoring_method"),
                "error": r.get("error"),
            }
            for r in rows
        ]
        if options["dry_run"]:
            self.stdout.write(json.dumps(summary, indent=2, default=str))
        else:
            out.mkdir(parents=True, exist_ok=True)
            (out / "REPORT.md").write_text(runner_report(summary), encoding="utf-8")
            self.stderr.write(f"Wrote REPORT.md and results under {out.resolve()}")
        if failed:
            sys.exit(1)

    # ── importers ───────────────────────────────────────────────────────────

    def _import_reports(self, options):
        source = Path(options["path"])
        files = sorted(p for p in source.glob("*/*.json") if p.name != "summary.json")
        if not files:
            raise CommandError(f"no AIEO results in {source}")
        user, made, kept = self._user(options), 0, 0
        for path in files:
            data = json.loads(path.read_text())
            url, stamp = data.get("url", ""), data.get("timestamp", "")
            when = parse_datetime(stamp) if stamp else None
            if when is not None and timezone.is_naive(when):
                when = timezone.make_aware(when, UTC)
            ok = data.get("status") == "success"
            method = data.get("scoring_method") or ""
            result = {k: v for k, v in data.items() if k not in ("url", "status", "score", "grade", "error")}
            values = {
                "owner": user,
                "visibility": options["visibility"],
                "kind": Audit.URL,
                "url": url,
                "method": Audit.AI if method == "ai" else Audit.HEURISTIC,
                "status": Audit.READY if ok else Audit.FAILED,
                "score": data.get("score") if ok else None,
                "grade": (data.get("grade") or "") if ok else "",
                "scoring_method": method,
                "result": result,
                "error": data.get("error") or "",
                "origin": "import",
                "batch": "aieo-reports",
                "audited_at": when,
            }
            row, created = Audit.objects.update_or_create(
                public_id=stable_id("aieo-report", f"{url}@{stamp}"), defaults=values
            )
            made, kept = made + created, kept + (not created)
        self.stdout.write(f"{made} audits imported, {kept} already here (batch aieo-reports)")

    def _import_prompts(self, options):
        directory = Path(options["path"])
        if not (directory / "patterns").is_dir():
            raise CommandError(f"{directory} is not a prompts directory (it has no patterns/)")
        report = prompts.seed(directory=directory, update=True, force=options["force"])
        self.stdout.write(
            f"{len(report.created)} created, {len(report.updated)} updated, {len(report.conflicts)} conflicts"
        )
        for conflict in report.conflicts:
            self.stdout.write(f"  conflict: {conflict}")


def runner_report(rows: list[dict]) -> str:
    """REPORT.md of the headless runner (AIEO's `tools/aieo_runner/report.py`)."""
    lines = [
        "# AIEO markdown report",
        "",
        f"_Generated: {datetime.now(UTC).isoformat()}_",
        "",
        "| File | Status | Score | Grade | Gaps | Method | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        notes = str(r.get("error") or "").replace("|", "\\|")[:200]
        score = r["score"] if r.get("score") is not None else ""
        lines.append(
            f"| `{r['file']}` | {r['status']} | {score} | {r.get('grade') or ''} | {r['gap_count']} | {r.get('method') or ''} | {notes} |"
        )
    return "\n".join([*lines, ""])
