/**
 * Dates for front matter: formatted and parsed by date-fns in an IANA time
 * zone through `@date-fns/tz` (ADR 0006 decision 9 — the libraries the
 * hand-rolled subset over `Intl` imitated).
 *
 * A pattern is a setting a person types (`zer0Cms.date.format`, a content
 * type's field), so it is read in the vocabulary file mode has always
 * documented rather than as a date-fns program:
 *
 *   yyyy yy   year            MMMM MMM MM M  month        dd d do  day
 *   EEEE EEE  weekday         HH H           hour 0–23    hh h     hour 1–12
 *   mm m      minute          ss s           second       SSS      millisecond
 *   aaa a     am/pm           XXX            UTC offset (`Z` when zero)
 *
 * Front Matter's Moment spellings mean what they meant there (`YYYY`, `YY`,
 * `DD`, `D`, `Do`), text in single quotes is literal, and so is every other
 * letter: `yyyy-MM-ddTHH:mm` writes a `T`. Left to date-fns, an unquoted `T`
 * is the time as milliseconds since 1970 — written into a file — and `D` and
 * `YY` throw.
 *
 * Three rules hold whatever the libraries do:
 *
 *   - **Nothing throws in a render.** A zone the host does not know (a typo in
 *     `zer0Cms.date.timezone`) is the host's zone; a pattern that still fails
 *     formats as ISO 8601 and parses as `null`.
 *   - **Every `Date` returned is a plain `Date`**, never a zoned one, so its
 *     `toISOString()` is UTC like everywhere else.
 *   - **`parseDate` never guesses.** An existing `Date`, an epoch number, ISO
 *     8601, then the given pattern — never `Date.parse`'s locale-dependent
 *     path. A date-only ISO string is UTC midnight and a zone-less date-time is
 *     local, unless a zone is given, in which case both are that zone's wall
 *     clock, which is what makes a DST boundary round-trip.
 */

import { tz, TZDate, tzOffset } from '@date-fns/tz';
import { format, parse, parseISO } from 'date-fns';

const ISO_ZONED = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})$/;
const ISO_LOCAL = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3})\d*)?)?)?$/;
const ISO_PATTERN = "yyyy-MM-dd'T'HH:mm:ssXXX";

/** `timeZone` when the host knows it; otherwise undefined, which means the host's zone. */
function knownZone(timeZone: string | undefined): string | undefined {
  return timeZone && !Number.isNaN(tzOffset(timeZone, new Date(0))) ? timeZone : undefined;
}

export function isValidDate(value: unknown): value is Date {
  return value instanceof Date && !Number.isNaN(value.getTime());
}

/** Offset of `timeZone` (or the host's zone) at `date`, in minutes east of UTC. */
export function timezoneOffset(date: Date, timeZone?: string): number {
  const zone = knownZone(timeZone);
  return zone ? tzOffset(zone, date) : -date.getTimezoneOffset();
}

/** The tokens a pattern may use, as date-fns spells them (the table above). */
const TOKENS: ReadonlySet<string> = new Set(
  'yyyy yy MMMM MMM MM M dd d do EEEE EEE HH H hh h mm m ss s SSS aaa a XXX'.split(' '),
);
/** Front Matter's Moment spellings, as date-fns spells them. */
const MOMENT: Readonly<Record<string, string>> = { YYYY: 'yyyy', YY: 'yy', DD: 'dd', D: 'd', Do: 'do' };

/**
 * A pattern's pieces, in date-fns's order: a quote (`''`, read before anything
 * else), quoted text (its inside in group 1), a run of one letter (or `Do`),
 * other text.
 */
const PIECES = /''|'((?:[^']|'')*)'?|[Dd]o|([A-Za-z])\2*|[^A-Za-z']+/g;

/**
 * `pattern` as date-fns reads it: the vocabulary's tokens (Moment's spellings
 * translated), and everything else — quoted text, other letters, punctuation —
 * as one quoted literal between them, so it is written as it was typed.
 */
export function normalizePattern(pattern: string): string {
  // Quoted, with each quote doubled; text of quotes alone is `''` per quote, since
  // date-fns reads a leading `''` as one quote before it looks for quoted text.
  const quote = (text: string) => {
    const doubled = text.replace(/'/g, "''");
    return /^'*$/.test(text) ? doubled : `'${doubled}'`;
  };
  let out = '';
  let text = '';
  for (const [run, quoted] of pattern.matchAll(PIECES)) {
    const token = MOMENT[run] ?? run;
    if (quoted === undefined && TOKENS.has(token)) {
      out += quote(text) + token;
      text = '';
    } else {
      text += run === "''" ? "'" : (quoted?.replace(/''/g, "'") ?? run);
    }
  }
  return out + quote(text);
}

/** Format `date` with `pattern` in `timeZone` (IANA id) or the host's zone. */
export function formatDate(date: Date, pattern: string, timeZone?: string): string {
  if (!isValidDate(date)) {
    return '';
  }
  const zone = knownZone(timeZone);
  const zoned = zone ? new TZDate(date, zone) : date;
  try {
    return format(zoned, normalizePattern(pattern));
  } catch {
    // Nothing in the vocabulary throws; should date-fns, ISO 8601 still says when.
    return format(zoned, ISO_PATTERN);
  }
}

/**
 * Coerce a front-matter value into a `Date`, trying in order: an existing
 * `Date`, an epoch number, an ISO-8601 string, then `pattern` if given.
 * Anything else is `null`.
 */
export function parseDate(value: unknown, pattern?: string, timeZone?: string): Date | null {
  if (value instanceof Date) {
    return isValidDate(value) ? value : null;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    const fromEpoch = new Date(value);
    return isValidDate(fromEpoch) ? fromEpoch : null;
  }
  if (typeof value !== 'string' || value.trim() === '') {
    return null;
  }
  const text = value.trim();
  const zone = knownZone(timeZone);
  const local = ISO_LOCAL.exec(text);
  let parsed: Date;
  if (ISO_ZONED.test(text)) {
    parsed = parseISO(text.replace(/\s+(?=(?:Z|[+-]\d{2}:?\d{2})$)/, ''));
  } else if (local !== null && zone !== undefined) {
    // No offset in the string: that zone's wall clock.
    const [y = 0, mo = 1, d = 1, hh = 0, mi = 0, ss = 0] = local.slice(1, 7).map((part) => Number(part ?? 0));
    parsed = new TZDate(y, mo - 1, d, hh, mi, ss, Number((local[7] ?? '0').padEnd(3, '0')), zone);
  } else if (local !== null) {
    // The platform's own ISO rules: a date-only string is UTC midnight, a date-time local.
    parsed = new Date(text.replace(' ', 'T'));
  } else if (pattern) {
    try {
      parsed = parse(text, normalizePattern(pattern), new Date(), zone === undefined ? undefined : { in: tz(zone) });
    } catch {
      return null; // a pattern date-fns still refuses reads nothing, as a value that does not match it would
    }
  } else {
    return null;
  }
  return isValidDate(parsed) ? new Date(parsed.getTime()) : null;
}
