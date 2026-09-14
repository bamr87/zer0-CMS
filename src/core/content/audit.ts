/**
 * The site-wide front-matter audit, and the fix-it that never writes.
 *
 * Decision D-D. `auditPage` checks one file, `auditSite` checks a whole site,
 * `fixFor` proposes a change set for the findings a script can honestly repair,
 * and `dryRunFix` renders the before/after through the ordinary line-surgery
 * path **without touching the disk**. Pure Node, no I/O of its own.
 *
 * ## The rule ids are somebody else's, on purpose
 *
 * Every id in `AUDIT_RULE_IDS` is lifehacker.dev's, spelled the way
 * `scripts/ci/lint_frontmatter.rb` spells it — `missing-key:<k>`,
 * `invalid-date`, `future-date`, `filename-date-mismatch`, `tags-not-array`,
 * `no-front-matter`, `description-too-long`. That site files a GitHub issue per
 * finding; so does this console's triage lane. If the two vocabularies drifted
 * by one character the same problem would be filed twice and closed once. A
 * rule id is a contract with another repository, not a local label.
 *
 * ## Honesty under D9
 *
 * The audit reports what it can check and stays quiet about what it cannot. It
 * never computes a health score — `SiteAudit` has no such field, and
 * `pageToRecord` keeps `health: -1` beside these issues rather than deriving a
 * number from them. Three places where the quiet answer is the right one:
 *
 *   - **A block the parser could not read reports that, and nothing else.**
 *     `FmBlock.warnings` is the channel. When it is non-empty every key check
 *     is suppressed for that file, because `defaults: &series` reaching the
 *     parser as the literal string `'&series'` would otherwise produce a
 *     confident `missing-key` for every key the anchor was meant to supply.
 *   - **`unknown-key` needs a closed vocabulary.** It fires only when a site
 *     declared an `optional` list in a real schema file. A site that declared
 *     nothing is not thereby a site where every key is unknown.
 *   - **A length rule needs a declared cap.** The SEO panel's own defaults are
 *     a budget, not a gate; turning one into a finding on every page is noise
 *     wearing a rule's clothes.
 *
 * ## Dates stay strings (D7)
 *
 * Nothing here parses a front-matter date into a `Date` and writes it back.
 * `invalid-date` matches a shape and then checks the calendar arithmetically;
 * `future-date` compares the leading `YYYY-MM-DD` of two strings, which is
 * exactly what an ISO date is for. The only `Date` in this module is the `now`
 * the caller passed, read for today's date and never round-tripped through a
 * value that came out of somebody's file. That is the difference between an
 * audit and a mass timezone shift.
 *
 * ## Mechanical versus substantive
 *
 * The lane split is `.cms/`'s (see `../contract/README.md`): `mechanical` means
 * a script can fix it, `substantive` means a person has to. It is decided by
 * whether `fixFor` can derive the value **from the file itself** — the date in
 * its own name, the slug of its own title, a default its own content type
 * declares. Populating `title`, `description` or `author` is substantive
 * however easy it looks, because choosing a value is judgment, and writing
 * `title: ''` is the same violation in quieter clothes rather than a fix.
 */

import { toPosix } from '../shared/glob';
import type {
  AuditIssue,
  AuditRuleId,
  ContentType,
  Field,
  Lane,
  LogSink,
  PageEntry,
  PlatformProfile,
  Severity,
  SiteAudit,
  SiteSchema,
  Zer0Config,
} from '../shared/types';
import type { Article } from './article';
import { resolveContentType } from './contentType';
import { emptyValueFor, findField, isEmpty } from './fields';
import type { FmBlock, FmValue, FrontMatter } from './frontmatter';
import { asList, asString, isYamlSequenceItem, ownValue, parseYamlKeyLine } from './frontmatter';
import { collectionSchemaFor, requiredKeysFor, toFrontMatterValue } from './schema';
import type { KeyChange } from './serialize';
import { serializeOptions, stitch, updateFrontMatterKeys } from './serialize';
import { createSlug } from './slug';

// ---------------------------------------------------------------------------
// The rule table
// ---------------------------------------------------------------------------

export interface AuditRuleSpec {
  severity: Severity;
  /** The lane a finding of this rule lands in unless the fix says otherwise. */
  lane: Lane;
  /** One line, for a tooltip and for this file's own documentation. */
  what: string;
}

/**
 * Severity and lane per rule, as data so a test and a UI read the same table.
 *
 * The severities follow lifehacker's lint where it has an opinion: a missing
 * required key, an unparseable or future date, a filename that disagrees with
 * its own front matter and a non-list `tags` all block that site's merge gate,
 * so they are errors here. Its style nits are warnings there and warnings here.
 * `missing-key`'s lane is overridden per finding by `fixFor`.
 */
export const AUDIT_RULE_SPECS: Readonly<Record<AuditRuleId, AuditRuleSpec>> = {
  'missing-key': {
    severity: 'error',
    lane: 'substantive',
    what: 'a key the collection requires is missing or empty',
  },
  'invalid-date': {
    severity: 'error',
    lane: 'substantive',
    what: 'a date key holds something that is not a date',
  },
  'future-date': {
    severity: 'error',
    lane: 'substantive',
    what: 'the publish date is after today, so the page will not build',
  },
  'filename-date-mismatch': {
    severity: 'error',
    lane: 'substantive',
    what: "the date in the filename and the date in the front matter disagree",
  },
  'tags-not-array': {
    severity: 'error',
    lane: 'mechanical',
    what: 'a taxonomy key holds a scalar where the site expects a list',
  },
  'unknown-choice': {
    severity: 'warning',
    lane: 'substantive',
    what: 'a value outside the choices the site declared for that key',
  },
  'title-too-long': {
    severity: 'warning',
    lane: 'substantive',
    what: 'the title is longer than the cap the site declared',
  },
  'description-too-long': {
    severity: 'warning',
    lane: 'substantive',
    what: 'the description is longer than the cap the site declared',
  },
  'unknown-key': {
    severity: 'info',
    lane: 'substantive',
    what: 'a key the collection schema names neither required nor optional',
  },
  'duplicate-slug': {
    severity: 'error',
    lane: 'substantive',
    what: 'two pages in one collection resolve to the same slug',
  },
  'duplicate-permalink': {
    severity: 'error',
    lane: 'substantive',
    what: 'two pages declare the same permalink',
  },
  'unreadable-frontmatter': {
    severity: 'warning',
    lane: 'substantive',
    what: 'the parser met a construct it cannot read, so this block is not vouched for',
  },
  'no-front-matter': {
    severity: 'error',
    lane: 'substantive',
    what: 'the file has no parseable front-matter block',
  },
};

/** Rules `fixFor` can ever answer for. Everything else returns `null`. */
const FIXABLE_RULES: ReadonlySet<AuditRuleId> = new Set<AuditRuleId>(['missing-key', 'tags-not-array']);

// ---------------------------------------------------------------------------
// Small readers over a page's projected front matter
// ---------------------------------------------------------------------------

/**
 * `PageEntry.data` as front matter. The index types it `Record<string, unknown>`
 * because it crosses a cache boundary; the values in it came out of this
 * module's own parser, and `toFrontMatterValue` re-establishes that structurally
 * rather than by assertion.
 */
export function pageFrontMatter(page: PageEntry): FrontMatter {
  const out: FrontMatter = {};
  for (const [key, value] of Object.entries(page.data)) {
    const converted = toFrontMatterValue(value);
    if (converted !== undefined) {
      out[key] = converted;
    }
  }
  return out;
}

/**
 * lifehacker's `present?`, exactly: `nil` is absent, anything that answers
 * `empty?` is absent when it is empty, and everything else is present. `false`
 * and `0` are values, not absences.
 */
function present(data: FrontMatter, key: string): boolean {
  const value = ownValue(data, key);
  if (value === undefined || value === null) {
    return false;
  }
  if (typeof value === 'string') {
    return value.trim().length > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === 'object') {
    return Object.keys(value).length > 0;
  }
  return true;
}

/** The first of `keys` this page carries as a non-empty string. */
function firstString(data: FrontMatter, keys: readonly string[]): { key: string; value: string } | undefined {
  for (const key of keys) {
    if (!present(data, key)) {
      continue;
    }
    const value = asString(ownValue(data, key)).trim();
    if (value.length > 0) {
      return { key, value };
    }
  }
  return undefined;
}

/** The collection this page sits in, as its content folder names it. */
function collectionNameOf(page: PageEntry): string {
  const folder = toPosix(page.folder).replace(/\/+$/, '');
  return folder.split('/').pop() ?? '';
}

/** The page's own directory, workspace-relative. `''` at the root. */
function directoryOf(page: PageEntry): string {
  const parts = toPosix(page.relPath).split('/');
  parts.pop();
  return parts.join('/');
}

/** The filename stem, lowercased — `2026-01-01-x.md` → `2026-01-01-x`. */
function stemOf(page: PageEntry): string {
  const base = toPosix(page.relPath).split('/').pop() ?? '';
  return base.replace(/\.[^./]+$/, '').toLowerCase();
}

// ---------------------------------------------------------------------------
// Dates, without ever building one
// ---------------------------------------------------------------------------

const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DATE_TIME_RE =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})?$/;

function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) {
    return isLeapYear(year) ? 29 : 28;
  }
  return month === 4 || month === 6 || month === 9 || month === 11 ? 30 : 31;
}

/**
 * The `YYYY-MM-DD` a date value starts with, or `null` when the text is not a
 * date this reader recognises **or** names a day that does not exist.
 *
 * The value is never converted: what comes back is a slice of the string that
 * was already there. Two shapes are accepted, and they are the two every
 * generator in this fleet writes — a bare date, and a date with a time and an
 * optional zone (`T` or a space, `Z` or `±HH:MM` or `±HHMM`).
 */
export function datePartOf(value: FmValue | undefined): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  const text = value.trim();
  const match = DATE_ONLY_RE.exec(text) ?? DATE_TIME_RE.exec(text);
  if (match === null) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) {
    return null;
  }
  return text.slice(0, 10);
}

/** Today, in the caller's own timezone — the same day a person sees on a calendar. */
function todayPart(now: Date): string {
  const pad = (value: number): string => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** The date in a filename, per the profile's own rule, as `YYYY-MM-DD`. */
export function filenameDateOf(profile: PlatformProfile, filePath: string): string | null {
  const base = toPosix(filePath).split('/').pop() ?? '';
  const rule = profile.frontMatter.filenameDate;
  if (rule === null) {
    return null;
  }
  // A profile's RegExp may carry `g`, whose `lastIndex` would make the second
  // call on the same object answer differently from the first.
  const stateless = new RegExp(rule.source, rule.flags.replace(/[gy]/g, ''));
  const matched = stateless.exec(base);
  if (matched === null) {
    return null;
  }
  const parts = /(\d{4})-(\d{2})-(\d{2})/.exec(matched[0]);
  if (parts === null) {
    return null;
  }
  const year = Number(parts[1]);
  const month = Number(parts[2]);
  const day = Number(parts[3]);
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) {
    return null;
  }
  return `${parts[1]}-${parts[2]}-${parts[3]}`;
}

/** Today as the profile writes dates. A stamp, never a re-serialized value. */
function stampToday(now: Date, profile: PlatformProfile): string {
  const day = todayPart(now);
  if (profile.frontMatter.dateFormat === 'date') {
    return day;
  }
  const pad = (value: number): string => String(value).padStart(2, '0');
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  if (profile.frontMatter.dateFormat === 'rfc3339') {
    const offset = -now.getTimezoneOffset();
    const sign = offset < 0 ? '-' : '+';
    const abs = Math.abs(offset);
    return `${day}T${time}${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
  }
  return `${day}T${time}.${String(now.getMilliseconds()).padStart(3, '0')}Z`;
}

// ---------------------------------------------------------------------------
// Locating a key's line
// ---------------------------------------------------------------------------

const WARNING_LINE_RE = /^line (\d+): /;

/**
 * The 1-based line a top-level key occupies inside the block body, or `null`.
 *
 * Best effort by design: a line number is a convenience for jumping the cursor,
 * and a wrong one is worse than none. Only top-level keys are located, and only
 * in the dialect's own spelling.
 */
export function lineOfKey(block: FmBlock | undefined, key: string): number | null {
  if (block === undefined) {
    return null;
  }
  const lines = block.raw.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const text = (lines[i] ?? '').replace(/\r$/, '');
    if (block.format === 'yaml') {
      if (/^\s/.test(text) || isYamlSequenceItem(text)) {
        continue;
      }
      if (parseYamlKeyLine(text)?.key === key) {
        return i + 1;
      }
      continue;
    }
    const trimmed = text.trim();
    const needle = block.format === 'toml' ? `${key} =` : `"${key}"`;
    if (trimmed.startsWith(needle) || trimmed.startsWith(`"${key}" =`)) {
      return i + 1;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Building an issue
// ---------------------------------------------------------------------------

interface IssueDraft {
  rule: AuditRuleId;
  path: string;
  field: string | null;
  message: string;
  line?: number | null;
  /** Overrides `AUDIT_RULE_SPECS[rule].lane` when the fix decides otherwise. */
  lane?: Lane;
  suggestion?: string | null;
  /** `missing-key:<k>` and friends; defaults to the rule id itself. */
  kind?: string;
  fixable?: boolean;
}

function issueOf(draft: IssueDraft): AuditIssue {
  const spec = AUDIT_RULE_SPECS[draft.rule];
  return {
    kind: draft.kind ?? draft.rule,
    severity: spec.severity,
    field: draft.field,
    message: draft.message,
    lane: draft.lane ?? spec.lane,
    suggestion: draft.suggestion ?? null,
    path: draft.path,
    rule: draft.rule,
    line: draft.line ?? null,
    fixable: draft.fixable ?? false,
  };
}

// ---------------------------------------------------------------------------
// The mechanical fixes, shared by the audit and by `fixFor`
// ---------------------------------------------------------------------------

/** A field `default` as a front-matter value. */
function defaultValueOf(field: Field): FmValue | undefined {
  const value = field.default;
  if (value === undefined) {
    return undefined;
  }
  return Array.isArray(value) ? [...value] : value;
}

/**
 * The change set that would fill in one missing required key, or `null` when no
 * mechanical fix is honest.
 *
 * Four cases can be derived from the file itself, and they are the only four:
 *
 *   1. a publish date, from the date in the file's own name (else today);
 *   2. the slug, computed from the title the way `createSlug` computes it;
 *   3. a value the content type declares as that field's `default`;
 *   4. the field's typed empty **when the typed empty is not empty** —
 *      `featured: false` and `weight: 0` are values; `title: ''` and `tags: []`
 *      are the same violation rewritten, and `isEmpty` is the module's own way
 *      of saying so.
 *
 * The site's draft field is excluded from case 3 and 4 whatever it declares:
 * `emptyValueFor` answers "a new document is a draft", and quietly proposing
 * `draft: true` on an existing page is an un-publish, not a repair.
 */
function missingKeyFix(
  key: string,
  cfg: Zer0Config,
  profile: PlatformProfile,
  ct: ContentType,
  filePath: string,
  data: FrontMatter,
  now: Date,
): KeyChange[] | null {
  if (profile.frontMatter.dateKeys.publish.includes(key)) {
    return [{ key, value: filenameDateOf(profile, filePath) ?? stampToday(now, profile) }];
  }
  if (key === profile.frontMatter.slugKey) {
    const title = asString(ownValue(data, cfg.seo.titleField)) || asString(ownValue(data, 'title'));
    const slug = createSlug(cfg, title, ct, filePath, data);
    return slug.length > 0 ? [{ key, value: slug }] : null;
  }
  if (key === profile.frontMatter.draft.name || key === cfg.draftField.name) {
    return null;
  }
  const field = findField(ct.fields, key);
  if (field === undefined) {
    return null;
  }
  const declared = defaultValueOf(field);
  if (declared !== undefined && !isEmpty(field, declared)) {
    return [{ key, value: declared }];
  }
  const typed = emptyValueFor(field, cfg);
  return isEmpty(field, typed) ? null : [{ key, value: typed }];
}

// ---------------------------------------------------------------------------
// auditPage
// ---------------------------------------------------------------------------

/**
 * Every finding on one page.
 *
 * `block` is the raw block when the caller read the file, and `undefined` when
 * it only has the index's projection. The two are different claims, and the one
 * combination that can only mean "this file has no front matter" is an absent
 * block **and** no projected keys — an absent block with keys means we were
 * handed a projection, and saying `no-front-matter` about a file nobody opened
 * would be inventing a fact (D9).
 */
export function auditPage(
  cfg: Zer0Config,
  profile: PlatformProfile,
  page: PageEntry,
  ct: ContentType,
  block: FmBlock | undefined,
  schema: SiteSchema,
  now: Date,
): AuditIssue[] {
  const data = pageFrontMatter(page);
  const out: AuditIssue[] = [];

  if (block === undefined && Object.keys(data).length === 0) {
    out.push(
      issueOf({
        rule: 'no-front-matter',
        path: page.relPath,
        field: null,
        message: 'file has no parseable front matter',
        suggestion: 'Add a front-matter block before the body.',
      }),
    );
    return out;
  }

  if (block !== undefined && block.warnings.length > 0) {
    // Say what we could not read, and nothing else. Every check below reads
    // `data`, and `data` is what the construct in the warning corrupted.
    for (const warning of block.warnings) {
      const matched = WARNING_LINE_RE.exec(warning);
      out.push(
        issueOf({
          rule: 'unreadable-frontmatter',
          path: page.relPath,
          field: null,
          message: warning.replace(WARNING_LINE_RE, ''),
          line: matched === null ? null : Number(matched[1]),
          suggestion: 'Rewrite the construct in the supported subset, or edit this file by hand.',
        }),
      );
    }
    return out;
  }

  const collection = collectionNameOf(page);
  const matched = collectionSchemaFor(schema, page.relPath, collection);

  auditRequiredKeys(out, cfg, profile, page, ct, block, schema, data, collection, now);
  auditDates(out, profile, page, block, data, now);
  auditTaxonomies(out, cfg, profile, page, block, data);
  auditChoices(out, page, ct, block, data, matched?.schema.layoutAllowed ?? null);
  auditLengths(out, page, block, schema);
  auditUnknownKeys(out, profile, page, block, data, schema, matched);
  return out;
}

function auditRequiredKeys(
  out: AuditIssue[],
  cfg: Zer0Config,
  profile: PlatformProfile,
  page: PageEntry,
  ct: ContentType,
  block: FmBlock | undefined,
  schema: SiteSchema,
  data: FrontMatter,
  collection: string,
  now: Date,
): void {
  for (const key of requiredKeysFor(schema, page.relPath, collection)) {
    if (present(data, key)) {
      continue;
    }
    const fix = missingKeyFix(key, cfg, profile, ct, page.filePath, data, now);
    out.push(
      issueOf({
        rule: 'missing-key',
        kind: `missing-key:${key}`,
        path: page.relPath,
        field: key,
        line: lineOfKey(block, key),
        lane: fix === null ? 'substantive' : 'mechanical',
        fixable: fix !== null,
        message: `required key \`${key}\` is missing or empty`,
        suggestion:
          fix === null
            ? `Give \`${key}\` a value.`
            : `Set \`${key}\` to ${JSON.stringify(fix[0]?.value ?? null)}.`,
      }),
    );
  }
}

function auditDates(
  out: AuditIssue[],
  profile: PlatformProfile,
  page: PageEntry,
  block: FmBlock | undefined,
  data: FrontMatter,
  now: Date,
): void {
  const today = todayPart(now);
  const dateKeys = [...profile.frontMatter.dateKeys.publish, ...profile.frontMatter.dateKeys.modified];
  const seen = new Set<string>();

  for (const key of dateKeys) {
    if (seen.has(key) || !present(data, key)) {
      continue;
    }
    seen.add(key);
    const raw = ownValue(data, key);
    const part = datePartOf(raw);
    if (part === null) {
      out.push(
        issueOf({
          rule: 'invalid-date',
          path: page.relPath,
          field: key,
          line: lineOfKey(block, key),
          message: `\`${key}\` is \`${asString(raw, String(raw))}\`, which is not a date`,
          suggestion: 'Write the date as `YYYY-MM-DD`, optionally with a time and a zone.',
        }),
      );
      continue;
    }
    if (profile.frontMatter.dateKeys.publish.includes(key) && part > today) {
      out.push(
        issueOf({
          rule: 'future-date',
          path: page.relPath,
          field: key,
          line: lineOfKey(block, key),
          message: `\`${key}\` is ${part}, which is after today (${today})`,
          suggestion: 'A generator in production builds nothing dated in the future.',
        }),
      );
    }
  }

  const fromName = filenameDateOf(profile, page.filePath);
  const publish = firstPublishDate(profile, data);
  if (fromName !== null && publish !== undefined && publish.part !== fromName) {
    out.push(
      issueOf({
        rule: 'filename-date-mismatch',
        path: page.relPath,
        field: publish.key,
        line: lineOfKey(block, publish.key),
        message: `filename says ${fromName}, \`${publish.key}\` says ${publish.part}`,
        suggestion:
          'Rename the file or edit the key — which one is right is a judgment about what was published when.',
      }),
    );
  }
}

function firstPublishDate(
  profile: PlatformProfile,
  data: FrontMatter,
): { key: string; part: string } | undefined {
  for (const key of profile.frontMatter.dateKeys.publish) {
    if (!present(data, key)) {
      continue;
    }
    const part = datePartOf(ownValue(data, key));
    if (part !== null) {
      return { key, part };
    }
  }
  return undefined;
}

function auditTaxonomies(
  out: AuditIssue[],
  cfg: Zer0Config,
  profile: PlatformProfile,
  page: PageEntry,
  block: FmBlock | undefined,
  data: FrontMatter,
): void {
  for (const key of profile.frontMatter.taxonomyKeys) {
    if (!present(data, key) || cfg.frontMatter.commaSeparatedFields.includes(key)) {
      // A key the project declared comma-separated holds a scalar on purpose;
      // `applyCommaSeparatedFields` is the site's own convention, not a defect.
      continue;
    }
    const value = ownValue(data, key);
    if (Array.isArray(value)) {
      continue;
    }
    out.push(
      issueOf({
        rule: 'tags-not-array',
        path: page.relPath,
        field: key,
        line: lineOfKey(block, key),
        fixable: true,
        message: `\`${key}\` is a scalar; the site reads it as a list`,
        suggestion: `Write \`${key}\` as a list.`,
      }),
    );
  }
}

function choiceIds(field: Field): string[] {
  return (field.choices ?? []).map((choice) => (typeof choice === 'string' ? choice : choice.id));
}

function auditChoices(
  out: AuditIssue[],
  page: PageEntry,
  ct: ContentType,
  block: FmBlock | undefined,
  data: FrontMatter,
  layoutAllowed: readonly string[] | null,
): void {
  if (layoutAllowed !== null && layoutAllowed.length > 0 && present(data, 'layout')) {
    const layout = asString(ownValue(data, 'layout')).trim();
    if (!layoutAllowed.includes(layout)) {
      out.push(
        issueOf({
          rule: 'unknown-choice',
          path: page.relPath,
          field: 'layout',
          line: lineOfKey(block, 'layout'),
          message: `layout \`${layout}\` is not one of ${layoutAllowed.join(', ')}`,
          suggestion: 'Use a layout the collection declares, or add this one to the schema.',
        }),
      );
    }
  }

  for (const field of ct.fields) {
    if (field.type !== 'choice' || !present(data, field.name)) {
      continue;
    }
    const allowed = choiceIds(field);
    if (allowed.length === 0) {
      continue;
    }
    for (const value of asList(ownValue(data, field.name))) {
      if (allowed.includes(value)) {
        continue;
      }
      out.push(
        issueOf({
          rule: 'unknown-choice',
          path: page.relPath,
          field: field.name,
          line: lineOfKey(block, field.name),
          message: `\`${field.name}\` is \`${value}\`, which is not one of ${allowed.join(', ')}`,
          suggestion: 'Pick a declared choice, or add this one to the content type.',
        }),
      );
    }
  }
}

function auditLengths(
  out: AuditIssue[],
  page: PageEntry,
  block: FmBlock | undefined,
  schema: SiteSchema,
): void {
  const titleMax = schema.constraints.titleMax;
  if (titleMax !== null && page.title.length > titleMax) {
    out.push(
      issueOf({
        rule: 'title-too-long',
        path: page.relPath,
        field: 'title',
        line: lineOfKey(block, 'title'),
        message: `${page.title.length} characters (the site's cap is ${titleMax})`,
        suggestion: 'Shorten the title, or raise the cap in the schema.',
      }),
    );
  }
  const descriptionMax = schema.constraints.descriptionMax;
  if (descriptionMax !== null && page.description.length > descriptionMax) {
    out.push(
      issueOf({
        rule: 'description-too-long',
        path: page.relPath,
        field: 'description',
        line: lineOfKey(block, 'description'),
        message: `${page.description.length} characters (the SEO cap is ${descriptionMax})`,
        suggestion: 'Shorten the description; a search result truncates it anyway.',
      }),
    );
  }
}

/** Sources that named a closed vocabulary. A profile default never does. */
const VOCABULARY_SOURCES: ReadonlySet<string> = new Set(['frontmatter_schema.yml', 'cms-config', 'zer0.json']);

function auditUnknownKeys(
  out: AuditIssue[],
  profile: PlatformProfile,
  page: PageEntry,
  block: FmBlock | undefined,
  data: FrontMatter,
  schema: SiteSchema,
  matched: { name: string; schema: { required: string[]; optional: string[] } } | undefined,
): void {
  if (matched === undefined || matched.schema.optional.length === 0) {
    return;
  }
  if (!VOCABULARY_SOURCES.has(schema.source)) {
    return;
  }
  const known = new Set<string>([
    ...matched.schema.required,
    ...matched.schema.optional,
    ...schema.global.required,
    ...profile.frontMatter.dateKeys.publish,
    ...profile.frontMatter.dateKeys.modified,
    ...profile.frontMatter.taxonomyKeys,
    ...profile.frontMatter.thumbnailKeys,
    ...profile.frontMatter.permalinkKeys,
    profile.frontMatter.slugKey,
    profile.frontMatter.draft.name,
    'layout',
    'published',
  ]);
  const typeKey = profile.frontMatter.typeKey;
  if (typeKey !== null) {
    known.add(typeKey);
  }

  for (const key of Object.keys(data)) {
    if (known.has(key)) {
      continue;
    }
    out.push(
      issueOf({
        rule: 'unknown-key',
        path: page.relPath,
        field: key,
        line: lineOfKey(block, key),
        message: `\`${key}\` is not in the \`${matched.name}\` schema`,
        suggestion: `Add \`${key}\` to the collection's optional list, or remove it.`,
      }),
    );
  }
}

// ---------------------------------------------------------------------------
// auditSite
// ---------------------------------------------------------------------------

/**
 * The separator inside a duplicate index's composite key. A collection name and
 * a slug are both text a person chose, so the joiner has to be a character
 * neither can contain — written as an escape, never as a literal NUL byte in
 * this source file.
 */
const SEP = '\u0000';

function push<T>(index: Map<string, T[]>, key: string, value: T): void {
  const existing = index.get(key);
  if (existing === undefined) {
    index.set(key, [value]);
  } else {
    existing.push(value);
  }
}

/**
 * Every finding across a site, plus the two that only exist between files.
 *
 * `blocks` is optional and keyed by either the workspace-relative or the
 * absolute path: a caller that read the files (the audit command) gets line
 * numbers and the `unreadable-frontmatter` channel; the store, which holds only
 * the index, gets everything else. That is the same "report less, never invent"
 * split D9 draws everywhere in this codebase.
 */
export function auditSite(
  cfg: Zer0Config,
  profile: PlatformProfile,
  pages: readonly PageEntry[],
  skipped: readonly string[],
  schema: SiteSchema,
  now: Date,
  log?: LogSink,
  blocks?: ReadonlyMap<string, FmBlock>,
): SiteAudit {
  const issues: AuditIssue[] = [];
  const bySlug = new Map<string, Placed[]>();
  const byPermalink = new Map<string, Placed[]>();
  const structural = new Set(
    [...profile.frontMatter.structuralStems, ...profile.frontMatter.bundleNames].map((stem) =>
      stem.toLowerCase(),
    ),
  );

  for (const page of pages) {
    const block = blocks?.get(page.relPath) ?? blocks?.get(page.filePath);
    const data = pageFrontMatter(page);
    const ct = resolveContentType(cfg, data, page.filePath);
    issues.push(...auditPage(cfg, profile, page, ct, block, schema, now));

    if (block !== undefined && block.warnings.length > 0) {
      // A block we could not read cannot be compared against another file
      // either: its slug may be an anchor we never resolved.
      continue;
    }
    if (page.slug.length > 0 && !structural.has(stemOf(page))) {
      // Grouped by the page's own directory, not by the registered content
      // folder. A recursive folder holds several of a generator's routes —
      // `/hacks/:slug/` and `/tools/:slug/` are two namespaces, and treating
      // them as one reported ten collisions on lifehacker.dev that its own
      // build does not have. Structural stems (`index`, `README`) are skipped
      // outright: `index` is a position in a directory, not a slug, and every
      // site has one per section.
      push(bySlug, `${directoryOf(page)}${SEP}${page.slug}`, {
        page,
        line: lineOfKey(block, profile.frontMatter.slugKey),
      });
    }
    const permalink = firstString(data, profile.frontMatter.permalinkKeys);
    if (permalink !== undefined) {
      // A trailing slash is not a difference: `/shared` and `/shared/` are one
      // URL to every generator in this fleet, and calling them two collisions
      // the site does not have is exactly the noise D9 is against.
      push(byPermalink, permalink.value.replace(/\/+$/, '') || '/', {
        page,
        line: lineOfKey(block, permalink.key),
      });
    }
  }

  collide(issues, bySlug, 'duplicate-slug', (key) => key.split(SEP)[1] ?? key, 'slug');
  collide(issues, byPermalink, 'duplicate-permalink', (key) => key, 'permalink');

  issues.sort(
    (a, b) =>
      a.path.localeCompare(b.path) || (a.line ?? 0) - (b.line ?? 0) || a.kind.localeCompare(b.kind),
  );

  const counts: Record<Severity, number> = { error: 0, warning: 0, info: 0 };
  const byRule: Record<string, number> = {};
  for (const issue of issues) {
    counts[issue.severity] += 1;
    byRule[issue.rule] = (byRule[issue.rule] ?? 0) + 1;
  }

  log?.verbose(
    `[audit] scanned=${pages.length} issues=${issues.length} errors=${counts.error} ` +
      `warnings=${counts.warning} skipped=${skipped.length} schema=${schema.source}`,
  );

  return {
    root: cfg.workspaceRoot,
    generatedAt: now.toISOString(),
    issues,
    counts,
    byRule,
    scanned: pages.length,
    skipped: [...skipped].sort(),
  };
}

/** A page, and the line its colliding key sits on when the caller read the file. */
interface Placed {
  page: PageEntry;
  line: number | null;
}

function collide(
  out: AuditIssue[],
  index: ReadonlyMap<string, Placed[]>,
  rule: 'duplicate-slug' | 'duplicate-permalink',
  label: (key: string) => string,
  field: string,
): void {
  for (const [key, group] of index) {
    if (group.length < 2) {
      continue;
    }
    const paths = group.map((entry) => entry.page.relPath).sort();
    for (const entry of group) {
      const others = paths.filter((candidate) => candidate !== entry.page.relPath);
      out.push(
        issueOf({
          rule,
          path: entry.page.relPath,
          field,
          line: entry.line,
          message: `\`${label(key)}\` is also used by ${others.join(', ')}`,
          suggestion: 'Two pages that resolve to one URL means one of them is unreachable.',
        }),
      );
    }
  }
}

// ---------------------------------------------------------------------------
// The fix-it that never writes
// ---------------------------------------------------------------------------

/**
 * The change set that repairs one finding, or `null` when no mechanical fix is
 * honest. See the module comment's "Mechanical versus substantive".
 *
 * Nothing here reads or writes the disk: it is handed the `Article` a caller
 * already read, and it returns `KeyChange[]` for `dryRunFix` to render.
 */
export function fixFor(
  issue: AuditIssue,
  cfg: Zer0Config,
  profile: PlatformProfile,
  ct: ContentType,
  article: Article,
  now: Date,
): KeyChange[] | null {
  if (!FIXABLE_RULES.has(issue.rule) || issue.field === null) {
    return null;
  }
  if (article.block !== null && article.block.warnings.length > 0) {
    // The same refusal `dryRunFix` makes, made one step earlier so a caller
    // that only asks "is there a fix?" gets the honest answer too.
    return null;
  }

  if (issue.rule === 'tags-not-array') {
    const current = ownValue(article.data, issue.field);
    if (current === undefined || Array.isArray(current)) {
      return null;
    }
    const list = asList(current);
    return list.length === 0 ? null : [{ key: issue.field, value: list }];
  }

  if (present(article.data, issue.field)) {
    // The file changed since the audit ran; the key is there now.
    return null;
  }
  return missingKeyFix(issue.field, cfg, profile, ct, article.filePath, article.data, now);
}

/**
 * What the file would look like after `changes`, without writing anything.
 *
 * The rendering goes through the ordinary write path —
 * `updateFrontMatterKeys` then `stitch`, with the same BOM and prefix handling
 * `writeArticle` uses — so the preview is the bytes, not an approximation of
 * them. A caller shows the two strings in a diff and asks a person.
 *
 * It refuses in exactly the cases line surgery already declines, plus one:
 *
 *   - **a block the parser could not read** — the warnings channel. Rewriting a
 *     file we did not understand is how an anchor becomes a literal string in
 *     somebody's repository;
 *   - **TOML and JSON**, which re-serialize wholesale (D7);
 *   - **a nested path whose parent holds a scalar**, which `updateFrontMatterKeys`
 *     signals by returning `null`;
 *   - **a file with no block at all**, which has no lines to operate on.
 */
export function dryRunFix(
  article: Article,
  changes: readonly KeyChange[],
  cfg: Zer0Config,
): { before: string; after: string } | { refused: string } {
  const block = article.block;
  if (block === null) {
    return { refused: 'this file has no front-matter block to edit' };
  }
  if (block.warnings.length > 0) {
    return {
      refused: `the parser could not read this block, so it will not rewrite it: ${block.warnings[0] ?? ''}`,
    };
  }
  if (block.format !== 'yaml') {
    return {
      refused: `${block.format.toUpperCase()} front matter re-serializes wholesale; line surgery is YAML-only (D7)`,
    };
  }
  if (changes.length === 0) {
    return { before: article.raw, after: article.raw };
  }

  const nextRaw = updateFrontMatterKeys(
    block.raw,
    changes,
    serializeOptions(cfg, 'yaml'),
    block.eol,
  );
  if (nextRaw === null) {
    return {
      refused: 'a nested path under a scalar or a sequence — line surgery cannot place it safely',
    };
  }

  // `writeArticle`'s own prefix rule, so `after` is byte-for-byte what a write
  // would have produced: everything before the opening fence (a BOM, say) is
  // carried across untouched.
  const prefix = article.raw.slice(0, block.start);
  return { before: article.raw, after: prefix + stitch(block, nextRaw, article.body, 'yaml') };
}
