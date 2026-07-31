/**
 * The mechanical brand guard — the half of the review that a machine can do.
 *
 * Three proven rule sets merged into one pass: the length and banned-phrase
 * errors from the Python publisher's `guard_commentary`, the 13 hard bans from
 * `scripts/content_lint.py`, and the filler / weak-hook warnings and the
 * 140-character fold preview from `compose.check`.
 *
 * Levels are a contract, not a decoration:
 *   - `error`   blocks a publish unless the caller forces it. Never blocks a
 *               preview — seeing what is wrong is how it gets fixed.
 *   - `warning` never blocks. It is an opinion about the writing.
 *   - `info`    never blocks. Exactly one is always appended: the fold
 *               preview, so the UI can draw the "… see more" line at the same
 *               character count the reader will see it at.
 *
 * The human review before approve is the other half of the gate. This module
 * exists so that half never has to spend attention on "did we say
 * cutting-edge again".
 */

import * as fs from 'node:fs/promises';

import { readJsonc } from '../shared/jsonio';
import { absPath } from '../shared/config';
import type { Zer0Config } from '../shared/types';

/** Where a long post is visually truncated; the hook has to land before it. */
export const FOLD = 140;

/** Hard ceiling on a single piece of commentary. */
export const MAX_LEN = 3000;

export type GuardLevel = 'error' | 'warning' | 'info';

export interface GuardFinding {
  level: GuardLevel;
  message: string;
}

export interface BannedPattern {
  name: string;
  pattern: RegExp;
}

/**
 * The 13 hard bans. All errors, all case-insensitive. Ported verbatim from the
 * Python lane so a phrase that fails in CI fails here, with the same name.
 */
export const BANNED_PATTERNS: readonly BannedPattern[] = [
  { name: 'cutting-edge', pattern: /\bcutting[- ]edge\b/i },
  { name: 'next-generation', pattern: /\bnext[- ]generation\b/i },
  { name: 'disruptive', pattern: /\bdisruptive\b/i },
  { name: 'revolutionary', pattern: /\brevolutionar(?:y|ies)\b/i },
  {
    // The smart apostrophe is not optional: real prose from an editor
    // contains U+2019, and a rule that only matches U+0027 would pass it.
    name: "in today's ... world/age/era",
    pattern: /\bin\s+today[’']s\s+[^.\n]{0,40}?\b(world|age|era|landscape|climate|environment)\b/i,
  },
  { name: 'leverage synergies', pattern: /\bleverag\w*\s+synerg\w*/i },
  { name: 'unlock value', pattern: /\bunlock(?:ing|s)?\s+value\b/i },
  { name: 'best-of-breed', pattern: /\bbest[- ]of[- ]breed\b/i },
  { name: 'world-class', pattern: /\bworld[- ]class\b/i },
  { name: 'solutioning', pattern: /\bsolutioning\b/i },
  { name: 'ideate', pattern: /\bideat(?:e|es|ed|ing|ion)\b/i },
  { name: 'circle back', pattern: /\bcircl(?:e|ing)\s+back\b/i },
  { name: 'low-hanging fruit', pattern: /\blow[- ]hanging\s+fruit\b/i },
];

/** The 9 filler patterns. All warnings. */
export const FILLER: ReadonlyArray<readonly [RegExp, string]> = [
  [/\bgame[- ]chang(?:er|ing)\b/i, 'game-changer'],
  [/\bcutting[- ]edge\b/i, 'cutting-edge'],
  [/\bnext[- ]generation\b/i, 'next-generation'],
  [/\brevolutionar(?:y|ies)\b/i, 'revolutionary'],
  [/\bexcited to announce\b/i, 'excited to announce'],
  [/\bthrilled to\b/i, 'thrilled to'],
  [/\bhumbled\b/i, 'humbled'],
  [/\bsynerg\w*/i, 'synergy'],
  [/!{1,}/, 'exclamation mark'],
];

/**
 * A `g` or `y` regex carries `lastIndex` between calls, so the same pattern
 * would match, then not match, then match again across previews. Workspace
 * patterns are author-supplied and may well carry those flags; strip them.
 */
function stateless(pattern: RegExp): RegExp {
  if (!pattern.global && !pattern.sticky) {
    return pattern;
  }
  return new RegExp(pattern.source, pattern.flags.replace(/[gy]/g, ''));
}

/**
 * Run every rule over `text`.
 *
 * Order matters and is preserved from the Python lane: length, then bans (in
 * declaration order, workspace patterns last), then the exclamation warning,
 * then filler, then the weak hook, then the fold. Two deduplications keep the
 * output honest rather than noisy:
 *
 *   1. the filler entry literally named `exclamation mark` is skipped, because
 *      the dedicated check above already reported it;
 *   2. a filler entry whose name already produced an *error* is skipped —
 *      which is why `cutting-edge`, `next-generation` and `revolutionary`
 *      report once rather than twice.
 *
 * `synergy` is deliberately **not** deduped against the ban named `leverage
 * synergies`: the names differ, so "leverage synergies" reports both an error
 * and a filler warning. That is the upstream behaviour and changing it would
 * silently diverge two lanes that are supposed to agree.
 *
 * A clean string yields exactly one finding: the fold `info`.
 */
export function guardText(
  text: string,
  opts: { extraPatterns?: readonly BannedPattern[] } = {},
): GuardFinding[] {
  const findings: GuardFinding[] = [];
  const erroredNames = new Set<string>();

  if (text.length > MAX_LEN) {
    findings.push({
      level: 'error',
      message: `commentary is ${text.length} chars (max ${MAX_LEN})`,
    });
  }

  for (const { name, pattern } of [...BANNED_PATTERNS, ...(opts.extraPatterns ?? [])]) {
    const match = stateless(pattern).exec(text);
    if (match) {
      findings.push({ level: 'error', message: `banned phrase "${match[0]}" (${name})` });
      erroredNames.add(name);
    }
  }

  if (text.includes('!')) {
    findings.push({
      level: 'warning',
      message: 'exclamation mark in commentary (house style: none)',
    });
  }

  for (const [pattern, name] of FILLER) {
    if (name === 'exclamation mark' || erroredNames.has(name)) {
      continue;
    }
    if (stateless(pattern).test(text)) {
      findings.push({ level: 'warning', message: `reads as filler: ${name}` });
    }
  }

  // The reason to keep reading has to land before the fold. A first line that
  // ends in under 40 characters has not said anything yet.
  const first = text.slice(0, FOLD);
  if (first.includes('\n') && (first.split('\n')[0] ?? '').length < 40) {
    findings.push({
      level: 'warning',
      message: 'weak hook: the first line ends before it says anything',
    });
  }

  findings.push({ level: 'info', message: `fold at ${FOLD} chars: "${first}"` });
  return findings;
}

/** Does this set of findings block a publish? */
export function hasErrors(findings: readonly GuardFinding[]): boolean {
  return findings.some((f) => f.level === 'error');
}

/** The `error` messages only — what a blocked publish reports back. */
export function errorMessages(findings: readonly GuardFinding[]): string[] {
  return findings.filter((f) => f.level === 'error').map((f) => f.message);
}

/**
 * Load extra banned patterns from a workspace JSON file:
 * `[{ "name": "…", "pattern": "…", "flags": "i" }]`.
 *
 * Throws on anything malformed — a caller that asked for this file by name
 * (the "check my patterns file" command) wants to hear why it failed. The
 * publish path calls `workspacePatterns` instead, which swallows.
 */
export async function loadWorkspacePatterns(file: string): Promise<BannedPattern[]> {
  const raw = readJsonc<unknown>(await fs.readFile(file, 'utf8'));
  if (!Array.isArray(raw)) {
    throw new Error(`banned-patterns file must be a JSON array: ${file}`);
  }
  return raw.map((entry, index) => {
    const e = entry as { name?: unknown; pattern?: unknown; flags?: unknown };
    if (typeof e.name !== 'string' || typeof e.pattern !== 'string') {
      throw new Error(`banned-patterns entry ${index} needs string "name" and "pattern": ${file}`);
    }
    const flags = typeof e.flags === 'string' ? e.flags : 'i';
    try {
      return { name: e.name, pattern: stateless(new RegExp(e.pattern, flags)) };
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(`banned-patterns entry ${index} has an invalid pattern (${detail}): ${file}`);
    }
  });
}

/**
 * The workspace's extra patterns, or none.
 *
 * Every failure degrades to "no extra rules": an unset setting, a missing
 * file, malformed JSON, a bad regex. A patterns file is an *addition* to the
 * guard, and a broken addition must never brick previewing, approving or
 * publishing — the 13 built-in bans still run either way.
 */
export async function workspacePatterns(cfg: Zer0Config): Promise<BannedPattern[]> {
  const configured = cfg.governance.bannedPatternsFile.trim();
  if (configured === '') {
    return [];
  }
  try {
    return await loadWorkspacePatterns(absPath(cfg, configured));
  } catch {
    // Deliberately swallowed — see above. `loadWorkspacePatterns` is the
    // exported path for a caller that wants the reason.
    return [];
  }
}

/** `guardText` with the workspace's extra patterns already loaded. */
export async function guardWithWorkspace(cfg: Zer0Config, text: string): Promise<GuardFinding[]> {
  return guardText(text, { extraPatterns: await workspacePatterns(cfg) });
}
