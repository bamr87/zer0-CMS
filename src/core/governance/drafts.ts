/**
 * The governed draft queue — the folder a human (or the agent, through the MCP
 * `zer0_draft` tool) puts proposed content into, and the only place publishing
 * ever reads from.
 *
 * Front-matter dialect, kept deliberately small and shared with the Python
 * lane: `type` (`article` | `update`, with `text` accepted as an alias of
 * `update`; default `article`), `status` (`pending` | `approved` |
 * `published`; default `pending`), `source` (a reference to the content this
 * draft came from), informational `title` / `description` / `link`, and an
 * optional `no_thumbnail`. **The body is the content that publishes.** Keys
 * from other dialects (`kind`, `audience`, `content_path`, …) are read back
 * out untouched, because parsing and writing are asymmetric here on purpose:
 * nothing in this module ever re-serialises a file it did not create.
 *
 * That asymmetry is the point. `markStatus` flips one line and leaves every
 * other byte alone, so approving a draft is a one-line diff in review — not a
 * whole-file requote from a YAML dumper. See decision D7.
 *
 * Lifecycle: `writeDraft` can only ever write `status: pending`; the local
 * approval gate flips it to `approved`; a successful publish flips it to
 * `published`. There is no code path that writes an already-approved draft.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { asBool, asString, splitFrontMatter, type FrontMatter } from '../content/frontmatter';
import { quoteScalar } from '../content/serialize';

export const STATUS_PENDING = 'pending';
export const STATUS_APPROVED = 'approved';
export const STATUS_PUBLISHED = 'published';

/** The three statuses the queue understands, in lifecycle order. */
export const DRAFT_STATUSES: readonly string[] = [STATUS_PENDING, STATUS_APPROVED, STATUS_PUBLISHED];

/** `article` becomes a page; `update` is free text with no canonical identity. */
export type DraftType = 'article' | 'update';

export interface DraftFile {
  /** Absolute path of the draft file. */
  path: string;
  meta: FrontMatter;
  body: string;
  /** `meta.status`, lowercased; defaults to `pending`. */
  status: string;
  /** `meta.type`, lowercased, with `text` normalised to `update`; defaults to `article`. */
  type: string;
}

/**
 * Split a draft into front matter and body. A file with no front matter yields
 * `{ meta: {}, body: <the whole file> }` — that is how a `README.md` living in
 * the queue folder identifies itself as documentation rather than a draft.
 */
export function parseDraft(text: string): { meta: FrontMatter; body: string } {
  const { block, body } = splitFrontMatter(text);
  return { meta: block === null ? {} : { ...block.data }, body };
}

/** `text` is an accepted spelling of `update`; anything else passes through. */
export function normalizeType(value: string): string {
  const lowered = value.trim().toLowerCase();
  if (lowered === '') {
    return 'article';
  }
  return lowered === 'text' ? 'update' : lowered;
}

export async function readDraft(filePath: string): Promise<DraftFile> {
  const { meta, body } = parseDraft(await fs.readFile(filePath, 'utf8'));
  return {
    path: filePath,
    meta,
    body,
    status: asString(meta.status, STATUS_PENDING).trim().toLowerCase() || STATUS_PENDING,
    type: normalizeType(asString(meta.type)),
  };
}

/**
 * Every draft in the queue: top-level `*.md` files only, sorted by filename.
 *
 * Files with zero front-matter keys are skipped. The queue folder is a normal
 * directory somebody will drop a `README.md` into, and "has no front matter"
 * is the cheapest honest test for "this is prose about the queue, not an item
 * in it". A missing folder is a normal state (nothing drafted yet) and yields
 * an empty list, never an error.
 */
export async function listQueue(dir: string): Promise<DraftFile[]> {
  let names: string[];
  try {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    names = entries.filter((e) => e.isFile() && e.name.endsWith('.md')).map((e) => e.name);
  } catch {
    // No queue folder yet — the normal state of a workspace that has never
    // drafted anything. The caller renders an empty queue, not an error.
    return [];
  }
  names.sort();

  const out: DraftFile[] = [];
  for (const name of names) {
    const draft = await readDraft(path.join(dir, name));
    if (Object.keys(draft.meta).length === 0) {
      continue;
    }
    out.push(draft);
  }
  return out;
}

/** The text that would publish: the body, else a `commentary` key. */
export function commentaryOf(draft: DraftFile): string {
  return draft.body.trim() || asString(draft.meta.commentary).trim();
}

/**
 * Suppress the preview image for this draft.
 *
 * BASH-CMS reproduced a Python quirk here (`no_thumbnail: false` counted as
 * true, because its parser only ever produced strings). This parser coerces
 * booleans, so the key means what it says.
 */
export function noThumbnail(draft: DraftFile): boolean {
  return asBool(draft.meta.no_thumbnail);
}

/** The draft's own title, if it carries one. */
export function titleOf(draft: DraftFile): string {
  return asString(draft.meta.title).trim();
}

/** The draft's own description, if it carries one. */
export function descriptionOf(draft: DraftFile): string {
  return asString(draft.meta.description).trim();
}

/** The reference to the content this draft came from (`source`), if any. */
export function sourceOf(draft: DraftFile): string {
  return asString(draft.meta.source).trim();
}

/** An external link carried by the draft, if any. */
export function linkOf(draft: DraftFile): string {
  return asString(draft.meta.link).trim();
}

/** The draft's filename without its extension — its stable local identity. */
export function slugOf(draft: DraftFile): string {
  return path.basename(draft.path).replace(/\.md$/i, '');
}

/** Keys written as `key: "value"`; everything else is emitted bare. */
const QUOTED_KEYS: ReadonlySet<string> = new Set(['title', 'description', 'link', 'source']);

export interface NewDraft {
  type: DraftType;
  /** Filename stem; collisions resolve to `<slug>-2`, `-3`, … */
  slug: string;
  body: string;
  source?: string;
  title?: string;
  description?: string;
  link?: string;
  /** Extra front-matter keys, emitted verbatim after the known ones. */
  extras?: Record<string, string>;
}

async function exists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    // `access` fails for "missing" and for "no permission" alike. Both mean
    // "do not claim this name is free", and the write below reports the real
    // error if it is the second one.
    return false;
  }
}

/**
 * Write a new draft into the queue and return its absolute path.
 *
 * The status is **always** `pending`: creating a draft and approving a draft
 * are different acts, and only the second one is a human decision. A name
 * collision resolves to `<slug>-2.md`, `<slug>-3.md`, … rather than
 * overwriting, because the queue is append-only from this direction.
 *
 * Key order is fixed (`type`, `status`, `source`, `title`, `description`,
 * `link`, then extras) so two drafts written a month apart diff cleanly.
 */
export async function writeDraft(dir: string, draft: NewDraft): Promise<string> {
  await fs.mkdir(dir, { recursive: true });

  let dest = path.join(dir, `${draft.slug}.md`);
  for (let n = 2; await exists(dest); n += 1) {
    dest = path.join(dir, `${draft.slug}-${n}.md`);
  }

  const meta: Record<string, string> = { type: draft.type, status: STATUS_PENDING };
  if (draft.source) {
    meta.source = draft.source;
  }
  if (draft.title) {
    meta.title = draft.title;
  }
  if (draft.description) {
    meta.description = draft.description;
  }
  if (draft.link) {
    meta.link = draft.link;
  }
  for (const [key, value] of Object.entries(draft.extras ?? {})) {
    // `status` is not overridable — see the note above.
    if (key !== 'status') {
      meta[key] = value;
    }
  }

  const lines = ['---'];
  for (const [key, value] of Object.entries(meta)) {
    // quoteScalar, not a local escape: it handles backslashes as well as
    // quotes. A title ending in `\` would otherwise emit `"…\"`, whose closing
    // quote reads as escaped — the string runs on and eats the rest of the block.
    lines.push(QUOTED_KEYS.has(key) ? `${key}: ${quoteScalar(value)}` : `${key}: ${value}`);
  }
  lines.push('---');

  await fs.writeFile(dest, `${lines.join('\n')}\n\n${draft.body.trim()}\n`, 'utf8');
  return dest;
}

/**
 * Flip the `status:` line in place, preserving every other byte of the file.
 *
 * Exactly one line changes: the first whose trimmed, lowercased form starts
 * with `status:`. A draft that carries no status line at all gets one inserted
 * directly after the opening fence — silently doing nothing would leave the
 * queue claiming a draft is still pending after a successful publish.
 *
 * Not an atomic write: this is a file a human may have open in an editor, and
 * replacing its inode detaches editors and watchers from it (see
 * `content/article.ts`). Ledgers get atomic writes; drafts do not.
 */
export async function markStatus(filePath: string, status: string): Promise<void> {
  const text = await fs.readFile(filePath, 'utf8');
  const lines = text.split(/\r\n|\r|\n/);
  const next = `status: ${status.trim()}`;

  const out: string[] = [];
  let replaced = false;
  for (const line of lines) {
    if (!replaced && line.trim().toLowerCase().startsWith('status:')) {
      out.push(next);
      replaced = true;
    } else {
      out.push(line);
    }
  }

  if (!replaced) {
    const fence = out.findIndex((line) => line.trim() === '---');
    if (fence === -1) {
      // No front matter to hold a status: prepend a block rather than write a
      // `status:` line into the body, where nothing would ever read it.
      out.unshift('---', next, '---', '');
    } else {
      out.splice(fence + 1, 0, next);
    }
  }

  await fs.writeFile(filePath, `${out.join('\n').replace(/\n*$/, '')}\n`, 'utf8');
}
