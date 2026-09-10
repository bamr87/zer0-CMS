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
