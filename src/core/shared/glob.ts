/**
 * A glob just big enough for content discovery: `*`, `?`, `**`, and nothing
 * else. No brace expansion, no character classes, no negation — the patterns
 * this CMS meets are `pages/_posts/**\/*.md`-shaped, and a dependency for that
 * is a dependency too many.
 *
 * Two properties matter and are easy to get wrong:
 *
 *  1. **Single-pass translation.** Cascading string replaces (`**` → `.*`,
 *     then `*` → `[^/]*`) rewrite the regex fragments emitted by earlier
 *     steps. The loop below walks the pattern once, left to right.
 *  2. **A static base.** Everything before the first magic character is a
 *     literal directory, so the walk starts there instead of at the workspace
 *     root — which is the difference between reading one folder and reading
 *     `node_modules`.
 *
 * Output is always workspace-relative POSIX, deduplicated and sorted, so two
 * runs on the same tree produce byte-identical lists.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

/**
 * Directories never worth walking into for content.
 *
 * The list is the platform-agnostic half plus Jekyll's `_site`, which is what
 * it has always been. Decision D12 moved the *platform's* share of this
 * question into `PlatformProfile.outputDirs`, and `skipDirsFor(profile, base)`
 * in `core/platform/permalink.ts` composes the two — so a Hugo site skips
 * `public/` and an Astro site skips `dist/` without this constant learning
 * either name. Pass the composed set to `walkGlobs`; this remains the default
 * for every caller that has not resolved a platform yet.
 */
export const SKIP_DIRS: ReadonlySet<string> = new Set([
  'node_modules',
  '.git',
  'dist',
  'out',
  '.vscode-test',
  'vendor',
  '_site',
]);

export interface CompiledGlob {
  /** Literal path prefix before the first magic character; `.` when there is none. */
  base: string;
  /** Anchored regex matching workspace-relative POSIX paths. */
  re: RegExp;
}

/** Backslashes to forward slashes — configured paths may be Windows-flavoured. */
export function toPosix(value: string): string {
  return value.split('\\').join('/');
}

const REGEX_SPECIALS = /[.+^${}()|[\]\\]/;

/** Translate one glob into its static base plus an anchored `RegExp`. */
export function compileGlob(glob: string): CompiledGlob {
  const norm = toPosix(glob).replace(/^\.\//, '');
  const firstMagic = norm.search(/[*?]/);
  const base =
    firstMagic === -1
      ? path.posix.dirname(norm)
      : norm.slice(0, firstMagic).replace(/\/[^/]*$/, '') || '.';

  let source = '';
  for (let i = 0; i < norm.length; i += 1) {
    if (norm.startsWith('**/', i)) {
      // Zero or more directories.
      source += '(?:[^/]+/)*';
      i += 2;
      continue;
    }
    if (norm.startsWith('**', i)) {
      source += '.*';
      i += 1;
      continue;
    }
    const ch = norm.charAt(i);
    if (ch === '*') {
      source += '[^/]*';
    } else if (ch === '?') {
      source += '[^/]';
    } else {
      source += REGEX_SPECIALS.test(ch) ? `\\${ch}` : ch;
    }
  }

  return { base: base === '' ? '.' : base, re: new RegExp(`^${source}$`) };
}

/** Does a workspace-relative POSIX path match any of the compiled globs? */
export function globMatches(relPath: string, globs: readonly CompiledGlob[]): boolean {
  const candidate = toPosix(relPath);
  return globs.some((g) => g.re.test(candidate));
}

async function walk(
  root: string,
  dir: string,
  out: string[],
  skip: ReadonlySet<string>,
): Promise<void> {
  let entries;
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    // A configured folder that does not exist yet is a normal state — an empty
    // result says exactly that, and the caller reports it in its own words.
    return;
  }

  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      // Hidden directories below the base are skipped; a base that *is* hidden
      // (`.zer0/drafts`) still works, because the walk starts inside it.
      if (skip.has(entry.name) || entry.name.startsWith('.')) {
        continue;
      }
      await walk(root, full, out, skip);
    } else if (entry.isFile()) {
      out.push(toPosix(path.relative(root, full)));
    }
  }
}

/**
 * All files under `root` matching any of `globs`, as workspace-relative POSIX
 * paths, deduplicated and sorted.
 *
 * `skip` is the set of directory names the walk refuses to descend into. It is
 * a parameter rather than a constant so a caller that knows the platform can
 * pass `skipDirsFor(profile, SKIP_DIRS)` and keep the generator's build output
 * out of the results; omitting it keeps the historical behaviour exactly.
 */
export async function walkGlobs(
  root: string,
  globs: string[],
  skip: ReadonlySet<string> = SKIP_DIRS,
): Promise<string[]> {
  const compiled = globs.map(compileGlob);
  const bases = [...new Set(compiled.map((c) => c.base))];

  const candidates: string[] = [];
  for (const base of bases) {
    await walk(
      root,
      base === '.' ? root : path.join(root, base.split('/').join(path.sep)),
      candidates,
      skip,
    );
  }

  const matched = new Set<string>();
  for (const candidate of candidates) {
    if (globMatches(candidate, compiled)) {
      matched.add(candidate);
    }
  }
  return [...matched].sort();
}
