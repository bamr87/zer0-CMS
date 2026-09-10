/**
 * The hand-off to GitFactory — one URL, and nothing else.
 *
 * The division of labour (`docs/ARCHITECTURE.md`, "The contract map") gives
 * GitFactory the browser: it designs blueprints, observes the wider fleet, and
 * owns the `factory--*.yml` files it compiles. This console operates inside the
 * editor on files a person already has open. Where the two meet, the meeting is
 * a link the person clicks — never a shared cache, never a write into the other
 * tool's files.
 *
 * ## Parseable by, not byte-equal to
 *
 * gitorio's `app/src/state/deeplink.ts` has both halves of the contract:
 *
 * ```ts
 * export function parseDeepLink(search: string): DeepLink {
 *   const params = new URLSearchParams(search);
 *   const rawRoster = params.getAll('roster').join(' ');
 *   return { tab: params.get('tab'), hub: params.get('hub'),
 *            roster: parseRosterText(rawRoster).map((r) => r.slug) };
 * }
 * export function rosterLink(base: string, slugs: string[], tab = 'fleet'): string {
 *   const params = new URLSearchParams({ tab, roster: slugs.join(',') });
 *   return `${base.replace(/\/?$/, '/')}?${params.toString()}`;
 * }
 * ```
 *
 * The **reader** understands three parameters. The **writer** emits two: it has
 * no `hub=`, because in that app the hub is a session override an operator types
 * rather than something a share link carries. This console does have a
 * configured hub (`zer0Cms.fleet.hub`), and handing it over is the whole point of
 * the hand-off — so `gitFactoryLink` emits `hub=` when it has one.
 *
 * That makes byte-equality with `rosterLink` the wrong test: it would either
 * force this console to drop the hub, or fail the moment gitorio reformats its
 * own writer. The right test is the one `engines.test.ts` runs — feed the output
 * to a transcription of `parseDeepLink` and assert it reads back exactly the tab,
 * hub and roster that went in. The reader is the contract; the writer is an
 * implementation detail of somebody else's app.
 *
 * Slug validity is the other half. `parseDeepLink` runs the roster through
 * `parseRosterText`, which drops anything that is not an `owner/name` — so a
 * junk slug does not corrupt the link, it silently disappears at the far end.
 * This writer therefore filters with the same rule locally, so what leaves here
 * is what arrives there.
 */

/** The GitFactory views this console knows how to open. */
export type GitFactoryTab = 'fleet' | 'harness';

/**
 * `owner/name`, the way `parseRepo` accepts it: two non-empty segments of the
 * characters GitHub allows, no leading slash, no third segment.
 */
const SLUG_RE = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/;

/** The slugs that will survive gitorio's own `parseRosterText`, deduped, in order. */
export function gitFactoryRoster(slugs: readonly string[]): string[] {
  const seen = new Set<string>();
  const kept: string[] = [];
  for (const raw of slugs) {
    const slug = raw.trim();
    if (!SLUG_RE.test(slug)) {
      continue;
    }
    const key = slug.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    kept.push(slug);
  }
  return kept;
}

/**
 * The GitFactory URL for a roster.
 *
 * `base` is `zer0Cms.fleet.gitfactoryUrl` (default
 * `https://bamr87.github.io/gitorio/`); a missing trailing slash is added, the
 * same normalisation `rosterLink` does. `hub` is emitted only when it is a real
 * `owner/name` — an empty override is worse than none, because it would blank a
 * hub the operator had already set in that session. An empty roster still
 * produces a valid link: opening the tab with nothing selected is a reasonable
 * thing to want.
 *
 * Pure, and it opens nothing: the shell decides whether a person asked for a
 * browser.
 */
export function gitFactoryLink(
  base: string,
  hub: string | null,
  slugs: readonly string[],
  tab: GitFactoryTab = 'fleet',
): string {
  const params = new URLSearchParams({ tab });
  if (hub !== null && SLUG_RE.test(hub.trim())) {
    params.set('hub', hub.trim());
  }
  params.set('roster', gitFactoryRoster(slugs).join(','));
  return `${base.replace(/\/?$/, '/')}?${params.toString()}`;
}
