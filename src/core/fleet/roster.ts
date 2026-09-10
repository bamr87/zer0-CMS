/**
 * The roster: which repositories this console is operating.
 *
 * Slice 1 was one repository — the folder you had open. Slice 2 is a fleet, and
 * a fleet arrives from three places at once, so this module reads each of them
 * and then says which wins.
 *
 * **The precedence is `workspace` > `settings` > `hub`, and it is about what
 * can be read without a socket.** A folder open in this window is a checkout on
 * disk: its manifest, its workflows and its `_data/` are readable now, offline,
 * at whatever commit is checked out. A settings entry is a repository a person
 * named on purpose. A hub entry is one the registry imported on their behalf.
 * When the same repository arrives twice, the record that keeps its local root
 * is the useful one, so it wins — and the loser is still allowed to contribute
 * the one field it may know better, the tracked branch.
 *
 * Deduping is case-insensitive on the slug because GitHub is: `bamr87/It-Journey`
 * and `bamr87/it-journey` are one repository, and a roster that listed both
 * would make two of every row on the screen.
 *
 * Everything here is pure and total. A malformed registry, a rejected setting
 * and an empty list are all normal states — the reader reports them and never
 * throws, for the same reason `.cms/` absence is a state rather than an error.
 */

import { parseYamlSubset } from '../content/frontmatter';
import type { FleetRosterEntry } from '../shared/types';
import { FLEET_MANIFEST_FILE } from './manifest';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asText(value: unknown): string {
  return value === undefined || value === null ? '' : String(value);
}

/** `owner/name`, tolerating a clone URL, a trailing `.git` and surrounding noise. */
export function rosterSlugOf(raw: string): string | undefined {
  const text = raw.trim().replace(/\.git$/i, '').replace(/\/+$/, '');
  const url = /^(?:https?:\/\/|git@)(?:www\.)?github\.com[/:]+(.+)$/i.exec(text);
  const candidate = url === null ? text : (url[1] ?? '');
  return /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(candidate) ? candidate : undefined;
}

// ---------------------------------------------------------------------------
// The hub registry
// ---------------------------------------------------------------------------

/**
 * `bamr87/bamr87` `_data/projects.yml` — the fleet's project registry, and the
 * join key every dash surface already uses.
 *
 * The file is a document-level YAML **sequence**, which `parseYamlSubset` will
 * not read (front matter is a mapping, so it refuses a top-level list on
 * purpose). Indenting every line by two and giving it a synthetic key turns it
 * into a mapping whose one value is that sequence, without touching a byte of
 * the content: relative indentation, block scalars and comments all survive,
 * and the audited parser does the work rather than a second hand-rolled one.
 *
 * Only four fields are read — the repository URL, the branch, the status and
 * the name — because those are the four the roster needs. Everything else the
 * registry carries (stack, category, release, schema, conformance) belongs to
 * the hub's own surfaces.
 *
 * **`status: archived` entries are dropped.** The roster is a list of things to
 * operate, and an archived repository has no automation left to operate; the
 * hub itself renders them separately. Nothing else is filtered: a repository
 * that is external, unmaintained or experimental is still a repository somebody
 * may want to look at.
 */
export function parseProjectsRegistry(text: string): FleetRosterEntry[] {
  const indented = text
    .split('\n')
    .map((line) => (line.length === 0 ? line : `  ${line}`))
    .join('\n');
  const parsed = parseYamlSubset(`projects:\n${indented}`).projects;
  if (!Array.isArray(parsed)) {
    return [];
  }
  const entries: FleetRosterEntry[] = [];
  for (const raw of parsed) {
    const project = asRecord(raw);
    if (project === undefined || asText(project.status) === 'archived') {
      continue;
    }
    const slug = rosterSlugOf(asText(project.repo_url));
    if (slug === undefined) {
      continue;
    }
    const branch = asText(project.branch);
    entries.push({
      slug,
      source: 'hub',
      localRoot: null,
      manifestPath: FLEET_MANIFEST_FILE,
      branch: branch === '' ? null : branch,
    });
  }
  return dedupe(entries);
}

// ---------------------------------------------------------------------------
// The setting
// ---------------------------------------------------------------------------

/**
 * `zer0Cms.fleet.roster` — the repositories a person named themselves.
 *
 * Rejections come back as a list rather than being swallowed, because a typo in
 * a settings array is invisible otherwise: the row simply never appears, and
 * "my repository is missing" is a much worse bug report than "this entry was
 * not `owner/name`".
 *
 * The setting is read through `settingsFleetRoster()` — the VS Code settings
 * layer alone. A `zer0.json` arriving with a cloned repository cannot add a
 * repository to the roster, for the same reason it cannot arm a dispatch.
 */
export function parseRosterSetting(values: readonly string[]): {
  entries: FleetRosterEntry[];
  rejected: string[];
} {
  const entries: FleetRosterEntry[] = [];
  const rejected: string[] = [];
  for (const value of values) {
    const slug = rosterSlugOf(value);
    if (slug === undefined) {
      rejected.push(value);
      continue;
    }
    entries.push({
      slug,
      source: 'settings',
      localRoot: null,
      manifestPath: FLEET_MANIFEST_FILE,
      branch: null,
    });
  }
  return { entries: dedupe(entries), rejected };
}

// ---------------------------------------------------------------------------
// The union
// ---------------------------------------------------------------------------

/** Higher wins. Declared as data so the precedence is one line to read. */
const SOURCE_RANK: Readonly<Record<FleetRosterEntry['source'], number>> = {
  workspace: 3,
  settings: 2,
  hub: 1,
};

/** Case-insensitive dedupe on the slug, first occurrence kept. */
function dedupe(entries: readonly FleetRosterEntry[]): FleetRosterEntry[] {
  const seen = new Set<string>();
  const out: FleetRosterEntry[] = [];
  for (const entry of entries) {
    const key = entry.slug.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    out.push(entry);
  }
  return out;
}

/**
 * Union any number of rosters into one.
 *
 * Order of the result is first-appearance order across the lists as given, so a
 * caller that passes the open folders first gets them first. Which *record*
 * survives for a slug is decided by `source` and not by argument order —
 * `workspace` beats `settings` beats `hub` however the lists were arranged, so
 * a caller cannot accidentally demote its own checkout by passing it last.
 *
 * The one field that crosses from a losing record is `branch`: the hub registry
 * knows the tracked branch of a repository this window has no checkout of, and
 * a winner that says `null` there is admitting it does not know rather than
 * asserting there is none. `localRoot` never crosses — a root is what makes an
 * entry a workspace entry, and copying one onto a settings record would make
 * the `source` field a lie.
 *
 * Pure: the input arrays and their entries are never mutated.
 */
export function mergeFleetRoster(
  ...lists: readonly (readonly FleetRosterEntry[])[]
): FleetRosterEntry[] {
  const order: string[] = [];
  const best = new Map<string, FleetRosterEntry>();
  const branches = new Map<string, string>();

  for (const list of lists) {
    for (const entry of list) {
      const key = entry.slug.toLowerCase();
      if (!best.has(key)) {
        order.push(key);
      }
      if (entry.branch !== null && entry.branch !== '' && !branches.has(key)) {
        branches.set(key, entry.branch);
      }
      const incumbent = best.get(key);
      if (incumbent === undefined || SOURCE_RANK[entry.source] > SOURCE_RANK[incumbent.source]) {
        best.set(key, entry);
      }
    }
  }

  // `order` is filled from the same loop that fills `best`, so every key has a
  // winner; the `flatMap` skips rather than asserts, because a total function
  // that cannot throw is easier to reason about than one that says it will not.
  return order.flatMap((key) => {
    const winner = best.get(key);
    if (winner === undefined) {
      return [];
    }
    const branch = winner.branch ?? branches.get(key) ?? null;
    return [branch === winner.branch ? winner : { ...winner, branch }];
  });
}
