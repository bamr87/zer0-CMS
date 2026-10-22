# `Zer0Cms::Distribution` — the LinkedIn lane

The governed path from a site's page to a LinkedIn post, and the aggregate response back into `.cms/distribution/performance.json`. The CLI (`bin/zer0-cms linkedin`), the reusable workflow (`.github/workflows/zer0-linkedin.yml`), the MCP server and the Rails CMS all call `Pipeline`. The design of record, including every gate and the declared call plan, is [`docs/DISTRIBUTION.md`](../../../../docs/DISTRIBUTION.md).

| File | What it holds |
|---|---|
| `config.rb` | A site's settings: `zer0.json` `distribution.linkedin`, then `_config.yml`, with environment overrides. Files describe; only `ZER0_LINKEDIN_PUBLISH=1` arms |
| `drafts.rb` | The queue: the extension's and the Python lane's dialect, always-pending creation, status by line surgery |
| `guard.rb` | The brand guard, rule-for-rule with `src/core/governance/guard.ts` |
| `permalink.rb` | The URL Jekyll 4.4 gives a page — the canonical URL and the ledger key |
| `composer.rb` | A deterministic first commentary, byte-compatible with the Python lane's default |
| `ledger.rb` | What was published, keyed by URL, written as Python's `json.dump`; an unreadable ledger is refused, never read as empty |
| `py_json.rb` | Python's `json.dumps`, byte for byte |
| `pipeline.rb` | compose, approve, preview (pure), publish (gated), posts, statistics, token status |
| `analytics.rb` | Statistics joined onto content paths through the ledger, merged into `performance.json` |
| `cli.rb`, `callback.rb` | `zer0-cms linkedin …` and the loopback OAuth callback |
| `mcp.rb` | The MCP server — no approve tool, publish off unless the operator armed it |

`test/zer0_cms/test_distribution.rb` drives the whole lane against a site built in a temp directory and a `ScriptedTransport`. `zer0 doctor` validates a site's block through `Config` under its `distribution` check.
