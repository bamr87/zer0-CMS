/**
 * `.claude/agents/<name>.md` — the fleet's agent files, read as data.
 *
 * An agent file is the role a run is performed *as*: a name, a description, the
 * tools it may use, and sometimes a model. CI passes one to the runner as
 * `--agent <name>`; this module is what lets the editor offer the same list.
 *
 * Three things make the parsing less trivial than "read the front matter":
 *
 *  1. **`tools` arrives in two notations.** Every repository in this fleet
 *     writes it as a comma-separated *string* (`tools: Bash, Read, Write`), the
 *     Claude Code documentation writes it as a YAML list, and both mean the
 *     same list. Both land here as `string[]`. The split is parenthesis-aware,
 *     because a scoped tool is spelled `Bash(gh pr create:*)` and a naive
 *     `split(',')` would eventually cut one of those in half.
 *  2. **`name` must equal the filename stem.** lifehacker's own
 *     `scripts/ci/lint_agents.rb` enforces it, and for a reason: the workflow
 *     names the agent by string, and Claude Code resolves that string against
 *     the *filename*. A file whose front matter disagrees is a dangling
 *     reference waiting to happen. So `nameMatchesFile` is recorded rather than
 *     silently repaired — a reader that renames the file to match would hide
 *     exactly the defect the lint exists to find.
 *  3. **Four houses, four dialects.** lifehacker folds its description with
 *     `>-` and ends with `## Hard rules`; it-journey writes one line and cites
 *     the shared quarantine doc; zer0-mistakes pins a `model:` and writes
 *     "USE WHEN … DO NOT USE FOR …"; bash-365 carries a quoted description with
 *     `<example>` blocks, a `color:`, and no `tools:` key at all. `dialect` is
 *     **descriptive** — it never gates anything — and the classifier is written
 *     down in `README.md` so a fifth house can be added by reading it.
 *
 * Pure: no `fs`, no `vscode`. `readAgents` takes its I/O as a parameter, which
 * is what lets the same code serve the extension host, the MCP server and a
 * test over a fixture directory.
 */

import { asList, asString, splitFrontMatter } from '../content/frontmatter';
import type { AgentDialect, AgentRecord } from '../shared/types';

/** Where a repository keeps its agent files, relative to its root. */
export const AGENTS_DIR = '.claude/agents';

/**
 * The injected filesystem the harness readers take. Deliberately two methods:
 * anything that needs more than "what is in this directory" and "what does this
 * file say" is doing something a pure reader should not be doing.
 *
 * `list` returns the entry names directly under `rel` (files and directories,
 * no recursion) and an empty array when the directory is absent — a repository
 * with no `.claude/` is a normal repository, not an error. `read` returns
 * `undefined` for a file that is not there or cannot be read as UTF-8.
 */
export interface HarnessIo {
  list(rel: string): Promise<string[]>;
  read(rel: string): Promise<string | undefined>;
}

/** The filename stem — `.claude/agents/grow-lifehacker.md` → `grow-lifehacker`. */
export function agentStem(filePath: string): string {
  const base = filePath.replace(/\\/g, '/').split('/').pop() ?? filePath;
  return base.endsWith('.md') ? base.slice(0, -3) : base;
}

/**
 * Split a `tools:` string into names, without cutting a scoped tool in half.
 *
 * `Bash(git:*),Bash(gh pr create:*),Write(pages/**)` is one legal value in this
 * fleet, and the scope inside the parentheses may itself contain a comma. So
 * the split tracks parenthesis depth and only breaks at depth zero.
 */
export function splitToolList(value: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let current = '';
  for (const char of value) {
    if (char === '(' || char === '[') {
      depth += 1;
    } else if (char === ')' || char === ']') {
      depth = Math.max(0, depth - 1);
    }
    if (char === ',' && depth === 0) {
      out.push(current);
      current = '';
      continue;
    }
    current += char;
  }
  out.push(current);
  return dedupe(out.map((name) => name.trim()).filter((name) => name.length > 0));
}

function dedupe(values: readonly string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values) {
    if (!seen.has(value)) {
      seen.add(value);
      out.push(value);
    }
  }
  return out;
}

/** `<!-- kit: agent-context v0.4.0 -->` → `agent-context v0.4.0`. */
export function readKitStamp(body: string): string | null {
  const match = /<!--\s*kit:\s*([^\n>]+?)\s*-->/.exec(body);
  return match?.[1] ?? null;
}

/**
 * The skills an agent file delegates to.
 *
 * The link is **prose** — there is no front-matter key for it anywhere in the
 * fleet. Three spellings occur: `**grow-lifehacker skill**` (lifehacker),
 * `` **`content-loop` skill** `` (bash-365), and a literal path
 * `.claude/skills/<name>/SKILL.md` (the quarantine citation and it-journey's
 * inventory step). All three are read; the quarantine doc is *not* a skill and
 * is filtered out here for the same reason `readSkills` excludes it.
 */
export function readSkillRefs(body: string): string[] {
  const found: string[] = [];
  // `**grow-lifehacker skill**` (the word inside the bold), `**cms-curator**
  // skill` (outside it), and `` **`content-loop` skill** `` all occur, and all
  // three mean the same edge in the join.
  const bolded = /\*\*`?([a-z0-9][a-z0-9._-]*)`?(?:\s+skill\*\*|\*\*\s+skill\b)/gi;
  const pathed = /\.claude\/skills\/([A-Za-z0-9._-]+)\//g;
  for (const re of [bolded, pathed]) {
    let match = re.exec(body);
    while (match !== null) {
      const name = match[1];
      if (name !== undefined && name !== SHARED_SKILL_DIR) {
        found.push(name);
      }
      match = re.exec(body);
    }
  }
  return dedupe(found);
}

/** The one directory under `.claude/skills/` that is not a skill. */
export const SHARED_SKILL_DIR = '_shared';

/** House tokens, in the order a tie is broken. Case-insensitive, word-ish. */
const HOUSE_TOKENS: ReadonlyArray<{ dialect: AgentDialect; pattern: RegExp }> = [
  { dialect: 'lifehacker', pattern: /lifehacker/gi },
  { dialect: 'it-journey', pattern: /it[-\s]journey/gi },
  { dialect: 'zer0-mistakes', pattern: /zer0-mistakes/gi },
  { dialect: 'bash-365', pattern: /bash-?365|bashconsultants|BASH Consulting/g },
];

/**
 * Which house's dialect this file is written in. Descriptive, never gating.
 *
 * **Structure first, name second.** A file's *shape* is what a dialect is; the
 * site it happens to name is only a tiebreak, because an agent that files
 * upstream bugs mentions two houses and belongs to the one whose conventions it
 * was written in. Ordered, first match wins:
 *
 *  1. A description carrying `<example>` blocks, or a `color:` key — the
 *     bash-365 persona shape. Six of six there, none anywhere else.
 *  2. A **bolded** `**Guardrails:**` citation of the shared quarantine doc, a
 *     "USE WHEN … DO NOT USE FOR …" description, or a `model:` pin —
 *     zer0-mistakes. Sixteen of seventeen carry the bolded line.
 *  3. An *unbolded* `Guardrails: …quarantine.md — all sections apply.` line —
 *     it-journey. Ten of ten, and the shape the hub's own template inherited.
 *  4. `## Hard rules` or `## The shape of a good run`, with the quarantine
 *     rules restated in prose rather than cited — lifehacker.
 *  5. Otherwise whichever house the file names most often.
 *  6. Otherwise `unknown`, which is a real answer for a file written to no
 *     house's conventions at all.
 */
export function classifyDialect(front: {
  description: string;
  hasColor: boolean;
  model: string | null;
  body: string;
}): AgentDialect {
  if (/<example>/i.test(front.description) || front.hasColor) {
    return 'bash-365';
  }
  const quarantine = new RegExp(`^\\s*(?:[-*]\\s*)?(\\*\\*)?Guardrails:`, 'm');
  const cite = quarantine.exec(front.body);
  const bolded = cite?.[1] !== undefined;
  if (
    (cite !== null && bolded) ||
    /USE WHEN|DO NOT USE FOR/.test(front.description) ||
    front.model !== null
  ) {
    return 'zer0-mistakes';
  }
  if (cite !== null) {
    return 'it-journey';
  }
  if (/^##\s+Hard rules|^##\s+The shape of a good run/im.test(front.body)) {
    return 'lifehacker';
  }
  const haystack = `${front.description}\n${front.body}`;
  let best: { dialect: AgentDialect; count: number } | null = null;
  for (const { dialect, pattern } of HOUSE_TOKENS) {
    const count = (haystack.match(pattern) ?? []).length;
    if (count > 0 && (best === null || count > best.count)) {
      best = { dialect, count };
    }
  }
  return best?.dialect ?? 'unknown';
}

/**
 * Parse one agent file. Never throws: a file with no front matter yields a
 * record whose `nameMatchesFile` is `false` and whose lists are empty, which is
 * a finding for a caller to report — not an exception for it to catch.
 */
export function parseAgentFile(filePath: string, text: string): AgentRecord {
  const { block, body } = splitFrontMatter(text);
  const data = block?.data ?? {};
  const stem = agentStem(filePath);
  const declared = asString(data['name']).trim();
  const rawTools = data['tools'];
  const tools = Array.isArray(rawTools)
    ? dedupe(asList(rawTools).map((tool) => tool.trim()).filter((tool) => tool.length > 0))
    : splitToolList(asString(rawTools));
  const model = asString(data['model']).trim();
  const description = asString(data['description']).trim();

  return {
    name: declared.length > 0 ? declared : stem,
    path: filePath,
    description,
    tools,
    model: model.length > 0 ? model : null,
    kitStamp: readKitStamp(body),
    skillRefs: readSkillRefs(body),
    citesQuarantine: body.includes(`${SHARED_SKILL_DIR}/quarantine.md`),
    dialect: classifyDialect({
      description,
      hasColor: Object.prototype.hasOwnProperty.call(data, 'color'),
      model: model.length > 0 ? model : null,
      body,
    }),
    nameMatchesFile: declared === stem,
  };
}

/**
 * Every agent a repository declares, sorted by name so a QuickPick and a report
 * list them in the same order twice running. A repository with no `.claude/`
 * yields `[]`.
 */
export async function readAgents(io: HarnessIo, dir: string = AGENTS_DIR): Promise<AgentRecord[]> {
  const entries = await io.list(dir);
  const out: AgentRecord[] = [];
  for (const entry of entries.filter((name) => name.endsWith('.md')).sort()) {
    const rel = `${dir}/${entry}`;
    const text = await io.read(rel);
    if (text !== undefined) {
      out.push(parseAgentFile(rel, text));
    }
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

/** The agent with this name, or `null`. Exact match: the runner's is too. */
export function findAgent(agents: readonly AgentRecord[], name: string | null): AgentRecord | null {
  if (name === null || name.length === 0) {
    return null;
  }
  return agents.find((agent) => agent.name === name) ?? null;
}
