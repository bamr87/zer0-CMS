"""`manage.py x COMMAND` — the X lane from a terminal and from CI (the reusable
`zer0-x.yml`), over a site's own files: the LinkedIn lane's command line
(`cli.py`) with X's commands.

Exit status as `manage.py linkedin`: 0 when the command did what it says, 1
when something was refused or failed, 2 on bad usage; `preview` and a rehearsed
`publish` exit 1 on a blocker that arming would not lift. Credentials come from
the environment only.
"""

import json
import os
import sys
import time
from pathlib import Path

from ..ledger import LedgerError
from ..x import Client, Error, oauth, plan
from ..x.client import send
from .cli import Runner, Usage, parser, write_env
from .site import ConfigError
from .x_mcp import XServer
from .x_pipeline import XPipeline
from .x_site import ARM_VARIABLE, XConfig

USAGE = """manage.py x — X distribution for a site's own files

Usage: manage.py x COMMAND [--site PATH] [--json] [options]

  status [--check]                   settings, queue and ledger; --check asks X which account the token posts as
  plan                               every X call this lane can make, and nothing else
  sources [--all]                    pages that can be shared (--all includes shared ones)
  queue                              drafts and their status
  calendar                           which draft a queue run releases when, under the cadence (issue #89)
  draft SOURCE [--commentary TEXT | --commentary-file FILE]
  draft --update --slug SLUG (--message TEXT | --message-file FILE)
                                     write a pending draft
  approve DRAFT                      pending -> approved: a person's decision
  preview [DRAFT]                    the exact post, the guard and every blocker; no network
  publish [DRAFT] [--live]           rehearse; with --live and ZER0_X_PUBLISH=1, post
  publish DRAFT --live --force       post past a guard error, a ledger entry or an unconfirmed attempt
  record DRAFT ID                    record a post a person found on X
  posts [--count N]                  the account's own recent posts
  verify ID                          read one of the account's posts back
  connect [--write-env FILE | --print-token]
                                     connect an account: OAuth 1.0a with the PIN X shows its owner
  mcp                                the same tools over MCP (stdio); publishing off unless armed

Credentials come from the environment only: X_API_KEY and X_API_SECRET (the app's),
X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET (the account's).
Settings: zer0.json "distribution": { "x": { ... } } (docs/DISTRIBUTION.md).
X bills each request: a post carrying a link costs more than one without.
"""

COMMANDS = (
    "status",
    "plan",
    "sources",
    "queue",
    "calendar",
    "draft",
    "approve",
    "preview",
    "publish",
    "record",
    "posts",
    "verify",
    "connect",
    "mcp",
)


def main(argv, *, out=sys.stdout, err=sys.stderr, env=None, transport=send, sleeper=time.sleep, stdin=None) -> int:
    try:
        opts = parser().parse_intermixed_args(argv)
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
        env = os.environ if env is None else env
        if opts.command == "mcp":
            server = XServer(opts.site, env=env, pipeline_options={"transport": transport, "sleeper": sleeper})

            def write(message):
                out.write(json.dumps(message) + "\n")
                out.flush()

            return server.run(stdin if stdin is not None else sys.stdin, write)
        runner = XRunner(XPipeline(XConfig(opts.site, env=env), transport=transport, sleeper=sleeper), opts, out, err)
        runner.stdin = stdin if stdin is not None else sys.stdin
        return getattr(runner, opts.command)()
    except (ConfigError, LedgerError, ValueError, KeyError, OSError) as e:
        err.write(f"error: {e}\n")
        return 1
    except Error as e:
        err.write(f"X: {e}\n")
        return 1


class XRunner(Runner):
    """The LinkedIn lane's commands where they are the same (sources, queue, draft, approve, preview, publish,
    record), X's where they are not."""

    def status(self):
        report = self.pipeline.status(check=self.opts.check)
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

    def posts(self):
        found = self.pipeline.posts(count=self.opts.count)
        if self.opts.json:
            self.emit(found)
        for post in [] if self.opts.json else found:
            first = (str(post.get("text") or "").splitlines() or [""])[0].strip()[:90]
            self.line(f"{post.get('id')}  {first}")
        return 0

    def connect(self):
        credentials = self.config.credentials
        if not credentials.app:
            raise ConfigError("connect needs X_API_KEY and X_API_SECRET in the environment (the app's key and secret)")
        client = Client(credentials, transport=self.pipeline.transport, sleeper=self.pipeline.sleeper)
        token, secret = oauth.request_token(client)
        self.line("Open this URL signed in as the account that will post, approve, and type the PIN X shows:\n")
        self.line(f"{oauth.authorize_url(token)}\n")
        self.out.flush()
        self.err.write("PIN: ")
        self.err.flush()
        pin = self.stdin.readline()
        found = oauth.access_token(client, token=token, secret=secret, pin=pin)
        self.line(f"Connected @{found['account'] or '?'} (use it as distribution.x.account).")
        if found["account"] and self.config.account and found["account"].lower() != self.config.account.lower():
            self.line(f"warning: zer0.json names @{self.config.account}, not @{found['account']}")
        pairs = {"X_ACCESS_TOKEN": found["access_token"], "X_ACCESS_TOKEN_SECRET": found["access_token_secret"]}
        self.store(pairs)
        return 0

    def store(self, pairs):
        if self.opts.write_env:
            write_env(self.env_file(), pairs)
            self.line(f"Wrote the token to {self.opts.write_env} (mode 600).")
        elif self.opts.print_token:
            for key, value in pairs.items():
                self.line(f"{key}={value}")
        else:
            self.line(
                "The token was not stored. Re-run with --write-env .env (a gitignored file) or --print-token "
                "to copy it into the X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET secrets."
            )

    def print_status(self, report):
        drafts = ", ".join(f"{v} {k}" for k, v in report["drafts"].items())
        held = [k for k, v in report["credentials"].items() if v]
        self.line(f"X distribution — {report['site']}")
        self.line(f"  configured   {'yes (zer0.json distribution.x)' if report['configured'] else 'no'}")
        self.line(f"  account      {'@' + report['account'] if report['account'] else '(none)'}")
        self.line(f"  site URL     {report['site_url'] or '(none)'}")
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
            who = f" — posts as {token['account']}" if token.get("account") else ""
            self.line(f"  token        {'ok' if token.get('ok') else 'NOT OK'}{who}")
            for message in token.get("problems", []):
                self.line(f"    problem  {message}")

    def print_preview(self, preview):
        draft = preview.draft
        self.line(f"\n{draft.relative}  [{draft.status}, {preview.kind}]")
        self.line(f"  key        {preview.key or '(none)'}")
        if preview.entry:
            self.line(f"  source     {preview.entry.relative}")
        text = (preview.payload or {}).get("text", preview.commentary)
        self.line(f"  text       {plan.weighted_length(text)} of {plan.TEXT_MAX} characters as X counts them:")
        for line in text.splitlines():
            self.line(f"    | {line}")
        for note in preview.notes:
            self.line(f"  note       {note}")
        for finding in preview.guard:
            if finding["level"] != "info":
                self.line(f"  {finding['level'].upper().ljust(10)} {finding['message']}")
        if not preview.blockers:
            self.line("  blockers   none")
        for blocker in preview.blockers:
            self.line(f"  blocked    {blocker.kind}: {blocker.message}")
        self.line(f"  payload    POST https://{plan.API_HOST}/2/tweets")
        if preview.payload:
            for line in json.dumps(preview.payload, indent=2, ensure_ascii=False).splitlines():
                self.line(f"    {line}")
