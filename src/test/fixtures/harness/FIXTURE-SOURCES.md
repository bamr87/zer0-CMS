# Fixture sources — verbatim copies, with origin and commit

Every file under `src/test/fixtures/harness/` is a **byte-verbatim** copy of a file that exists in another repository. Nothing here is authored, and that is the whole point: the four houses write their agent files four different ways, and a reader tested against a shape somebody typed into a test is a reader that breaks the first time it meets a real repository.

**Never hand-edit a copy.** When a fixture needs to move forward, re-copy it from the origin path at a newer commit and update the row below. A test that then fails is telling you the fleet changed, which is the signal this directory exists to carry.

The per-repository layout mirrors the real one (`<repo>/.claude/agents/…`, `<repo>/.claude/skills/<name>/SKILL.md`, `<repo>/_data/ai.yml`) so the readers can be pointed at a fixture root exactly the way they are pointed at an open folder. PR4's harness inventory adds `<repo>/.github/workflows/…` and `<repo>/fleet.manifest.yml` to the same trees.

Staged 2026-09-09.

| fixture path | origin repo | origin path | commit |
|---|---|---|---|
| `lifehacker/.claude/agents/grow-lifehacker.md` | `bamr87/lifehacker.dev` | `.claude/agents/grow-lifehacker.md` | `0715766` |
| `lifehacker/.claude/skills/grow-lifehacker/SKILL.md` | `bamr87/lifehacker.dev` | `.claude/skills/grow-lifehacker/SKILL.md` | `0715766` |
| `lifehacker/.claude/skills/_shared/quarantine.md` | `bamr87/lifehacker.dev` | `.claude/skills/_shared/quarantine.md` | `9ee9059` |
| `lifehacker/_data/ai.yml` | `bamr87/lifehacker.dev` | `_data/ai.yml` | `b4b4cbf` |
| `it-journey/.claude/agents/agent-auditor.md` | `bamr87/it-journey` | `.claude/agents/agent-auditor.md` | `7fd3cc59` |
| `it-journey/.claude/skills/cms-curator/SKILL.md` | `bamr87/it-journey` | `.claude/skills/cms-curator/SKILL.md` | `ee4bdbe3` |
| `it-journey/_data/ai.yml` | `bamr87/it-journey` | `_data/ai.yml` | `7fd3cc59` |
| `zer0-mistakes/.claude/agents/a11y-fixer.md` | `bamr87/zer0-mistakes` | `.claude/agents/a11y-fixer.md` | `a377fae6` |
| `zer0-mistakes/.claude/skills/run-zer0-mistakes/SKILL.md` | `bamr87/zer0-mistakes` | `.claude/skills/run-zer0-mistakes/SKILL.md` | `43404554` |
| `zer0-mistakes/_data/ai.yml` | `bamr87/zer0-mistakes` | `_data/ai.yml` | `4edc0010` |
| `bash-365/.claude/agents/loop-writer.md` | `amr-bash/bash-365.com` | `.claude/agents/loop-writer.md` | `14fe3ae` |
| `bash-365/.claude/skills/content-loop/SKILL.md` | `amr-bash/bash-365.com` | `.claude/skills/content-loop/SKILL.md` | `14fe3ae` |
| `hub/agent-auditor.template.md` | `bamr87/bamr87` | `templates/agent-context/agent-auditor.template.md` | `c862558` |

## What each copy is here to prove

| Fixture | The shape it pins |
|---|---|
| `lifehacker/…/grow-lifehacker.md` | A folded `>-` description, a comma-separated `tools:` string, no `model:`, and an agent→skill link written as prose (`**grow-lifehacker skill**`). |
| `it-journey/…/agent-auditor.md` | A one-line description and the *unbolded* `Guardrails: …quarantine.md — all sections apply.` citation that distinguishes this house from the next one. |
| `zer0-mistakes/…/a11y-fixer.md` | A folded description carrying "USE WHEN … DO NOT USE FOR …", and a `model:` pin — thirteen of that repository's seventeen agents carry one. |
| `bash-365/…/loop-writer.md` | A quoted-string description with embedded `<example>` blocks and escapes, a `model:`, a `color:`, and **no `tools:` key at all** — which must read as an empty list, not a defaulted one. |
| `lifehacker/…/_shared/quarantine.md` | The directory under `.claude/skills/` that is **not** a skill, and the reason `skillCountsFor` reports two numbers instead of picking one. |
| the three `_data/ai.yml` files | The full form (with keys this console does not model), the minimal three-key form, and a form buried under thirty lines of comment. |
| `hub/agent-auditor.template.md` | The kit's own house-neutral template, `__PLACEHOLDERS__` and `<!-- kit: agent-context v__KIT_VERSION__ -->` stamp intact. |

`zer0-mistakes/.claude/agents/agent-auditor.md` is deliberately **not** copied here: it is the hub template rendered into that repository, so it reads as it-journey's dialect rather than its host's. The classifier says so, and it is the one file in fifty-two where the answer surprises — which is a fact about the fleet, not a bug in the reader.

## PR4 (WP4.1) — the workflow files, the ledger, and the one overlay

The harness inventory reads two artefacts these trees did not carry: the `.github/workflows/` a lane is implemented in, and the AI-usage ledger a lane's spend lands in.

**Twelve of the workflow files are not copied here.** They are already staged, verbatim and provenanced, under `src/test/fixtures/fleet/workflows/<repo>/` — `content-factory.yml`, `pipeline.yml`, `triage.yml`, `germinate.yml`, `grow-lineage.yml`, `content-loop.yml` and the rest of the twenty-five files `engines.test.ts` reads. `harness.test.ts` reads them where they lie, through an injected I/O that overlays the two trees (`inventoryIo`), and reads `fleet.manifest.yml` from `fixtures/fleet/manifests/<repo>.fleet.manifest.yml` the same way.

That is deliberate and it is not tidiness. One copy of `content-factory.yml` at one recorded commit cannot drift away from itself; two copies eventually do — one gets refreshed, the other does not, and the suite that reads the stale one keeps passing while telling you about a repository that no longer exists. The readers take their filesystem as a parameter precisely so a test can compose one, which is what makes the single copy possible.

**Eleven lifehacker workflows are copied**, because the parity claim needs all seventeen of that repository's lanes derivable from files in the tree, and the fleet fixtures hold six of them. With these eleven, `deriveLaneFromWorkflow` can be run against every lane the committed manifest declares and compared field by field — which is the only way "the port reproduces `wtd fleet adopt`" is a measurement rather than a hope.

Staged 2026-09-09.

| fixture path | origin repo | origin path | commit |
|---|---|---|---|
| `lifehacker/.github/workflows/agent-review.yml` | `bamr87/lifehacker.dev` | `.github/workflows/agent-review.yml` | `50e1ce4` |
| `lifehacker/.github/workflows/brand-sweep.yml` | `bamr87/lifehacker.dev` | `.github/workflows/brand-sweep.yml` | `50e1ce4` |
| `lifehacker/.github/workflows/claude.yml` | `bamr87/lifehacker.dev` | `.github/workflows/claude.yml` | `9ee9059` |
| `lifehacker/.github/workflows/content-scout.yml` | `bamr87/lifehacker.dev` | `.github/workflows/content-scout.yml` | `50e1ce4` |
| `lifehacker/.github/workflows/devops-audit.yml` | `bamr87/lifehacker.dev` | `.github/workflows/devops-audit.yml` | `50e1ce4` |
| `lifehacker/.github/workflows/factory--issue-factory-2.yml` | `bamr87/lifehacker.dev` | `.github/workflows/factory--issue-factory-2.yml` | `e8f5cbd` |
| `lifehacker/.github/workflows/fleet-dispatch.yml` | `bamr87/lifehacker.dev` | `.github/workflows/fleet-dispatch.yml` | `50e1ce4` |
| `lifehacker/.github/workflows/loop-tuner.yml` | `bamr87/lifehacker.dev` | `.github/workflows/loop-tuner.yml` | `50e1ce4` |
| `lifehacker/.github/workflows/quest-forge.yml` | `bamr87/lifehacker.dev` | `.github/workflows/quest-forge.yml` | `50e1ce4` |
| `lifehacker/.github/workflows/weekly-epic.yml` | `bamr87/lifehacker.dev` | `.github/workflows/weekly-epic.yml` | `50e1ce4` |
| `lifehacker/.github/workflows/wire-scout.yml` | `bamr87/lifehacker.dev` | `.github/workflows/wire-scout.yml` | `50e1ce4` |
| `lifehacker/_data/ai_usage/ledger.jsonl` | `bamr87/lifehacker.dev` | `_data/ai_usage/ledger.jsonl` | `68a0fc7` |
| `lifehacker/_data/ai_usage/summary.yml` | `bamr87/lifehacker.dev` | `_data/ai_usage/summary.yml` | `68a0fc7` |
| `zer0-mistakes/.github/workflows/visual-evidence-autogen.yml` | `bamr87/zer0-mistakes` | `.github/workflows/visual-evidence-autogen.yml` | `4edc0010` |

### What each of these copies is here to prove

| Fixture | The shape it pins |
|---|---|
| the eleven lifehacker workflows | Every lane the committed manifest declares, so `deriveLaneFromWorkflow` can be held to all **seventeen** of them and not just the six the fleet fixtures happen to carry. |
| `lifehacker/.github/workflows/loop-tuner.yml` | A dispatch **input** tested with `!= "false"` while the lane's own switch is default-OFF — the false positive that killed a looser polarity rule. |
| `lifehacker/.github/workflows/claude.yml` | A `--agent` flag on a **metering** line (`usage.rb ingest-execution-log … --agent claude-mention`), which labels a ledger row and names no agent file. Reading it as an agent reference produced a confident, wrong error. |
| `lifehacker/.github/workflows/content-scout.yml` | A header comment *documenting* the `secrets.X \|\| github.token` trap the workflow was migrated off. It is the thirteenth token-chain finding against a list of twelve, and the reason that rule reads comment-stripped text. |
| `lifehacker/_data/ai_usage/{ledger.jsonl,summary.yml}` | The one committed ledger in the fleet: a JSONL row whose `workflow` key is the workflow's **`name:`** (`pipeline`) rather than its stem, and a rollup whose three window totals are relative to its own `generated_at`. |
| `zer0-mistakes/.github/workflows/visual-evidence-autogen.yml` | The fleet's **only** default-ON switch (`vars.VISUAL_EVIDENCE_AUTOGEN_ENABLED != 'false'`). A console that assumed "unset means off" would report a running lane as idle. |
