# The Engine

Five prompts, three scripts, one gate.

## Prompts (`prompts/`)
- **scout.md** — proposes candidate ironies for the cycle's domain
- **scribe.md** — drafts a candidate into the entry schema
- **alanis-gate.md** — the rubric; scores 0–10, verdicts below threshold
- **linker.md** — weaves new entries into the graph with wikilinks
- **gardener.md** — maintenance pass: dedupe, stale links, futures that matured

## Scripts (`scripts/`)
- **lib.mjs** — harness call (Anthropic API by default, lifehacker.dev adapter stub), config, path guardrails
- **germinate.mjs** — full cycle: scout → scribe → gate → nursery + compost
- **gate.mjs** — standalone gate for PR checks (used by alanis-gate.yml)
- **transplant.mjs** — vault → Jekyll collection (wikilinks → permalinks) for zer0-mistakes publishing

## Swapping the harness
`seed.config.yml → harness.provider`. The default (`claude-code`) runs prompts
through the Claude Code CLI, which brings its own OAuth credentials — the
keychain locally, a `CLAUDE_CODE_OAUTH_TOKEN` secret in CI (generate one with
`claude setup-token`). If the CLI is missing or can't authenticate, the engine
falls back to the [Claude API](https://docs.claude.com/en/api/overview) with
`ANTHROPIC_API_KEY`; set `provider: anthropic` to skip the CLI entirely. The
`lifehacker` provider is a stub in `lib.mjs` marked `// HARNESS ADAPTER` —
point it at the lifehacker.dev endpoint and env var, and every prompt in this
directory flows through it unchanged. Prompts are the contract; the wire is
an implementation detail.
