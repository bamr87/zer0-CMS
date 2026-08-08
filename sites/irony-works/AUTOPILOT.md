# AUTOPILOT.md — operating the Irony Works autopilot

Irony Works is an **encyclopedia driven by Claude Code**, built on the same
harness and the same governance as [lifehacker.dev](https://lifehacker.dev).
This is the operator's guide.

## TL;DR

A robot reads this repo, researches ironies, scores them against a rubric,
writes the survivors into the vault, and opens a pull request. A human merges.
There is no dashboard — the repo **is** the CMS, and `vault/` is the product.

## The harness

Prompts run through the **Claude Code CLI on OAuth** — keychain locally,
`CLAUDE_CODE_OAUTH_TOKEN` in CI (`claude setup-token` mints one). Subscription
auth means $0 marginal cost per call. If the CLI is missing or cannot
authenticate, `engine/scripts/lib.mjs` falls back to the Anthropic Messages API
with `ANTHROPIC_API_KEY`, which is real spend.

> The founding prompt asked for "the lifehacker.dev AI harness." There is no
> lifehacker.dev completion endpoint — that site runs Claude Code on OAuth.
> Using this harness *is* using that one. `harness.provider: anthropic` forces
> the metered path; everything else takes the CLI.

## The data that drives it

| File | Purpose |
|---|---|
| `engine/seed.config.yml` | Every tunable: model, batch size, gate threshold, domain rotation, writable paths, price table. |
| `engine/prompts/*.md` | The five roles — scout, alanis-gate, scribe, linker, gardener. Prompts are the contract; keep them wire-agnostic. |
| `vault/templates/entry.md` | The schema. `expectation` + `reversal` are the load-bearing fields — they are what make irony machine-checkable. |
| `.claude/skills/grow-irony-works/SKILL.md` | The instructions the robot follows in assisted mode. |
| `vault/compost/the-merely-unfortunate.md` | The "no" pile, with verdicts. Never deleted; history files appeals. |
| `_data/ai_usage/` + `AI_USAGE.md` | The meter: tokens and API-equivalent cost per call, per prompt, per workflow. |

## Running a cycle (assisted mode — preferred)

From the repo root, in Claude Code:

```
/grow-irony-works
```

or just ask: *"do a germination run"* / *"grow the vault"*. The skill will pick
the next domain in rotation, propose candidates, **research them against real
sources** (the step the unattended run cannot do), score them at the gate, draft
the passes into `vault/nursery/`, log the failures to compost, and open a PR.
Then it stops.

You review and merge. Merging is the selection pressure.

## Running a cycle (unattended)

```sh
npm i js-yaml --no-save
node engine/scripts/germinate.mjs [batch]   # uses local OAuth
node engine/scripts/usage-ledger.mjs        # fold the meter into AI_USAGE.md
```

The unattended path has no web access — it draws on model knowledge alone, so
its `veracity` claims deserve more scrutiny at review. Prefer assisted mode when
the entries matter.

## Scheduling (wired, OFF until you flip the variable)

`germinate.yml` carries a weekly cron that **idles behind its switch**:

```sh
gh variable set GERMINATE_ENABLED --body true    # turn the loop on
gh variable set GERMINATE_ENABLED --body false   # turn it off
```

Manual dispatch always runs regardless. The bot token cannot set repo variables,
so **the loop can never enable itself**.

## Guardrails (do not remove)

- **The engine writes to `vault/nursery/`, the compost ledger, and `_data/ai_usage/`. Nothing else.**
  Enforced by `assertWritable()` in `lib.mjs`, not by politeness. Canon, prompts,
  workflows, and config are human-only.
- **No direct pushes to `main`.** The robot works on branches and opens PRs.
- **No self-merge.** A human merges — that is the whole governance model.
- **No invented sources, quotations, dates, or command output.** Everything cited
  was read; everything shown was run.
- **Never sharpen a story past its evidence.** Thin sources mean a downgraded
  `veracity` and a note in the body, not a better-sounding sentence.
- **Prefer one verified irony to five plausible ones.**

If you loosen any of these, say so in `vault/mirrors/` in the same change — a
vault about irony that quietly relaxed its own rules would be an entry.

## The compounding loop

| Memory | File | Written by | Read by |
|---|---|---|---|
| Canon | `vault/` | humans merging PRs | the scout, as the dedupe list |
| Rejections | `vault/compost/the-merely-unfortunate.md` | the gate | future scouts, and appeals |
| Open positions | `vault/futures/` | humans and the gardener | the gardener, as futures mature |
| Self-critique | `vault/mirrors/` | humans and the gardener | anyone checking the vault against itself |
| Cost | `_data/ai_usage/` → `AI_USAGE.md` | every harness call | the operator, deciding what a cycle is worth |

The cycle: **scout → verify → gate → draft → PR → human merges → the merged
entry becomes the next scout's dedupe list and the next entry's `Rhymes with:`
target.** The graph densifies; the vault gets harder to duplicate and easier to
traverse. That is the ratchet.

## Publishing

Push to `main` → `publish.yml` runs `transplant.mjs` (wikilinks → permalinks,
`vault/` → `_entries/`) → Jekyll builds through the `zer0-mistakes` remote theme
→ GitHub Pages. Live at <https://bamr87.github.io/irony-works/>.

`vault/` is the source of truth. The site is a pressing.
