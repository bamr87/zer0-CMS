/**
 * `.claude/skills/<name>/SKILL.md` — the procedures an agent is told to follow.
 *
 * A skill is a directory with a `SKILL.md` in it; its front matter carries a
 * `name` (which must equal the directory) and a `description` that doubles as
 * the trigger list — "Use when asked to …", "Triggers on: …". Nothing joins a
 * workflow to a skill except prose: the workflow's prompt says *use the X
 * skill*, and the agent file says the same. So the description is where the
 * trigger phrases have to be mined from, and `triggerPhrases` is exactly that
 * mining, kept honest by being quoted material rather than a paraphrase.
 *
 * ### `_shared/` is not a skill, and the two counters disagree about it
 *
 * `.claude/skills/_shared/` holds `quarantine.md` — the guardrails every agent
 * cites for reading untrusted text. It is not a skill: it has no `SKILL.md`, no
 * name, and no trigger. lifehacker's `scripts/ci/lint_agents.rb` excludes it
 * from its skill count; `wtd fleet adopt`, which derives a manifest by counting
 * directories, includes it. For lifehacker.dev that is 16 against 17 — the same
 * repository, two numbers, both correct under their own definition.
 *
 * `skillCountsFor` therefore reports **both**, and nothing in this console
 * silently picks a winner. A scorecard that showed one number would be telling
 * a repository its own lint is wrong.
 */

import { asString, splitFrontMatter } from '../content/frontmatter';
import type { SkillRecord } from '../shared/types';
import { SHARED_SKILL_DIR, type HarnessIo } from './agents';

/** Where a repository keeps its skills, relative to its root. */
export const SKILLS_DIR = '.claude/skills';

/** The file that makes a directory a skill. */
export const SKILL_FILE = 'SKILL.md';

export { SHARED_SKILL_DIR };

/** The directory a skill file sits in — `.claude/skills/foo/SKILL.md` → `foo`. */
export function skillDirOf(filePath: string): string {
  const parts = filePath.replace(/\\/g, '/').split('/');
  return parts.length >= 2 ? (parts[parts.length - 2] ?? '') : '';
}

/**
 * The phrases a person would say to invoke this skill.
 *
 * Two sources, both verbatim from the description: any quoted phrase (every
 * house writes its triggers as `"crawl the news sources"`, `'run the loop'`),
 * and the comma-separated list after a `Triggers on:` label. Nothing is
 * invented — an empty list means the description never said.
 */
export function readTriggerPhrases(description: string): string[] {
  const out: string[] = [];
  const quoted = /["“']([^"”']{3,80})["”']/g;
  let match = quoted.exec(description);
  while (match !== null) {
    const phrase = match[1]?.trim();
    if (phrase !== undefined && phrase.length > 0) {
      out.push(phrase);
    }
    match = quoted.exec(description);
  }
  const labelled = /Triggers on:\s*([^.]+)/i.exec(description);
  if (labelled?.[1] !== undefined) {
    for (const piece of labelled[1].split(',')) {
      const phrase = piece.trim();
      if (phrase.length > 0) {
        out.push(phrase);
      }
    }
  }
  const seen = new Set<string>();
  return out.filter((phrase) => {
    const key = phrase.toLowerCase();
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

/** Parse one `SKILL.md`. Never throws; an unparseable file yields empty fields. */
export function parseSkillFile(filePath: string, text: string): SkillRecord {
  const { block } = splitFrontMatter(text);
  const data = block?.data ?? {};
  const dir = skillDirOf(filePath);
  const declared = asString(data['name']).trim();
  const description = asString(data['description']).trim();
  return {
    name: declared.length > 0 ? declared : dir,
    path: filePath,
    description,
    triggerPhrases: readTriggerPhrases(description),
    nameMatchesDir: declared === dir,
  };
}

/** The two counts, computed from the directory listing and the parsed skills. */
export function skillCountsFor(dirNames: readonly string[]): {
  lintAgents: number;
  wtdAdopt: number;
} {
  const dirs = dirNames.filter((name) => !name.startsWith('.'));
  return {
    // lifehacker's lint counts skill directories and excludes `_shared`.
    lintAgents: dirs.filter((name) => name !== SHARED_SKILL_DIR).length,
    // `wtd fleet adopt` counts every directory under `.claude/skills/`.
    wtdAdopt: dirs.length,
  };
}

/**
 * Every skill a repository declares, plus both counts.
 *
 * A directory without a `SKILL.md` is not a skill and is absent from `skills`,
 * but it still counts toward `counts.wtdAdopt` — that is the disagreement this
 * module exists to preserve rather than resolve.
 */
export async function readSkills(
  io: HarnessIo,
  dir: string = SKILLS_DIR,
): Promise<{ skills: SkillRecord[]; counts: { lintAgents: number; wtdAdopt: number } }> {
  const entries = await io.list(dir);
  const skills: SkillRecord[] = [];
  for (const entry of entries.filter((name) => !name.startsWith('.')).sort()) {
    if (entry === SHARED_SKILL_DIR) {
      continue;
    }
    const rel = `${dir}/${entry}/${SKILL_FILE}`;
    const text = await io.read(rel);
    if (text !== undefined) {
      skills.push(parseSkillFile(rel, text));
    }
  }
  return { skills, counts: skillCountsFor(entries) };
}
