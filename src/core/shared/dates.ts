/**
 * Date formatting and parsing over a small token vocabulary, with timezone
 * support from `Intl.DateTimeFormat` — the stdlib replacement for date-fns +
 * date-fns-tz (two dependencies, ~70 kB, used for eight tokens).
 *
 * Patterns are the date-fns subset content authors actually write:
 *
 *   yyyy yy   year            MMMM MMM MM M  month        dd d   day
 *   EEEE EEE  weekday         HH H           hour 0–23    hh h   hour 1–12
 *   mm m      minute          ss s           second       SSS    millisecond
 *   aaa a     am/pm           XXX            UTC offset (`Z` when zero)
 *
 * Anything else is emitted literally, and text inside single quotes is always
 * literal (`'T'` in `yyyy-MM-dd'T'HH:mm:ss`), so an unsupported token degrades
 * to visible text instead of throwing in a panel render.
 *
 * All of it is timezone-aware through one mechanism: the calendar fields are
 * read out of `Intl.DateTimeFormat.formatToParts` for the requested zone, and
 * the reverse direction resolves the zone offset by a two-pass fixpoint, which
 * is what makes a DST boundary round-trip.
 */

const NUMERIC_PARTS: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
};

const formatterCache = new Map<string, Intl.DateTimeFormat>();

function formatterFor(timeZone: string | undefined, extra: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${timeZone ?? 'local'}|${Object.entries(extra).map(([k, v]) => `${k}=${String(v)}`).join(',')}`;
  const cached = formatterCache.get(key);
  if (cached) {
    return cached;
  }
  const options: Intl.DateTimeFormatOptions = { ...NUMERIC_PARTS, ...extra };
  if (timeZone) {
    options.timeZone = timeZone;
  }
  let formatter: Intl.DateTimeFormat;
  try {
    formatter = new Intl.DateTimeFormat('en-US', options);
  } catch {
    // An invalid IANA zone (a typo in `zer0Cms.date.timezone`) must not break a
    // panel render, so fall back to the host's zone.
    formatter = new Intl.DateTimeFormat('en-US', { ...NUMERIC_PARTS, ...extra });
  }
  formatterCache.set(key, formatter);
  return formatter;
}

interface DateParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
  millisecond: number;
  weekdayLong: string;
  weekdayShort: string;
  monthLong: string;
  monthShort: string;
}

const lookup = (list: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes): string =>
  list.find((p) => p.type === type)?.value ?? '';

const num = (value: string): number => {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : 0;
};

/**
 * Calendar fields of `date` as seen in `timeZone`. Month and weekday *names*
 * cost two extra `formatToParts` calls, so they are only fetched when the
 * pattern actually asks for them.
 */
function partsOf(date: Date, timeZone?: string, withNames = false): DateParts {
  const raw = formatterFor(timeZone, {}).formatToParts(date);
  const parts: DateParts = {
    year: num(lookup(raw, 'year')),
    month: num(lookup(raw, 'month')),
    day: num(lookup(raw, 'day')),
    // `hourCycle: 'h23'` still yields "24" for midnight in some ICU builds.
    hour: num(lookup(raw, 'hour')) % 24,
    minute: num(lookup(raw, 'minute')),
    second: num(lookup(raw, 'second')),
    millisecond: date.getMilliseconds(),
    weekdayLong: '',
    weekdayShort: '',
    monthLong: '',
    monthShort: '',
  };

  if (withNames) {
    const long = formatterFor(timeZone, { weekday: 'long', month: 'long' }).formatToParts(date);
    const short = formatterFor(timeZone, { weekday: 'short', month: 'short' }).formatToParts(date);
    parts.weekdayLong = lookup(long, 'weekday');
    parts.monthLong = lookup(long, 'month');
    parts.weekdayShort = lookup(short, 'weekday');
    parts.monthShort = lookup(short, 'month');
  }

  return parts;
}

/** Does this pattern need month/weekday names? */
function needsNames(tokens: readonly PatternToken[]): boolean {
  return tokens.some(
    (t) => !t.literal && (t.text === 'MMM' || t.text === 'MMMM' || t.text === 'EEE' || t.text === 'EEEE'),
  );
}

/** Offset of `timeZone` at `date`, in minutes east of UTC. */
export function timezoneOffset(date: Date, timeZone?: string): number {
  const p = partsOf(date, timeZone);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second, p.millisecond);
  return Math.round((asUtc - date.getTime()) / 60000);
}

function pad(value: number, width: number): string {
  return String(Math.abs(value)).padStart(width, '0');
}

/** FM accepted Moment-style `YYYY`/`DD`; normalise them to the date-fns spelling. */
export function normalizePattern(pattern: string): string {
  return pattern.replace(/YYYY/g, 'yyyy').replace(/DD/g, 'dd');
}

interface PatternToken {
  literal: boolean;
  text: string;
}

/** Split a pattern into literal runs and same-letter token runs. */
function tokenize(pattern: string): PatternToken[] {
  const tokens: PatternToken[] = [];
  let i = 0;
  while (i < pattern.length) {
    const ch = pattern.charAt(i);

    if (ch === "'") {
      if (pattern.charAt(i + 1) === "'") {
        tokens.push({ literal: true, text: "'" });
        i += 2;
        continue;
      }
      const end = pattern.indexOf("'", i + 1);
      if (end === -1) {
        tokens.push({ literal: true, text: pattern.slice(i + 1) });
        break;
      }
      tokens.push({ literal: true, text: pattern.slice(i + 1, end) });
      i = end + 1;
      continue;
    }

    if (/[A-Za-z]/.test(ch)) {
      let run = ch;
      while (pattern.charAt(i + run.length) === ch) {
        run += ch;
      }
      tokens.push({ literal: false, text: run });
      i += run.length;
      continue;
    }

    tokens.push({ literal: true, text: ch });
    i += 1;
  }
  return tokens;
}

function offsetToken(minutes: number): string {
  if (minutes === 0) {
    return 'Z';
  }
  const sign = minutes < 0 ? '-' : '+';
  return `${sign}${pad(Math.trunc(minutes / 60), 2)}:${pad(minutes % 60, 2)}`;
}

function renderToken(token: string, p: DateParts, offsetMinutes: number): string | undefined {
  const hour12 = p.hour % 12 === 0 ? 12 : p.hour % 12;
  switch (token) {
    case 'yyyy':
      return pad(p.year, 4);
    case 'yy':
      return pad(p.year % 100, 2);
    case 'MMMM':
      return p.monthLong;
    case 'MMM':
      return p.monthShort;
    case 'MM':
      return pad(p.month, 2);
    case 'M':
      return String(p.month);
    case 'dd':
      return pad(p.day, 2);
    case 'd':
      return String(p.day);
    case 'EEEE':
      return p.weekdayLong;
    case 'EEE':
      return p.weekdayShort;
    case 'HH':
      return pad(p.hour, 2);
    case 'H':
      return String(p.hour);
    case 'hh':
      return pad(hour12, 2);
    case 'h':
      return String(hour12);
    case 'mm':
      return pad(p.minute, 2);
    case 'm':
      return String(p.minute);
    case 'ss':
      return pad(p.second, 2);
    case 's':
      return String(p.second);
    case 'SSS':
      return pad(p.millisecond, 3);
    case 'aaa':
      return p.hour < 12 ? 'am' : 'pm';
    case 'a':
      return p.hour < 12 ? 'AM' : 'PM';
    case 'XXX':
      return offsetToken(offsetMinutes);
    default:
      return undefined;
  }
}

/**
 * Format `date` with `pattern`, in `timeZone` (IANA id) or the host zone.
 * Unknown tokens pass through literally.
 */
export function formatDate(date: Date, pattern: string, timeZone?: string): string {
  if (!isValidDate(date)) {
    return '';
  }
  const tokens = tokenize(normalizePattern(pattern));
  const parts = partsOf(date, timeZone, needsNames(tokens));
  const offset = timezoneOffset(date, timeZone);

  let out = '';
  for (const token of tokens) {
    if (token.literal) {
      out += token.text;
      continue;
    }
    out += renderToken(token.text, parts, offset) ?? token.text;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

export function isValidDate(value: unknown): value is Date {
  return value instanceof Date && !Number.isNaN(value.getTime());
}

const ISO_RE =
  /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3})\d*)?)?\s*(Z|[+-]\d{2}:?\d{2})?)?$/;

const MONTH_NAMES = [
  'january',
  'february',
  'march',
  'april',
  'may',
  'june',
  'july',
  'august',
  'september',
  'october',
  'november',
  'december',
];

interface WallClock {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
  millisecond: number;
}

/**
 * Wall-clock fields in `timeZone` → the UTC instant they denote.
 *
 * Two passes: guess with the offset in force at the naive instant, then
 * re-read the offset at that guess. That second pass is what makes a time
 * written on either side of a DST change resolve to the right instant.
 */
function wallClockToUtc(fields: WallClock, timeZone: string): Date {
  const naive = Date.UTC(
    fields.year,
    fields.month - 1,
    fields.day,
    fields.hour,
    fields.minute,
    fields.second,
    fields.millisecond,
  );
  const firstGuess = naive - timezoneOffset(new Date(naive), timeZone) * 60000;
  const secondOffset = timezoneOffset(new Date(firstGuess), timeZone) * 60000;
  return new Date(naive - secondOffset);
}

function localWallClock(fields: WallClock): Date {
  return new Date(
    fields.year,
    fields.month - 1,
    fields.day,
    fields.hour,
    fields.minute,
    fields.second,
    fields.millisecond,
  );
}

function parseWithPattern(value: string, pattern: string, timeZone?: string): Date | null {
  const tokens = tokenize(normalizePattern(pattern));
  const order: string[] = [];
  let source = '^';

  for (const token of tokens) {
    if (token.literal) {
      source += token.text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      continue;
    }
    switch (token.text) {
      case 'yyyy':
        source += '(\\d{4})';
        break;
      case 'yy':
      case 'MM':
      case 'dd':
      case 'HH':
      case 'hh':
      case 'mm':
      case 'ss':
        source += '(\\d{2})';
        break;
      case 'M':
      case 'd':
      case 'H':
      case 'h':
      case 'm':
      case 's':
        source += '(\\d{1,2})';
        break;
      case 'SSS':
        source += '(\\d{1,3})';
        break;
      case 'MMMM':
      case 'MMM':
      case 'EEEE':
      case 'EEE':
        source += '([A-Za-z]+)';
        break;
      case 'aaa':
      case 'a':
        source += '([AaPp][Mm])';
        break;
      case 'XXX':
        source += '(Z|[+-]\\d{2}:?\\d{2})';
        break;
      default:
        source += token.text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        continue;
    }
    order.push(token.text);
  }
  source += '$';

  const match = new RegExp(source).exec(value.trim());
  if (!match) {
    return null;
  }

  const now = new Date();
  const fields = {
    year: now.getFullYear(),
    month: 1,
    day: 1,
    hour: 0,
    minute: 0,
    second: 0,
    millisecond: 0,
  };
  let pm: boolean | undefined;
  let explicitOffset: number | undefined;

  order.forEach((token, index) => {
    const captured = match[index + 1];
    if (captured === undefined) {
      return;
    }
    const n = Number.parseInt(captured, 10);
    switch (token) {
      case 'yyyy':
        fields.year = n;
        break;
      case 'yy':
        fields.year = 2000 + n;
        break;
      case 'MM':
      case 'M':
        fields.month = n;
        break;
      case 'MMMM':
      case 'MMM': {
        const found = MONTH_NAMES.findIndex((name) => name.startsWith(captured.toLowerCase()));
        if (found >= 0) {
          fields.month = found + 1;
        }
        break;
      }
      case 'dd':
      case 'd':
        fields.day = n;
        break;
      case 'HH':
      case 'H':
      case 'hh':
      case 'h':
        fields.hour = n;
        break;
      case 'mm':
      case 'm':
        fields.minute = n;
        break;
      case 'ss':
      case 's':
        fields.second = n;
        break;
      case 'SSS':
        fields.millisecond = n;
        break;
      case 'aaa':
      case 'a':
        pm = captured.toLowerCase() === 'pm';
        break;
      case 'XXX':
        explicitOffset = captured === 'Z' ? 0 : offsetMinutesOf(captured);
        break;
      default:
        break;
    }
  });

  if (pm === true && fields.hour < 12) {
    fields.hour += 12;
  }
  if (pm === false && fields.hour === 12) {
    fields.hour = 0;
  }

  if (explicitOffset !== undefined) {
    const naive = Date.UTC(
      fields.year,
      fields.month - 1,
      fields.day,
      fields.hour,
      fields.minute,
      fields.second,
      fields.millisecond,
    );
    return new Date(naive - explicitOffset * 60000);
  }

  const parsed = timeZone ? wallClockToUtc(fields, timeZone) : localWallClock(fields);
  return isValidDate(parsed) ? parsed : null;
}

function offsetMinutesOf(token: string): number {
  const match = /^([+-])(\d{2}):?(\d{2})$/.exec(token);
  if (!match) {
    return 0;
  }
  const sign = match[1] === '-' ? -1 : 1;
  return sign * (Number.parseInt(match[2] ?? '0', 10) * 60 + Number.parseInt(match[3] ?? '0', 10));
}

/**
 * Coerce a front-matter value into a `Date`, trying in order: an existing
 * `Date`, an epoch number, an ISO-8601 string, then `pattern` if given.
 * Anything else is `null` — deliberately, so a locale-formatted string never
 * silently becomes a wrong date via `Date.parse`'s implementation-defined path.
 */
export function parseDate(value: unknown, pattern?: string, timeZone?: string): Date | null {
  if (value instanceof Date) {
    return isValidDate(value) ? value : null;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    const fromEpoch = new Date(value);
    return isValidDate(fromEpoch) ? fromEpoch : null;
  }
  if (typeof value !== 'string') {
    return null;
  }

  const text = value.trim();
  if (!text) {
    return null;
  }

  const iso = ISO_RE.exec(text);
  if (iso) {
    const [, y, mo, d, hh, mi, ss, ms, zone] = iso;
    const fields: WallClock = {
      year: Number(y),
      month: Number(mo),
      day: Number(d),
      hour: hh === undefined ? 0 : Number(hh),
      minute: mi === undefined ? 0 : Number(mi),
      second: ss === undefined ? 0 : Number(ss),
      millisecond: ms === undefined ? 0 : Number(ms.padEnd(3, '0')),
    };
    if (zone !== undefined) {
      const offset = zone === 'Z' ? 0 : offsetMinutesOf(zone);
      const utc = Date.UTC(
        fields.year,
        fields.month - 1,
        fields.day,
        fields.hour,
        fields.minute,
        fields.second,
        fields.millisecond,
      );
      return new Date(utc - offset * 60000);
    }
    if (timeZone) {
      // No offset in the string: read the wall clock in the requested zone,
      // which is what makes `formatDate`/`parseDate` round-trip across DST.
      return wallClockToUtc(fields, timeZone);
    }
    // Otherwise keep the platform's own ISO rules: a date-only string is UTC
    // midnight, a zone-less date-time is local.
    const native = new Date(text.replace(' ', 'T'));
    if (isValidDate(native)) {
      return native;
    }
  }

  if (pattern) {
    return parseWithPattern(text, pattern, timeZone);
  }
  return null;
}
