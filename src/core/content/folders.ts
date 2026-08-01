/**
 * Where content lives: turning the `contentFolders` entries of `zer0.json`
 * into the concrete directories on disk, and answering the reverse question —
 * which registered folder does *this* file belong to?
 *
 * Two configured spellings need expanding before a path is real:
 *
 *   - **Wildcards.** A path with a star segment — `pages`, star, `posts` —
 *     registers every matching directory as its own folder, titled
 *     `Posts (pages/blog/posts)`. The expansion walks the tree segment by
 *     segment rather than globbing the whole workspace, so a wildcard in the
 *     last segment reads exactly one directory.
 *   - **Date tokens.** `pages/{{year}}/posts` is resolved against the
 *     configured date format and timezone, so a workspace that files content by
 *     year does not need its config edited every January.
 *
 * `[[workspace]]` is *not* handled here: `resolveConfig` has already expanded
 * it, and `ContentFolder.originalPath` keeps whatever the author typed so a
 * round-trip back into `zer0.json` writes their spelling, not ours.
 *
 * The file → folder match is the one piece of behaviour that is deliberately
 * stricter than Front Matter's. FM asked `filePath.includes(folder.path)`,
 * which matches a folder path appearing *anywhere* in the file path and makes
 * `/site/pages` claim `/tmp/copy-of/site/pages/x.md`. Here the folder path has
 * to be a prefix ending on a path boundary, and the longest such prefix wins.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { SKIP_DIRS, toPosix } from '../shared/glob';
import type { ContentFolder, ContentType, Zer0Config } from '../shared/types';
import { hasPlaceholder, processDatePlaceholders, processTimePlaceholders } from './placeholders';

/** How many directory levels a `**` segment may descend before we stop. */
const MAX_WILDCARD_DEPTH = 12;

/** Native path for a POSIX one — a no-op everywhere except Windows. */
function toNative(value: string): string {
  return value.split('/').join(path.sep);
}

function hasMagic(value: string): boolean {
  return value.includes('*') || value.includes('?');
}

/** One path segment as an anchored regex: `*` and `?` are the only magic. */
function segmentPattern(segment: string): RegExp {
  let source = '';
  for (const ch of segment) {
    if (ch === '*') {
      source += '[^/]*';
    } else if (ch === '?') {
      source += '[^/]';
    } else if (/[.+^${}()|[\]\\]/.test(ch)) {
      source += `\\${ch}`;
    } else {
      source += ch;
    }
  }
  return new RegExp(`^${source}$`);
}

async function subdirectories(dirPosix: string, includeHidden: boolean): Promise<string[]> {
  let entries;
  try {
    entries = await fs.readdir(toNative(dirPosix), { withFileTypes: true });
  } catch {
    // A wildcard whose parent does not exist expands to nothing. That is a
    // configuration that has not been created yet, not an error to report.
    return [];
  }

  const out: string[] = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || SKIP_DIRS.has(entry.name)) {
      continue;
    }
    if (!includeHidden && entry.name.startsWith('.')) {
      continue;
    }
    out.push(`${dirPosix}/${entry.name}`);
  }
  return out;
}

async function expandSegments(
  basePosix: string,
  segments: readonly string[],
  depth: number,
): Promise<string[]> {
  const head = segments[0];
  if (head === undefined) {
    return [basePosix];
  }
  const tail = segments.slice(1);

  if (head === '**') {
    if (depth >= MAX_WILDCARD_DEPTH) {
      return [];
    }
    const out = await expandSegments(basePosix, tail, depth);
    for (const child of await subdirectories(basePosix, false)) {
      out.push(...(await expandSegments(child, segments, depth + 1)));
    }
    return out;
  }

  if (!hasMagic(head)) {
    return expandSegments(`${basePosix}/${head}`, tail, depth);
  }

  const re = segmentPattern(head);
  const out: string[] = [];
  for (const child of await subdirectories(basePosix, head.startsWith('.'))) {
    const name = child.slice(child.lastIndexOf('/') + 1);
    if (re.test(name)) {
      out.push(...(await expandSegments(child, tail, depth)));
    }
  }
  return out;
}

/** Every existing directory matching an absolute wildcard path, sorted. */
async function directoriesMatching(pattern: string): Promise<string[]> {
  const posix = toPosix(pattern);
  const segments = posix.split('/');
  const firstMagic = segments.findIndex(hasMagic);
  if (firstMagic === -1) {
    return [posix];
  }
  const base = segments.slice(0, firstMagic).join('/');
  const expanded = await expandSegments(base === '' ? '/' : base, segments.slice(firstMagic), 0);
  return [...new Set(expanded)].sort();
}

/**
 * The configured folders, made concrete: wildcards expanded to the directories
 * that exist, date tokens resolved, titles filled in from the basename, and
 * `originalPath` preserved for every entry.
 *
 * A folder that simply does not exist yet is still returned — creating it is
 * the shell's decision to offer, not this module's to make. Duplicate paths
 * (two config entries expanding onto the same directory) are collapsed, first
 * declaration winning, so nothing is scanned or listed twice.
 */
export async function resolveFolders(cfg: Zer0Config): Promise<ContentFolder[]> {
  const out: ContentFolder[] = [];
  const seen = new Set<string>();

  const push = (folder: ContentFolder): void => {
    const key = toPosix(folder.path);
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    out.push(folder);
  };

  for (const folder of cfg.contentFolders) {
    if (!folder.path) {
      continue;
    }
    const original = folder.originalPath ?? folder.path;

    if (hasMagic(folder.path)) {
      const roots = toPosix(cfg.workspaceRoot);
      for (const match of await directoriesMatching(folder.path)) {
        const relative = match.startsWith(roots) ? match.slice(roots.length + 1) : match;
        push({
          ...folder,
          title: `${folder.title || path.posix.basename(match)} (${relative})`,
          path: toNative(match),
          originalPath: original,
        });
      }
      continue;
    }

    // Only the date vocabulary is resolved here: a folder path is read on every
    // refresh, and running the custom placeholders would mean spawning a
    // subprocess to answer "where does content live?".
    const resolved = hasPlaceholder(folder.path)
      ? processDatePlaceholders(processTimePlaceholders(folder.path, cfg), cfg)
      : folder.path;

    push({
      ...folder,
      title: folder.title || path.basename(resolved),
      path: resolved,
      originalPath: original,
    });
  }

  return out;
}

/** Is `filePath` inside `folderPath`, matching on whole path segments? */
function prefixLength(folderPath: string, filePath: string): number {
  const folder = toPosix(folderPath).replace(/\/+$/, '');
  const file = toPosix(filePath);

  if (hasMagic(folder)) {
    // A folder registered by wildcard is matched against the pattern itself, so
    // `folderForFile` still answers before `resolveFolders` has run.
    const segments = folder.split('/');
    const fileSegments = file.split('/');
    if (fileSegments.length <= segments.length) {
      return 0;
    }
    for (let i = 0; i < segments.length; i += 1) {
      const segment = segments[i];
      const candidate = fileSegments[i];
      if (segment === undefined || candidate === undefined) {
        return 0;
      }
      if (segment === '**') {
        // Only a trailing `**` is meaningful for a prefix test; anything after
        // it cannot be aligned segment by segment.
        return folder.length;
      }
      if (!segmentPattern(segment).test(candidate)) {
        return 0;
      }
    }
    return folder.length;
  }

  if (file === folder) {
    return folder.length;
  }
  return file.startsWith(`${folder}/`) ? folder.length : 0;
}

/**
 * The registered folder that owns this file — the longest matching prefix, so
 * `pages/_posts/tech` wins over `pages/_posts` for a file inside both.
 * `undefined` when the file lives outside every registered folder.
 */
export function folderForFile(
  folders: readonly ContentFolder[],
  filePath: string,
): ContentFolder | undefined {
  let best: ContentFolder | undefined;
  let bestLength = 0;

  for (const folder of folders) {
    if (!folder.path) {
      continue;
    }
    const length = prefixLength(folder.path, filePath);
    if (length > bestLength) {
      best = folder;
      bestLength = length;
    }
  }

  return best;
}

/**
 * The filename-prefix *template* for new content, before placeholders run.
 *
 * The chain is workspace default → folder → content type, each level
 * overriding the one before it when it declares the key at all. Declaring it as
 * `null` or `""` is a real answer meaning "no prefix here", which is why the
 * test is `!== undefined` rather than a truthiness check: a folder must be able
 * to switch off a prefix the workspace turned on.
 *
 * The legacy literal `yyyy-MM-dd` is rewritten to `{{date|yyyy-MM-dd}}` —
 * without it, a date-shaped prefix would be taken as a literal filename.
 */
export function filePrefixFor(
  cfg: Zer0Config,
  folder: ContentFolder | undefined,
  ct: ContentType | undefined,
): string {
  let prefix: string | null | undefined = cfg.content.filePrefix;

  if (folder !== undefined && folder.filePrefix !== undefined) {
    prefix = folder.filePrefix;
  }
  if (ct !== undefined && ct.filePrefix !== undefined) {
    prefix = ct.filePrefix;
  }

  if (prefix === null || prefix === undefined || prefix === '') {
    return '';
  }
  return prefix === 'yyyy-MM-dd' ? '{{date|yyyy-MM-dd}}' : prefix;
}
