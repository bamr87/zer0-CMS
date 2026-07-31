/**
 * UTC timestamps in the exact shape the Python lane writes everywhere:
 * `%Y-%m-%dT%H:%M:%SZ` — second precision, no milliseconds.
 *
 * This is a byte contract, not a formatting preference. Ledger records and
 * `.cms/distribution/` payloads are written by both lanes; a stray `.123` in
 * one of them turns every publish into a diff. Anything user-facing goes
 * through `dates.ts` instead — this module is for machine-read fields only.
 */

/** `2026-07-31T14:05:22Z` */
export function utcStamp(date: Date = new Date()): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/** `2026-07-31` */
export function utcDate(date: Date = new Date()): string {
  return date.toISOString().slice(0, 10);
}
