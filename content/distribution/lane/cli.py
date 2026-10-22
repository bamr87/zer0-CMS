"""`manage.py linkedin COMMAND` — the LinkedIn lane from a terminal and from CI
(the reusable `zer0-linkedin.yml`), over a site's own files.

Exit status: 0 when the command did what it says, 1 when something was refused
or failed (a blocker, a LinkedIn error, a bad configuration), 2 on bad usage.
`preview` and a rehearsed `publish` exit 1 when a draft has a blocker that
arming would not lift, so a dry run in CI fails on a guard error rather than
passing silently. Credentials come from the environment only.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from ..ledger import LedgerError
from ..linkedin import Client, Error, oauth, plan, posts
from ..linkedin.client import send
from .pipeline import Pipeline
from .site import ARM_VARIABLE, Config, ConfigError

USAGE = """manage.py linkedin — LinkedIn distribution for a site's own files

Usage: manage.py linkedin COMMAND [--site PATH] [--json] [options]

  status [--check] [--warn-days N]   settings, queue and ledger; --check asks LinkedIn about the token
  plan                               every LinkedIn call this lane can make, and nothing else
  sources [--all]                    pages that can be shared (--all includes shared ones)
  queue                              drafts and their status
  draft SOURCE [--commentary TEXT | --commentary-file FILE]
  draft --update --slug SLUG (--message TEXT | --message-file FILE)
                                     write a pending draft
  approve DRAFT                      pending -> approved: a person's decision
  preview [DRAFT]                    the exact payload, the guard and every blocker; no network
  publish [DRAFT] [--live]           rehearse; with --live and ZER0_LINKEDIN_PUBLISH=1, post
  publish DRAFT --live --force       post past a guard error, a ledger entry or an unconfirmed attempt
  record DRAFT URN                   record a post a person found on LinkedIn
  posts [--count N]                  the author's own recent posts
  verify URN                         read one post back
  organizations                      pages the token's member may post to
  stats [--write]                    aggregate statistics for published posts
  connect [--port N] [--redirect-uri URL] [--write-env FILE | --print-token]
                                     three-legged OAuth (state + PKCE) through a loopback callback

Credentials come from the environment only: LINKEDIN_ACCESS_TOKEN, and optionally
LINKEDIN_REFRESH_TOKEN with LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET.
Settings: zer0.json "distribution": { "linkedin": { ... } } (docs/DISTRIBUTION.md).
"""

COMMANDS = (
    "status",
    "plan",
    "sources",
    "queue",
    "draft",
    "approve",
    "preview",
    "publish",
    "record",
    "posts",
    "verify",
    "organizations",
    "stats",
    "connect",
)


class Usage(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def parser() -> Parser:
    p = Parser(prog="manage.py linkedin", add_help=False)
    p.add_argument("command", nargs="?")
    p.add_argument("args", nargs="*")
    p.add_argument("--site", default=".")
    p.add_argument("--json", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--warn-days", type=int, default=7)
    p.add_argument("--all", action="store_true")
    p.add_argument("--commentary")
    p.add_argument("--commentary-file")
    p.add_argument("--update", action="store_true")
    p.add_argument("--slug")
    p.add_argument("--message")
    p.add_argument("--message-file")
    p.add_argument("--live", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--write", action="store_true")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--redirect-uri")
    p.add_argument("--write-env")
    p.add_argument("--print-token", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    return p


def main(argv, *, out=sys.stdout, err=sys.stderr, env=None, transport=send, sleeper=time.sleep) -> int:
    try:
        opts = parser().parse_intermixed_args(argv)  # a draft id may come after the options, as CI passes it
    except Usage as e:
        err.write(f"error: {e}\n\n{USAGE}")
        return 2
    if opts.help or opts.command in (None, "help"):
        out.write(USAGE)
        return 0
    if opts.command not in COMMANDS:
        err.write(f"error: unknown command {opts.command}\n\n{USAGE}")
        return 2
    try:
        for key in ("commentary", "message"):
            if path := getattr(opts, f"{key}_file"):
                setattr(opts, key, Path(path).read_text(encoding="utf-8"))
        config = Config(opts.site, env=os.environ if env is None else env)
        runner = Runner(Pipeline(config, transport=transport, sleeper=sleeper), opts, out, err)
        return getattr(runner, opts.command)()
    except (ConfigError, LedgerError, ValueError, KeyError, OSError) as e:
        err.write(f"error: {e}\n")
        return 1
    except Error as e:
        err.write(f"LinkedIn: {e}\n")
        return 1


class Runner:
    """One method per command, so `main` dispatches by name and a test drives a command without a subprocess."""

    def __init__(self, pipeline: Pipeline, opts, out, err):
        self.pipeline, self.config, self.opts, self.out, self.err = pipeline, pipeline.config, opts, out, err
        self.args = list(opts.args)

    def emit(self, data):
        self.out.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def line(self, text=""):
        self.out.write(f"{text}\n")

    def arg(self, name):
        if not self.args:
            raise ValueError(f"missing {name}")
        return self.args.pop(0)

    # ── commands ─────────────────────────────────────────────────────────────
    def status(self):
        report = self.pipeline.status(check=self.opts.check, warn_days=self.opts.warn_days)
        if self.opts.json:
            self.emit(report)
        else:
            self.print_status(report)
        failed = report["errors"] or (self.opts.check and not report["token"].get("ok"))
        return 1 if failed else 0

    def plan(self):
        if self.opts.json:
            self.emit({"calls": [c.as_dict() for c in plan.CALLS]})
        else:
            self.line(plan.describe())
        return 0

    def sources(self):
        found = [s for s in self.pipeline.sources() if self.opts.all or not s.urn]
        if self.opts.json:
            self.emit([s.as_dict() for s in found])
        elif not found:
            self.line("No shareable pages." if self.opts.all else "Every shareable page has been shared.")
        for source in [] if self.opts.json else found:
            self.line(f"{'shared  ' if source.urn else '        '} {source.entry.relative}")
            self.line(f"          {source.url}{f'  ({source.urn})' if source.urn else ''}")
        return 0

    def queue(self):
        drafts = self.pipeline.drafts()
        rows = [
            {"id": d.id, "path": d.relative, "status": d.status, "type": d.type, "source": d.text("source")}
            for d in drafts
        ]
        if self.opts.json:
            self.emit(rows)
        elif not drafts:
            self.line(f"The queue ({self.config.queue}) is empty.")
        for row in [] if self.opts.json else rows:
            source = f"  <- {row['source']}" if row["source"] else ""
            self.line(f"{row['status'].ljust(10)} {row['type'].ljust(8)} {row['path']}{source}")
        return 0

    def draft(self):
        if self.opts.update:
            if not (self.opts.slug and self.opts.message):
                raise ValueError("an update needs --slug and --message (or --message-file)")
            created = self.pipeline.compose_update(self.opts.message, slug=self.opts.slug)
        else:
            created = self.pipeline.compose(self.arg("SOURCE (or --update)"), commentary=self.opts.commentary)
        preview = self.pipeline.preview(created)
        if self.opts.json:
            self.emit({"created": created.relative, "preview": preview.as_dict(self.config.root)})
        else:
            self.line(f"wrote {created.relative} (status: pending — a person approves it)")
            self.print_preview(preview)
        return 0

    def approve(self):
        return self.report(self.pipeline.approve(self.pipeline.draft(self.arg("DRAFT"))))

    def preview(self):
        if self.args:
            drafts = [self.pipeline.draft(self.args.pop(0))]
        else:
            drafts = [d for d in self.pipeline.drafts() if d.status != "published"]
        previews = [self.pipeline.preview(d) for d in drafts]
        if self.opts.json:
            self.emit([p.as_dict(self.config.root) for p in previews])
        elif not previews:
            self.line(f"Nothing to preview: no unpublished drafts in {self.config.queue}.")
        for preview in [] if self.opts.json else previews:
            self.print_preview(preview)
        return 1 if any(p.problems for p in previews) else 0

    def publish(self):
        live, force = self.opts.live, self.opts.force
        if self.args:
            outcomes = [self.pipeline.publish(self.pipeline.draft(self.args.pop(0)), live=live, force=force)]
        else:
            outcomes = self.pipeline.publish_queue(live=live, force=force)
        if self.opts.json:
            self.emit(
                [
                    {**o.as_dict(), "preview": o.preview.as_dict(self.config.root) if o.preview else None}
                    for o in outcomes
                ]
            )
        elif not outcomes:
            self.line(
                f"Nothing to publish: no draft in {self.config.queue} has an accepted status "
                f"({', '.join(self.config.accept_statuses)})."
            )
        for outcome in [] if self.opts.json else outcomes:
            if outcome.preview and not live:
                self.print_preview(outcome.preview)
            self.print_outcome(outcome)
        return 0 if all(o.ok for o in outcomes) else 1

    def record(self):
        draft = self.pipeline.draft(self.arg("DRAFT"))
        return self.report(self.pipeline.record_post(draft, self.arg("URN")))

    def posts(self):
        found = self.pipeline.posts(count=self.opts.count)
        if self.opts.json:
            self.emit(found)
        for post in [] if self.opts.json else found:
            first = (str(post.get("commentary") or "").splitlines() or [""])[0].strip()[:90]
            self.line(f"{post.get('id')}  {first}")
        return 0

    def verify(self):
        self.emit(self.pipeline.verify(self.arg("URN")))
        return 0

    def organizations(self):
        pages = self.pipeline.organizations()
        if pages is None:
            self.err.write(
                "This token may not read page roles (it needs r_organization_admin or rw_organization_admin).\n"
            )
            return 1
        if self.opts.json:
            self.emit([{"urn": p.urn, "role": p.role, "name": p.name} for p in pages])
        elif not pages:
            self.line("The token's member holds no posting role on any page.")
        for page in [] if self.opts.json else pages:
            self.line(f"{page.urn.ljust(36)} {page.role.ljust(24)} {page.name or ''}")
        return 0

    def stats(self):
        result = self.pipeline.statistics(write=self.opts.write)
        if self.opts.json:
            self.emit(
                {
                    "performance": result["performance"],
                    "matched": result["matched"],
                    "skipped": result["skipped"],
                    "written": result["path"],
                }
            )
            return 0
        for path, counts in result["performance"].items():
            self.line(f"{path}\n  {', '.join(f'{k} {v}' for k, v in counts.items())}")
        if not result["performance"]:
            self.line("no published posts with statistics")
        if result["path"]:
            self.line(f"wrote {result['path']}")
        return 0

    def connect(self):
        credentials = self.config.credentials
        if not credentials.app:
            raise ConfigError("connect needs LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in the environment")
        redirect = self.opts.redirect_uri or f"http://127.0.0.1:{self.opts.port}/callback"
        target = urlsplit(redirect)
        if target.hostname not in ("127.0.0.1", "localhost", "::1") or not target.port:
            raise ValueError("--redirect-uri must be a loopback URL with a port, e.g. http://127.0.0.1:8765/callback")
        scopes = self.config.scopes or oauth.scopes_for(self.config.author_type)
        flow = self.pipeline.session().oauth()
        state, verifier = oauth.new_state(), oauth.new_verifier()
        url = flow.authorize_url(
            redirect_uri=redirect, state=state, scopes=scopes, code_challenge=oauth.challenge(verifier)
        )
        self.line(f"Add {redirect} to the app's authorized redirect URLs, then open this URL as the member who")
        self.line(f"owns the account (or administers the page) and approve:\n\n{url}\n")
        self.line(f"Waiting for LinkedIn's redirect on {redirect} …")
        params = wait_for_callback(target.port, target.path or "/callback")
        if params.get("error"):
            raise Error(f"LinkedIn answered {params['error']}: {params.get('error_description', '')}")
        if not oauth.state_matches(state, params.get("state")):
            raise Error("the callback's state does not match — refusing its code")
        token = flow.exchange(code=params.get("code", ""), redirect_uri=redirect, code_verifier=verifier)
        expires = token.expires_at.isoformat() if token.expires_at else "unknown"
        self.line(
            f"Connected. Scopes: {' '.join(token.scopes)}. Access token expires {expires} ({token.days_left()} days)."
        )
        if token.refresh_expires_at:
            self.line(f"Refresh token expires {token.refresh_expires_at.isoformat()}.")
        if "openid" in token.scopes:
            client = Client(token.access_token, api_version=self.config.api_version, transport=self.pipeline.transport)
            member = oauth.member(client)
            self.line(
                f"Member: {member['name']} — {member['urn']} (use it as distribution.linkedin.author for a profile)"
            )
        self.store_token(token)
        return 0

    # ── helpers ──────────────────────────────────────────────────────────────
    def store_token(self, token):
        if self.opts.write_env:
            path = (self.config.root / self.opts.write_env).resolve()
            ignored = (
                subprocess.run(
                    ["git", "-C", str(self.config.root), "check-ignore", "-q", str(path)], capture_output=True
                ).returncode
                == 0
            )
            if not ignored:
                raise ConfigError(f"{self.opts.write_env} is not ignored by git — refusing to write a token into it")
            write_env(
                path, {"LINKEDIN_ACCESS_TOKEN": token.access_token, "LINKEDIN_REFRESH_TOKEN": token.refresh_token}
            )
            self.line(f"Wrote the token to {self.opts.write_env} (mode 600).")
        elif self.opts.print_token:
            self.line(f"LINKEDIN_ACCESS_TOKEN={token.access_token}")
            if token.refresh_token:
                self.line(f"LINKEDIN_REFRESH_TOKEN={token.refresh_token}")
        else:
            self.line(
                "The token was not stored. Re-run with --write-env .env (a gitignored file) or --print-token "
                "to copy it into a secret."
            )

    def report(self, outcome):
        if self.opts.json:
            self.emit(outcome.as_dict())
        else:
            self.print_outcome(outcome)
        return 0 if outcome.ok else 1

    def print_outcome(self, outcome):
        self.line(f"{outcome.state.upper().ljust(9)} {outcome.draft.relative if outcome.draft else ''}")
        for message in outcome.messages:
            self.line(f"  {message}")

    def print_status(self, report):
        drafts = ", ".join(f"{v} {k}" for k, v in report["drafts"].items())
        held = [k for k, v in report["credentials"].items() if v]
        self.line(f"LinkedIn distribution — {report['site']}")
        self.line(f"  configured   {'yes (zer0.json distribution.linkedin)' if report['configured'] else 'no'}")
        kind = f" [{report['author_type']}]" if report["author_type"] else ""
        self.line(f"  author       {report['author'] or '(none)'}{kind}")
        self.line(f"  site URL     {report['site_url'] or '(none)'}")
        self.line(f"  API version  {report['api_version']} ({report['api_version_status']})")
        self.line(f"  queue        {report['queue']} — {drafts}")
        unreadable = "" if report["ledger_readable"] else " (UNREADABLE)"
        self.line(f"  ledger       {report['ledger']} — {report['published']} published{unreadable}")
        here = ", ".join(report["publishable_statuses"]) or "none"
        self.line(f"  accepts      {', '.join(report['accept_statuses'])} (in this run: {here})")
        self.line(f"  armed        {'yes' if report['armed'] else f'no ({ARM_VARIABLE} is not set)'}")
        self.line(f"  credentials  {', '.join(held) or '(none)'}")
        for message in report["errors"]:
            self.line(f"  ERROR    {message}")
        for message in report["warnings"]:
            self.line(f"  warning  {message}")
        token = report.get("token")
        if token:
            days = f" — {token['days_left']} day(s) left" if token.get("days_left") is not None else ""
            self.line(f"  token        {'ok' if token.get('ok') else 'NOT OK'}{days}")
            for message in token.get("problems", []):
                self.line(f"    problem  {message}")
            for message in token.get("notes", []):
                self.line(f"    note     {message}")

    def print_preview(self, preview):
        draft = preview.draft
        self.line(f"\n{draft.relative}  [{draft.status}, {preview.kind}]")
        self.line(f"  key        {preview.key or '(none)'}")
        if preview.entry:
            self.line(f"  source     {preview.entry.relative}")
        image = preview.thumbnail.relative_to(self.config.root).as_posix() if preview.thumbnail else "(none)"
        self.line(f"  image      {image}")
        self.line(f"  commentary {posts.commentary_length(preview.commentary)} chars as sent (LinkedIn folds at 140):")
        for text in preview.commentary.splitlines():
            self.line(f"    | {text}")
        for note in preview.notes:
            self.line(f"  note       {note}")
        for finding in preview.guard:
            if finding["level"] != "info":
                self.line(f"  {finding['level'].upper().ljust(10)} {finding['message']}")
        if not preview.blockers:
            self.line("  blockers   none")
        for blocker in preview.blockers:
            self.line(f"  blocked    {blocker.kind}: {blocker.message}")
        self.line(f"  payload    POST https://api.linkedin.com/rest/posts (LinkedIn-Version {self.config.api_version})")
        if preview.payload:
            for text in json.dumps(preview.payload, indent=2, ensure_ascii=False).splitlines():
                self.line(f"    {text}")


def write_env(path: Path, pairs: dict):
    pairs = {k: v for k, v in pairs.items() if v}
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen = set()
    for i, text in enumerate(lines):
        key = text.split("=", 1)[0].strip()
        if key in pairs:
            lines[i], seen = f"{key}={pairs[key]}", seen | {key}
    lines += [f"{k}={v}" for k, v in pairs.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def parse_request_line(line: str, path: str = "/callback"):
    """`GET /callback?code=…&state=… HTTP/1.1` → {"code": …, "state": …}, or None for anything else."""
    parts = str(line or "").strip().split(" ")
    if len(parts) != 3 or parts[0] != "GET" or parts[2] not in ("HTTP/1.0", "HTTP/1.1"):
        return None
    try:
        target = urlsplit(parts[1])
    except ValueError:
        return None
    return dict(parse_qsl(target.query)) if target.path == path else None


def wait_for_callback(port: int, path: str = "/callback", timeout: int = 300, host: str = "127.0.0.1") -> dict:
    """The one request of the flow that comes back to a terminal: listen on 127.0.0.1 only, answer anything that
    is not the callback with a 404 and keep waiting, accept one callback, and close."""
    found: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server's name
            params = parse_request_line(self.requestline, path)
            text = (
                "zer0-CMS received LinkedIn's answer. You can close this tab." if params is not None else "Not found."
            ).encode()
            self.send_response(200 if params is not None else 404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(text)))
            self.end_headers()
            self.wfile.write(text)
            if params is not None:
                found.update(params)

        def log_message(self, *args):
            return None  # the request line carries the code: never into a log

    deadline = time.monotonic() + timeout
    with HTTPServer((host, port), Handler) as server:
        server.timeout = 1
        while not found:
            if time.monotonic() > deadline:
                raise Error(f"no OAuth callback arrived within {timeout} seconds")
            server.handle_request()
    return found
