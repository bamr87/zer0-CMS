/**
 * `.github/workflows/*.yml` — what a workflow file actually *says*, read as data.
 *
 * A lane is seven files pretending to be one thing: an agent file, a skill, a
 * workflow, a manifest entry, a repository variable, a token and a line in a
 * spend ledger. This module reads the one of those seven that is the ground
 * truth — the workflow — and records the facts the other six are supposed to
 * agree with.
 *
 * ## Why this is regex over `parseYamlSubset`, and not a YAML parser
 *
 * `dist/mcp-server.js` is built with an empty bare-import allow-list (decision
 * D14), so nothing reachable from the core barrel may import `yaml` or
 * `@bamr87/fleet-engines`. `src/core/fleet/inspect.ts` solves the same problem
 * by taking the engines as *data*; that works for the extension host, which can
 * inject them, and not at all for the MCP server, which cannot. So this module
 * is deliberately **engines-free**: `parseYamlSubset` for the shapes it can
 * read, and line scans for everything a GitHub Actions file does that the
 * subset cannot (anchors, merge keys, multi-line flow collections, `${{ }}`
 * expressions inside quoted scalars).
 *
 * That is a real duplication of *reading*, but not of *answers*: `inspect.ts`
 * reports the engines' `WorkflowFacts` and its 15-rule audit; this reports the
 * seven fields the inventory joins on, four of which (`runnerShape`,
 * `switchHost`, `switchPolarity`, `dispatchBypassesSwitch`) the engines do not
 * model at all. Where both speak — the lane↔workflow match — the inventory
 * uses the same rule `attachLanes` uses, written down once in `joins.ts`.
 *
 * ## The fields, and why each one earns its place
 *
 * - **`runnerShape`** — the fleet is mid-migration between four ways of calling
 *   a model, and `fleet/v1`'s `harness` vocabulary flattens the hub composite
 *   and a bare `claude -p` into one value (`claude-cli`). A console that cannot
 *   tell them apart cannot report the migration it exists to report.
 * - **`switches` + `switchHost` + `switchPolarity`** — one real lane's switch
 *   lives on a *different* workflow (ai-world-view's `grow-lineage.yml` inherits
 *   `ORCHESTRATE_ENABLED` from `orchestrate.yml`, its only automated
 *   dispatcher), and one reads `!= 'false'`, which is default-**on**. A switch
 *   table that assumed "unset means off" would be wrong about both.
 * - **`dispatchBypassesSwitch`** — the fleet is genuinely split. The hub's
 *   `ai-lane.yml` lets a manual run through a closed switch; lifehacker's own
 *   gates do not. An operator flipping a switch needs to know which they have.
 * - **`crons` vs `dormantCrons`** — a commented-out schedule is not a schedule.
 *   `wtd fleet adopt` scans raw text and records them as live crons, which is
 *   how lifehacker's manifest claims `explore` runs at 06:23 daily when its
 *   cron has been commented out for months. `derive.ts` reproduces that bug on
 *   purpose (parity); this module tells the truth.
 * - **`generatedByGitFactory`** — a `factory--*.yml` is compiled from a
 *   blueprint and will be overwritten. Nothing in this console may propose
 *   editing one, so the fact has to be legible before anything offers.
 *
 * Every field is coerced the way `src/core/fleet/manifest.ts` coerces: a
 * malformed workflow yields a well-typed record with honest nulls, never a
 * `TypeError` three modules away from the bad byte. `null` means "the file did
 * not say", which is a different answer from `false`.
 */

import { parseYamlSubset } from '../content/frontmatter';
import type { RunnerShape, WorkflowRecord } from '../shared/types';
import type { HarnessIo } from './agents';

/** Where a repository keeps its workflows, relative to its root. */
export const WORKFLOWS_DIR = '.github/workflows';

/** The filename stem — `.github/workflows/triage.yml` → `triage`. */
export function workflowStem(filePath: string): string {
  const base = filePath.replace(/\\/g, '/').split('/').pop() ?? filePath;
  return base.replace(/\.ya?ml$/i, '');
}

/** `.github/workflows/x.yml` → `x.yml`. */
export function workflowBasename(filePath: string): string {
  return filePath.replace(/\\/g, '/').split('/').pop() ?? filePath;
}

// ---------------------------------------------------------------------------
// Text scanning — the narrow haystacks
// ---------------------------------------------------------------------------

/**
 * Drop whole-line `#` comments and trailing ` #` comments.
 *
 * A port of `wtd/fleet/textscan.py:strip_comments`, and for its reason: a
 * workflow that *forbids* merging in a prompt, and a workflow that merges, both
 * contain the string `gh pr merge`. Only a trailing `#` preceded by whitespace
 * is stripped, and only on a line with balanced quotes, so `${{ }}` and `$#`
 * survive.
 */
export function stripYamlComments(text: string): string {
  const out: string[] = [];
  for (const raw of text.split('\n')) {
    if (raw.trimStart().startsWith('#')) {
      continue;
    }
    let line = raw;
    if (count(line, '"') % 2 === 0 && count(line, "'") % 2 === 0) {
      line = line.replace(/\s+#(?!\{).*$/, '');
    }
    out.push(line);
  }
  return out.join('\n');
}

function count(text: string, char: string): number {
  let n = 0;
  for (const c of text) {
    if (c === char) {
      n += 1;
    }
  }
  return n;
}

/** Prose that negates a capability rather than exercising it. */
const NEGATION =
  /\b(never|do not|don'?t|must not|cannot|can'?t|no tier|forbidden|refuse|without)\b/i;

/** The line is searching for a pattern, not running it. */
const DETECTOR = /\b(grep|rg|ripgrep|egrep|awk|sed)\b|--allowedTools\s+['"]?\(/;

/** Markdown emphasis or a numbered list — a strong hint the line is prompt prose. */
const PROSE_HINT = /^\s*(?:[-*+]\s+)?\*\*|^\s*\d+\.\s+\[|^\s*>/;

/**
 * Lines that plausibly execute or grant a capability. The `wtd` textscan port,
 * used by both this module and `derive.ts` so the two agree about what "the
 * lane does this" means.
 *
 * Tool grants are kept: `--allowedTools "Bash(gh pr merge:*)"` confers the
 * capability, and FLEET-SPEC is explicit that conferring one *is* having it.
 */
export function commandLines(text: string): string[] {
  const kept: string[] = [];
  for (const line of stripYamlComments(text).split('\n')) {
    if (line.trim() === '') {
      continue;
    }
    if (NEGATION.test(line)) {
      continue;
    }
    const grants = line.includes('allowedTools');
    if (DETECTOR.test(line) && !grants) {
      continue;
    }
    if (PROSE_HINT.test(line) && !grants) {
      continue;
    }
    kept.push(line);
  }
  return kept;
}

/** True when `pattern` matches a line that actually does something. */
export function executesPattern(text: string, pattern: RegExp): boolean {
  return commandLines(text).some((line) => reset(pattern).test(line));
}

/** A fresh lastIndex for a possibly-global regexp, so reuse cannot skip a hit. */
function reset(pattern: RegExp): RegExp {
  pattern.lastIndex = 0;
  return pattern;
}

/**
 * The body of a top-level block — every line after `^<key>:` up to the next
 * column-zero line. An inline form (`on: [push, pull_request]`) yields the
 * remainder of the key line as its single entry.
 *
 * Written as a line scan rather than through `parseYamlSubset` because a
 * workflow's `on:` block routinely carries multi-line flow collections and
 * `${{ }}` inside quoted scalars, both of which the subset reads wrong. A
 * region of raw lines is something later scans can be honest about.
 */
export function topLevelBlock(text: string, key: string): string[] {
  const lines = text.split('\n');
  const head = new RegExp(`^${key}:\\s*(.*)$`);
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (line === undefined) {
      continue;
    }
    const match = head.exec(line);
    if (match === null) {
      continue;
    }
    const inline = (match[1] ?? '').trim();
    const body: string[] = inline === '' ? [] : [inline];
    for (let j = i + 1; j < lines.length; j += 1) {
      const next = lines[j];
      if (next === undefined) {
        break;
      }
      if (next.trim() !== '' && !/^\s/.test(next)) {
        break;
      }
      body.push(next);
    }
    return body;
  }
  return [];
}

// ---------------------------------------------------------------------------
// Runner shape — how this workflow calls a model
// ---------------------------------------------------------------------------

/** A caller of the hub's reusable lane: `uses: <owner>/<repo>/.github/workflows/ai-lane.yml@<ref>`. */
const RE_AI_LANE_CALLER = /[\w.-]+\/[\w.-]+\/\.github\/workflows\/ai-lane\.ya?ml@/;

/** The hub composite, by remote reference or (against the rules) a local copy. */
const RE_CLAUDE_RUN = /[\w.-]+\/[\w.-]+\/[^\s'"]*claude-run@|\.?\/?\.github\/actions\/claude-run\b/;

const RE_CLAUDE_CODE_ACTION = /anthropics\/claude-code-action/;

/** Repo-local scripts that drive an agent loop of their own. */
const RE_AGENTIC_ENGINE = /\b(?:germinate|gate)\.mjs\b|\bagentic_validate\.py\b/;

/** The bare CLI, or the fleet's `scripts/ai/run.sh` shim around it. */
const RE_CLAUDE_CLI = /(?<!\w)claude\s+-p\b|@anthropic-ai\/claude-code|scripts\/ai\/run\.sh/;

/** Any Claude credential named in the file — necessary, but not sufficient. */
const RE_CLAUDE_CREDENTIAL = /secrets\.(?:CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY)/;

/**
 * A repo-local script or reusable being run. Required alongside a credential
 * before this reader will call a workflow an `engine`.
 *
 * The credential alone is not evidence of spending: zer0-mistakes'
 * `deploy-chat-proxy.yml` hands `ANTHROPIC_API_KEY` to `cloudflare/wrangler-action`
 * as a *deploy secret* for a Worker that calls Claude at request time. The
 * workflow spends nothing, and calling it a model call was wrong in the useful
 * direction — it named a real Anthropic key, and still ran no model.
 */
const RE_LOCAL_SCRIPT =
  /(?:ruby|python3?|node|bash|sh)\s+[\w./-]*(?:scripts|engine|tools|test|bin)\//;

/**
 * How this workflow calls a model. Ordered, first match wins, and the order is
 * the point:
 *
 *  1. `ai-lane-caller` — the hub's reusable lane. It is checked first because a
 *     caller also names `claude-run` in nothing but its own comments, and
 *     because `wtd fleet adopt` misses this shape entirely (see `derive.ts`).
 *  2. `claude-run` — the hub composite, the fleet's intended shape.
 *  3. `claude-code-action` — the marketplace action.
 *  4. `agentic-engine` — a repo-local script that runs its own agent loop.
 *     Checked *before* the bare CLI because such a script installs the CLI as a
 *     dependency, and "this lane is an engine" is the more useful answer than
 *     "this lane runs `npm i -g @anthropic-ai/claude-code`".
 *  5. `claude-cli` — a bare `claude -p`, or the `scripts/ai/run.sh` shim.
 *  6. `engine` — no harness marker at all, yet a Claude credential is present:
 *     something here spends a model call through code this reader cannot see
 *     (zer0-mistakes' `translate.yml` calls Claude from a Ruby script). Worth a
 *     name, because that is exactly the class the fleet's own audit calls
 *     "unmetered".
 *  7. `none` — this workflow calls no model.
 */
export function classifyRunnerShape(text: string): RunnerShape {
  // Comment-stripped, because a comment ABOUT a runner is not a runner. The hub's
  // own `ai-lane.yml` carries a copy-me example of `uses: …/ai-lane.yml@main` in
  // its header, and reading the raw text classified the reusable lane as a caller
  // of itself.
  const scanned = stripYamlComments(text);
  if (RE_AI_LANE_CALLER.test(scanned)) {
    return 'ai-lane-caller';
  }
  if (RE_CLAUDE_RUN.test(scanned)) {
    return 'claude-run';
  }
  if (RE_CLAUDE_CODE_ACTION.test(scanned)) {
    return 'claude-code-action';
  }
  if (RE_AGENTIC_ENGINE.test(scanned)) {
    return 'agentic-engine';
  }
  if (RE_CLAUDE_CLI.test(scanned)) {
    return 'claude-cli';
  }
  if (RE_CLAUDE_CREDENTIAL.test(scanned) && RE_LOCAL_SCRIPT.test(scanned)) {
    return 'engine';
  }
  return 'none';
}

/** `true` when this workflow calls a model at all — the inventory's AI filter. */
export function callsAModel(shape: RunnerShape): boolean {
  return shape !== 'none';
}

// ---------------------------------------------------------------------------
// Switches — the kill switch, where it lives, and which way it points
// ---------------------------------------------------------------------------

/**
 * The suffixes the fleet uses for a gating repository variable. Taken from
 * `@bamr87/fleet-engines`' `KILL_SWITCH_SUFFIXES` so a switch this console
 * names is a switch the hub's own audit names.
 */
export const SWITCH_SUFFIXES: readonly string[] = ['_ENABLED', '_AUTOMERGE', '_SUBSTANTIVE'];

const RE_VARS = /vars\.([A-Z][A-Z0-9_]*)/g;
const RE_VARS_INDEX = /vars\[\s*['"]?([A-Za-z][\w.]*)['"]?\s*\]/g;

/**
 * `vars[inputs.switch]` — a switch that exists but whose NAME lives at the call
 * site. The hub's reusable `ai-lane.yml` is gated this way, so "has a switch" and
 * "names a switch" are different questions there.
 */
const RE_INDEXED_SWITCH = /vars\[/;

function looksLikeSwitch(name: string): boolean {
  return SWITCH_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

/**
 * The gating variables this workflow actually reads.
 *
 * A `vars.X` is a switch when its name carries one of the fleet's kill-switch
 * suffixes, or when the file compares it to `'true'` / `'false'` — which is
 * what a gate does and what a `vars.QUEST_AI_MODEL` never does. Reading every
 * `vars.` as a switch is how a switch table ends up listing model names.
 */
export function readSwitches(text: string): string[] {
  const found = new Set<string>();
  const scanned = stripYamlComments(text);
  let match = reset(RE_VARS).exec(scanned);
  while (match !== null) {
    const name = match[1];
    if (name !== undefined && (looksLikeSwitch(name) || comparedToBoolean(scanned, name))) {
      found.add(name);
    }
    match = RE_VARS.exec(scanned);
  }
  // `vars[inputs.switch]` — the hub's reusable lane, whose switch is an input.
  // The name is not knowable here; the caller's `with: switch:` is (below).
  let indexed = reset(RE_VARS_INDEX).exec(scanned);
  while (indexed !== null) {
    const name = indexed[1];
    if (name !== undefined && looksLikeSwitch(name)) {
      found.add(name);
    }
    indexed = RE_VARS_INDEX.exec(scanned);
  }
  // An `ai-lane.yml` caller declares its switch as an input value.
  const declared = /^\s*switch:\s*['"]?([A-Z][A-Z0-9_]*)['"]?\s*$/m.exec(scanned);
  if (declared?.[1] !== undefined) {
    found.add(declared[1]);
  }
  return [...found].sort();
}

function comparedToBoolean(text: string, name: string): boolean {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`vars\\.${escaped}\\s*[!=]=\\s*['"](?:true|false)['"]`).test(text);
}

/**
 * Which way the switch points.
 *
 * `enabled-when-true` is the fleet's default-OFF posture: the lane idles until
 * somebody sets the variable. `disabled-when-false` is default-ON — the lane
 * runs unless somebody sets the variable to `false`, which zer0-mistakes'
 * `visual-evidence-autogen.yml` does and nothing else in the fleet does. A
 * console that assumed the first would report that lane as idle while it ran.
 */
export function readSwitchPolarity(
  text: string,
  switches: readonly string[],
): WorkflowRecord['switchPolarity'] {
  const scanned = stripYamlComments(text);
  if (switches.length === 0 && !RE_INDEXED_SWITCH.test(scanned)) {
    // No switch to have a polarity. ai-world-view's `grow-lineage.yml` compares a
    // `vars.` value to 'true' for something that is not a gate at all, and
    // reporting that as this lane's polarity would name a switch it does not have.
    return 'unknown';
  }
  for (const name of switches) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (new RegExp(`vars\\.${escaped}\\s*!=\\s*['"]false['"]`).test(scanned)) {
      return 'disabled-when-false';
    }
  }
  // Deliberately no looser fallback for `!= 'false'`. lifehacker's
  // `loop-tuner.yml` tests a dispatch INPUT that way (`[ "$IMPROVE" != "false" ]`)
  // while its switch is default-OFF, and a rule that read any `!= 'false'` in the
  // file as polarity would have reported that lane as running unless disarmed.
  if (
    /vars\.[A-Z][A-Z0-9_]*\s*==\s*['"]true['"]/.test(scanned) ||
    /["']\$\{?ENABLED\}?["']?\s*=[=]?\s*["']true["']/.test(scanned) ||
    /\[\s*"\$ENABLED"\s*=\s*"true"\s*\]/.test(scanned) ||
    /"\$ENABLED"\s*!=\s*"true"/.test(scanned)
  ) {
    return 'enabled-when-true';
  }
  return 'unknown';
}

/**
 * The workflow file that hosts a switch this one only *inherits*.
 *
 * ai-world-view's `grow-lineage.yml` is dispatch-only and carries no gate of
 * its own; its scheduled consent is `ORCHESTRATE_ENABLED`, enforced on
 * `orchestrate.yml`, the only workflow that dispatches it. The manifest records
 * that switch against the lane, so a reader that looked only for `vars.` in the
 * lane's own file would call the manifest wrong.
 *
 * The rule: a `*_ENABLED` name that appears in the text but is **not read**
 * here, mentioned within two lines of a `.yml` filename that is not this file.
 * That is prose, and it is read as prose — an `info` finding, never a gate.
 */
export function readSwitchHost(
  text: string,
  switches: readonly string[],
  selfBasename: string,
): string | null {
  const lines = text.split('\n');
  const read = new Set(switches);
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] ?? '';
    const named = /\b([A-Z][A-Z0-9_]*_ENABLED)\b/.exec(line);
    if (named?.[1] === undefined || read.has(named[1])) {
      continue;
    }
    const window = [lines[i - 1] ?? '', line, lines[i + 1] ?? '', lines[i + 2] ?? ''].join('\n');
    const file = /\b([\w.-]+\.ya?ml)\b/.exec(window);
    const host = file?.[1];
    if (host !== undefined && host !== selfBasename) {
      return host;
    }
  }
  return null;
}

/**
 * Does a manual `workflow_dispatch` run get through a closed switch?
 *
 * Three shapes exist in the fleet, and all three are here because the fleet
 * really is split on the question:
 *
 *  - `github.event_name == 'workflow_dispatch' || vars.X_ENABLED == 'true'`
 *    (irony-works' `germinate.yml`) — a job-level `if:`;
 *  - `[ "$EVENT" != "workflow_dispatch" ] && [ "$ENABLED" != "true" ]`
 *    (the hub's `ai-lane.yml`) — a negated event test inside the gate;
 *  - `if [ … = "workflow_dispatch" ]; then echo "go=true"` (lifehacker's
 *    `triage.yml`) — a shell branch that decides before the switch is read.
 *
 * `null` when the question does not arise — which takes two conditions, not one:
 *
 *  - **nothing to bypass.** No named switch *and* no `vars[…]` indexed read.
 *    `false` here would claim a manual run respects a switch that does not exist.
 *  - **no way to dispatch.** No `workflow_dispatch` trigger *and* no
 *    `workflow_call`. The second half matters: the hub's reusable `ai-lane.yml`
 *    declares only `workflow_call`, yet its gate reads
 *    `[ "$EVENT" != "workflow_dispatch" ]` — because for a reusable workflow the
 *    event is the *caller's*. A guard that looked only at this file's own
 *    triggers would report the fleet's canonical bypass as "not applicable".
 */
export function readDispatchBypass(
  text: string,
  events: readonly string[],
  switches: readonly string[],
): boolean | null {
  const scannedText = stripYamlComments(text);
  const gated = switches.length > 0 || RE_INDEXED_SWITCH.test(scannedText);
  const dispatchable = events.includes('workflow_dispatch') || events.includes('workflow_call');
  if (!gated || !dispatchable) {
    return null;
  }
  const lines = scannedText.split('\n');
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] ?? '';
    if (!line.includes('workflow_dispatch')) {
      continue;
    }
    // Shape 1 — an expression that ORs the event against the switch.
    if (line.includes('||') && /vars\.[A-Z][A-Z0-9_]*/.test(line)) {
      return true;
    }
    // Shape 2 — the event test is negated in the same statement as the switch.
    if (/!=\s*['"]?workflow_dispatch/.test(line) && /ENABLED|\$SWITCH|vars\./.test(line)) {
      return true;
    }
    // Shape 3 — a shell branch that sets `go=true` before the switch is read.
    const window = [line, lines[i + 1] ?? '', lines[i + 2] ?? '', lines[i + 3] ?? ''].join('\n');
    if (/=\s*['"]?workflow_dispatch/.test(line) && /\bgo=true\b/.test(window)) {
      return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// Triggers
// ---------------------------------------------------------------------------

/** One `cron:` line, live or parked. `null` when the line is not a cron. */
function cronOnLine(line: string): { cron: string; dormant: boolean } | null {
  const match = /^(\s*)(#\s*)?-?\s*cron:\s*(?:'([^']*)'|"([^"]*)"|([^#\n]*))/.exec(line);
  if (match === null) {
    return null;
  }
  const value = (match[3] ?? match[4] ?? match[5] ?? '').trim();
  if (value === '' || !/^[\d*/,\-\s?LW#]+$/.test(value)) {
    return null;
  }
  return { cron: value, dormant: match[2] !== undefined };
}

/**
 * The `on:` block, however this file spells the key.
 *
 * YAML 1.1 reads a bare `on` as the boolean `true`, which is why every parser in
 * this fleet has a special case for it and why some houses quote the key. This
 * is a line scan, so the quoting is the only thing that varies — but all four
 * spellings occur across the fleet's forty-odd workflows and a reader that
 * handled one would report the other three as having no triggers at all.
 */
export function onBlock(text: string): string[] {
  for (const key of ['on', "'on'", '"on"', 'On', 'ON']) {
    const body = topLevelBlock(text, key);
    if (body.length > 0) {
      return body;
    }
  }
  return [];
}

/** The `on:` block's keys — every trigger the workflow declares, sorted. */
export function readEvents(text: string): string[] {
  const body = onBlock(text);
  const found = new Set<string>();
  // `on: [push, pull_request]` — the whole block is one inline sequence.
  const inline = body[0];
  if (inline !== undefined && inline.startsWith('[')) {
    for (const piece of inline.replace(/^\[|\]$/g, '').split(',')) {
      const name = piece.trim().replace(/^['"]|['"]$/g, '');
      if (name !== '') {
        found.add(name);
      }
    }
    return [...found].sort();
  }
  let base: number | null = null;
  for (const line of body) {
    if (line.trim() === '' || line.trimStart().startsWith('#')) {
      continue;
    }
    const indent = line.length - line.trimStart().length;
    if (base === null) {
      base = indent;
    }
    if (indent !== base) {
      continue;
    }
    const key = /^\s*([a-z_]+):/.exec(line);
    if (key?.[1] !== undefined) {
      found.add(key[1]);
    }
    const item = /^\s*-\s*([a-z_]+)\s*$/.exec(line);
    if (item?.[1] !== undefined) {
      found.add(item[1]);
    }
  }
  return [...found].sort();
}

/** Live crons and parked ones, read from the whole file so a parked one is seen. */
export function readCrons(text: string): { crons: string[]; dormantCrons: string[] } {
  const crons: string[] = [];
  const dormantCrons: string[] = [];
  for (const line of text.split('\n')) {
    const found = cronOnLine(line);
    if (found === null) {
      continue;
    }
    (found.dormant ? dormantCrons : crons).push(found.cron);
  }
  return { crons: dedupe(crons), dormantCrons: dedupe(dormantCrons) };
}

function dedupe(values: readonly string[]): string[] {
  return [...new Set(values)];
}

// ---------------------------------------------------------------------------
// The rest of the record
// ---------------------------------------------------------------------------

/** The workflow's `name:`, from column zero. The stem when it declares none. */
export function readWorkflowName(text: string, filePath: string): string {
  const match = /^name:\s*(.+)$/m.exec(text);
  const declared = (match?.[1] ?? '').trim().replace(/^['"]|['"]$/g, '');
  return declared === '' ? workflowStem(filePath) : declared;
}

/** A `--agent` that labels a metering row rather than choosing an agent file. */
const METERING_LINE = /usage(?:_report|_ledger|-ledger)?\.(?:rb|py|mjs)|ingest-/;

/**
 * The agents this workflow names, as literals.
 *
 * Two things are deliberately **not** agent references:
 *
 *  - `agent: ${{ matrix.item.role }}` — the name is computed at run time and no
 *    file-level reader can resolve it. lifehacker's own `lint_agents.rb` skips
 *    the same expressions, so a dangling reference this console reports is one
 *    that lint would report too.
 *  - `--agent` on a metering line. `ruby scripts/ai/usage.rb
 *    ingest-execution-log "$f" --agent claude-mention` is labelling a ledger
 *    row with a *role*, and a `claude-code-action` lane's role has no agent file
 *    by construction. Reading it as one produced three confident, wrong
 *    "dangling agent" errors against a healthy repository — which is how this
 *    exclusion earned its place.
 */
export function readAgentRefs(text: string): string[] {
  const found = new Set<string>();
  for (const line of stripYamlComments(text).split('\n')) {
    const keyed = /^\s*agent:\s*['"]?([A-Za-z0-9][\w-]*)['"]?\s*$/.exec(line);
    if (keyed?.[1] !== undefined) {
      found.add(keyed[1]);
    }
    if (METERING_LINE.test(line)) {
      continue;
    }
    const flagged = /--agent[= ]+['"]?([A-Za-z0-9][\w-]*)/g;
    let flag = flagged.exec(line);
    while (flag !== null) {
      if (flag[1] !== undefined) {
        found.add(flag[1]);
      }
      flag = flagged.exec(line);
    }
  }
  for (const name of readSubagentRefs(text)) {
    found.add(name);
  }
  return [...found].sort();
}

/**
 * `Use the <x> subagent` — a prompt naming a role in prose.
 *
 * This is an **agent** reference, not a skill one, and the distinction is not
 * pedantic: zer0-mistakes' `ai-content-review.yml` says "Use the
 * content-reviewer subagent" and its `ui-audit.yml` says "Use the ui-auditor
 * subagent", and both names are `.claude/agents/*.md` files. Reading "subagent"
 * as a skill citation reported two live, correctly-wired lanes as having broken
 * skill links — which is how this function came to exist separately.
 */
export function readSubagentRefs(text: string): string[] {
  const found = new Set<string>();
  const pattern = /\b([a-z0-9][a-z0-9._-]*)\s+subagent\b/gi;
  let match = pattern.exec(text);
  while (match !== null) {
    if (match[1] !== undefined) {
      found.add(match[1]);
    }
    match = pattern.exec(text);
  }
  return [...found].sort();
}

/**
 * The skills a workflow's prompt names.
 *
 * There is no structured field for this anywhere in the fleet — the link is a
 * sentence inside a `prompt:` string ("Use the grow-lifehacker skill …"). Two
 * spellings occur and both are read; nothing else is, because a looser pattern
 * turns every occurrence of the word "skill" into a dangling reference.
 *
 * Two spellings deliberately NOT followed here: `<x> subagent`, which names an
 * agent and is read by `readSubagentRefs`; and a slash command
 * (`/test-lifehacker`), which cannot be told apart from a path.
 */
/**
 * Words a `Use the … skill` sentence can leave in the capture group when the
 * skill's own name is elsewhere. bash-365's `content-loop.yml` says "Follow the
 * skill in order:", which named `the` as a skill and reported
 * `.claude/skills/the/SKILL.md` missing.
 */
const NOT_A_SKILL_NAME = new Set([
  'the',
  'a',
  'an',
  'this',
  'that',
  'its',
  'their',
  'our',
  'same',
  'above',
  'following',
  'repo',
  'repository',
  'agent',
  'subagent',
]);

export function readWorkflowSkillRefs(text: string): string[] {
  const found = new Set<string>();
  const patterns = [
    /\b(?:use|follow|run|drives?|via)\s+(?:the\s+)?\*{0,2}`?([a-z0-9][a-z0-9._-]*)`?\*{0,2}\s+skill\b/gi,
    // The bold may close before or after the word "skill": lifehacker writes
    // `**grow-lifehacker skill**` and bash-365 writes `**content-loop** skill`.
    /\*\*`?([a-z0-9][a-z0-9._-]*)`?(?:\s+skill\*\*|\*\*\s+skill\b)/gi,
  ];
  for (const pattern of patterns) {
    let match = reset(pattern).exec(text);
    while (match !== null) {
      const name = match[1];
      if (name !== undefined && name !== '_shared' && !NOT_A_SKILL_NAME.has(name.toLowerCase())) {
        found.add(name);
      }
      match = pattern.exec(text);
    }
  }
  return [...found].sort();
}

/** Every `secrets.X` the file names, sorted — the token side of the join. */
export function readSecrets(text: string): string[] {
  const found = new Set<string>();
  const pattern = /secrets\.([A-Z][A-Z0-9_]*)/g;
  let match = pattern.exec(text);
  while (match !== null) {
    if (match[1] !== undefined) {
      found.add(match[1]);
    }
    match = pattern.exec(text);
  }
  return [...found].sort();
}

/**
 * The file a lane must leave non-empty, or `null`.
 *
 * `pr-result.txt` is the fleet's convention and not its rule: bash-365 writes
 * `loop-result.json`, it-journey only warns, and a `claude-code-action` lane
 * writes nothing at all. So this reads the assertion the workflow actually
 * makes, in the two spellings that exist, and reports `null` rather than
 * assuming the convention holds.
 */
export function readResultFile(text: string): string | null {
  const scanned = stripYamlComments(text);
  const input = /result-file:\s*['"]?([\w.\-/]+\.\w+)/.exec(scanned);
  if (input?.[1] !== undefined) {
    return input[1];
  }
  const asserted = /\[\s*!?\s*-s\s+['"]?([\w.\-/]+\.\w+)['"]?\s*\]/.exec(scanned);
  return asserted?.[1] ?? null;
}

/** Labels the workflow puts on what it opens. */
export function readLabels(text: string): string[] {
  const found = new Set<string>();
  const scanned = stripYamlComments(text);
  const pattern = /--label[= ]+['"]?([^'"\s\\]+)/g;
  let match = pattern.exec(scanned);
  while (match !== null) {
    const label = match[1];
    if (label !== undefined && !label.startsWith('$') && !label.startsWith('-')) {
      found.add(label);
    }
    match = pattern.exec(scanned);
  }
  return [...found].sort();
}

/** The branch name a scripted lane pushes to, as written (shell and all). */
export function readBranchPattern(text: string): string | null {
  const scanned = stripYamlComments(text);
  const assigned = /\bbranch=(?:"([^"\n]+)"|'([^'\n]+)'|([^\s"';]+))/.exec(scanned);
  const value = assigned?.[1] ?? assigned?.[2] ?? assigned?.[3];
  if (value !== undefined && value !== '') {
    return value;
  }
  const checkout = /git checkout -b\s+["']?([^"'\s]+)/.exec(scanned);
  const branch = checkout?.[1];
  return branch === undefined || branch.startsWith('$') ? null : branch;
}

/**
 * The toolchain versions the workflow pins.
 *
 * `null` means "this workflow does not state a version" — which covers both a
 * workflow that installs nothing and one that delegates to a composite that
 * pins it internally (zer0-mistakes' `./.github/actions/setup-ruby`). The field
 * exists to feed a generated lane's `setup-ruby:` input, and there is nothing
 * to pass in either case.
 */
export function readSetup(text: string): WorkflowRecord['setup'] {
  const scanned = stripYamlComments(text);
  return {
    ruby: version(scanned, 'ruby'),
    node: version(scanned, 'node'),
    python: version(scanned, 'python'),
  };
}

function version(text: string, tool: string): string | null {
  const match = new RegExp(`${tool}-version:\\s*['"]?([\\w.]+)`).exec(text);
  const value = match?.[1];
  return value === undefined || value.startsWith('$') ? null : value;
}

/** `dynamic` when a matrix is computed by a planning job, `static` when listed. */
export function readMatrix(text: string): WorkflowRecord['matrix'] {
  const scanned = stripYamlComments(text);
  if (!/^\s*matrix:/m.test(scanned)) {
    return 'none';
  }
  return /matrix:\s*\$\{\{\s*fromJSON|fromJSON\([^)]*(?:matrix|plan)/i.test(scanned)
    ? 'dynamic'
    : 'static';
}

/**
 * The top-level `permissions:` block. Job-level escalations are deliberately not
 * merged in: "what does this file grant everything by default" is the question
 * the fleet's own audit asks, and folding a single job's `issues: write` into
 * the answer would make a least-privilege workflow look permissive.
 */
export function readPermissions(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of topLevelBlock(text, 'permissions')) {
    if (line.trimStart().startsWith('#')) {
      continue;
    }
    const match = /^\s*([a-z-]+):\s*(\S+)\s*$/.exec(line);
    if (match?.[1] !== undefined && match[2] !== undefined) {
      out[match[1]] = match[2];
    }
  }
  return out;
}

/** The longest any job here may run, in minutes — or `null` when none says. */
export function readTimeoutMinutes(text: string): number | null {
  const scanned = stripYamlComments(text);
  const pattern = /timeout-minutes:\s*(\d+)/g;
  let best: number | null = null;
  let match = pattern.exec(scanned);
  while (match !== null) {
    const value = Number.parseInt(match[1] ?? '', 10);
    if (!Number.isNaN(value) && (best === null || value > best)) {
      best = value;
    }
    match = pattern.exec(scanned);
  }
  return best;
}

/** `kit: ai-runner v0.1.0` — wherever in the header comment it is written. */
export function readWorkflowKitStamp(text: string): string | null {
  const match = /(?:^|\s)kit:\s*([a-z][\w-]*)\s+(v[\w.]+)/m.exec(text);
  if (match?.[1] === undefined || match[2] === undefined) {
    return null;
  }
  // The hub writes the stamp mid-sentence ("… opens a pull request\". kit:
  // ai-runner v0.1.0."), so a trailing sentence period is part of the match and
  // not part of the version.
  return `${match[1]} ${match[2].replace(/\.+$/, '')}`;
}

/** GitFactory compiles these from a blueprint and overwrites hand edits. */
export function isGeneratedByGitFactory(text: string, filePath: string): boolean {
  return (
    /GENERATED BY GITFACTORY/i.test(text) || /^factory--/.test(workflowBasename(filePath))
  );
}

// ---------------------------------------------------------------------------
// The record
// ---------------------------------------------------------------------------

/**
 * Read one workflow file. Never throws: a file that is not YAML at all yields a
 * record whose lists are empty and whose tristates are `null`, which is a
 * finding for a caller to report rather than an exception for it to catch.
 *
 * `parseYamlSubset` is consulted for exactly one thing — whether the document
 * parses as a mapping at all — so that a caller can tell "no jobs" from
 * "unreadable". Everything else is a line scan, because everything else is a
 * shape the subset gets wrong.
 */
export function scanWorkflow(filePath: string, text: string): WorkflowRecord {
  const runnerShape = classifyRunnerShape(text);
  const events = readEvents(text);
  const switches = readSwitches(text);
  const { crons, dormantCrons } = readCrons(text);
  const parsed = parseYamlSubset(text);
  const jobs = parsed['jobs'];
  const hasJobs = typeof jobs === 'object' && jobs !== null && !Array.isArray(jobs);

  return {
    path: filePath,
    name: readWorkflowName(text, filePath),
    runnerShape,
    agentRefs: readAgentRefs(text),
    skillRefs: readWorkflowSkillRefs(text),
    switches,
    switchHost: readSwitchHost(text, switches, workflowBasename(filePath)),
    switchPolarity: readSwitchPolarity(text, switches),
    dispatchBypassesSwitch: readDispatchBypass(text, events, switches),
    crons,
    dormantCrons,
    events,
    secrets: readSecrets(text),
    resultFile: readResultFile(text),
    labels: readLabels(text),
    branchPattern: readBranchPattern(text),
    setup: readSetup(text),
    matrix: hasJobs || /^\s*matrix:/m.test(text) ? readMatrix(text) : 'none',
    continueOnError: /continue-on-error:\s*true/.test(stripYamlComments(text)),
    timeoutMinutes: readTimeoutMinutes(text),
    permissions: readPermissions(text),
    kitStamp: readWorkflowKitStamp(text),
    generatedByGitFactory: isGeneratedByGitFactory(text, filePath),
  };
}

/**
 * Every workflow a repository declares, sorted by path so two runs list them in
 * the same order. A repository with no `.github/workflows/` yields `[]` — a
 * normal state, not an error (decision D9).
 *
 * `*.action.yml` is skipped: a composite action that happens to live under the
 * workflows directory is not a workflow, and reading one as a lane would invent
 * a lane nothing runs.
 */
export async function readWorkflows(
  io: HarnessIo,
  dir: string = WORKFLOWS_DIR,
): Promise<WorkflowRecord[]> {
  const entries = await io.list(dir);
  const out: WorkflowRecord[] = [];
  for (const entry of entries.filter(isWorkflowFile).sort()) {
    const rel = `${dir}/${entry}`;
    const text = await io.read(rel);
    if (text !== undefined) {
      out.push(scanWorkflow(rel, text));
    }
  }
  return out;
}

function isWorkflowFile(name: string): boolean {
  return /\.ya?ml$/i.test(name) && !/\.action\.ya?ml$/i.test(name);
}
