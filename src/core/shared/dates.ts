/**
 * Dates for front matter: date-fns patterns, formatted and parsed in an IANA
 * time zone through `@date-fns/tz` (ADR 0006 decision 9 — the libraries the
 * hand-rolled subset over `Intl` imitated). Patterns are date-fns's, with
 * Front Matter's Moment spellings `YYYY` and `DD` read as `yyyy` and `dd`, and
 * text in single quotes literal (`yyyy-MM-dd'T'HH:mm:ssXXX`).
 *
 * Three rules hold whatever the libraries do:
 *
 *   - **Nothing throws in a render.** A zone the host does not know (a typo in
 *     `zer0Cms.date.timezone`) is the host's zone; a pattern date-fns refuses
 *     formats as ISO 8601, which is still a true and readable date.
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

/** FM accepted Moment-style `YYYY`/`DD`; normalise them to the date-fns spelling. */
export function normalizePattern(pattern: string): string {
  return pattern.replace(/YYYY/g, 'yyyy').replace(/DD/g, 'dd');
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
    // An unescaped letter date-fns has no token for: ISO 8601 still says when.
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
    parsed = parse(text, normalizePattern(pattern), new Date(), zone === undefined ? undefined : { in: tz(zone) });
  } else {
    return null;
  }
  return isValidDate(parsed) ? new Date(parsed.getTime()) : null;
}
