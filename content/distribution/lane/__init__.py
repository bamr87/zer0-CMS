"""The LinkedIn lane over a site's own files — the Ruby lane
(`rails/lib/zer0_cms/distribution/`, retired by PLAN G5) in Python, for what
has no database: a content repository's CI (the reusable `zer0-linkedin.yml`)
and a terminal, through `manage.py linkedin`.

| Module | What it holds |
|---|---|
| `site.py` | a site's settings (`zer0.json` `distribution.linkedin`, `_config.yml`, the environment), its pages, and the default commentary |
| `drafts.py` | the queue: the extension's dialect, always-pending creation, status by line surgery |
| `pipeline.py` | compose, approve, preview (pure), publish (gated), record, posts, statistics, token status |
| `cli.py` | `manage.py linkedin COMMAND --site PATH` and the loopback OAuth callback |

It shares the platform's LinkedIn client (`distribution/linkedin/`), its gates
(`distribution/gates.py`), its ledger file (`distribution/ledger.py`), its
permalinks (`distribution/permalink.py`) and its brand guard
(`suggestions/guard.py`), so a draft, a finding and a ledger entry mean the same
thing in the extension, the studio and CI.
"""
