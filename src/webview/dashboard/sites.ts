/**
 * The Sites route — one row per open workspace folder, and which one the
 * console is pointed at.
 *
 * This is the screen the whole multi-root slice exists for. Every other tab
 * shows *a* site; this one shows that there are twelve of them, what kind of
 * site each is, which carry a project config, which carry a fleet manifest, and
 * how much content each holds. Before it existed, eleven of this fleet's twelve
 * open folders had no representation anywhere in the extension.
 *
 * **Decision D5, in its smallest possible form.** Both buttons post
 * `{type:'command', id, args:{site}}` — a site **id** and nothing else. Not a
 * path, not a config, not "and also make it trusted". The host looks that id up
 * in `SiteRegistry`, which is the only thing that knows which folders are
 * actually open; an id from a render that predates a folder closing is dropped
 * with a log line. The disabled state on a button here is a courtesy: `Preview`
 * re-asks `workspaceTrusted()` inside `doPreviewSite`, in the same function the
 * palette calls, and refuses in words.
 *
 * **Counts are honest about not knowing.** Constructing a store per folder must
 * not become a scan per folder at activation, so a site that has never been
 * read reports "not scanned" rather than zero pages — an unexamined site and an
 * empty one are different facts, and rendering both as `0` is how a console
 * starts lying quietly. The host refreshes every site when this tab is opened,
 * which is a person asking for exactly that work.
 */

import {
  dataTable,
  emptyState,
  gatedButton,
  keyValueList,
  statusPill,
  type StatusVariant,
} from '../shared/components';
import { clear, el, type Child } from '../shared/dom';
import type { BlockerView, DashboardState, SiteView } from '../shared/protocol';

/** A site whose store has never built a snapshot says so in this word. */
const NOT_SCANNED = 'not scanned';

function scanned(site: SiteView): boolean {
  return !site.detectionSource.includes(NOT_SCANNED);
}

// ---------------------------------------------------------------------------
// Cells
// ---------------------------------------------------------------------------

function nameCell(site: SiteView): Child {
  return el(
    'span',
    { class: 'z-sites__name' },
    el('span', { class: site.active ? 'z-sites__label is-active' : 'z-sites__label' }, site.name),
    site.active
      ? statusPill({ variant: 'ok', text: 'active', title: 'the console is pointed at this site' })
      : null,
  );
}

/**
 * The platform, with the overlay beside it rather than instead of it.
 *
 * zer0-mistakes is an overlay **on** Jekyll and never a sibling identity
 * (decision D12), so it renders as `jekyll + zer0-mistakes` — a row that said
 * only `zer0-mistakes` would be a fourth place where that distinction could rot.
 */
function platformCell(site: SiteView): Child {
  const variant: StatusVariant = scanned(site) ? 'neutral' : 'unknown';
  return el(
    'span',
    { class: 'z-sites__platform' },
    statusPill({
      variant,
      text: site.platform,
      title: `detected by: ${site.detectionSource}`,
    }),
    site.overlay === null ? null : el('code', { class: 'z-sites__overlay' }, `+ ${site.overlay}`),
  );
}

function configuredCell(site: SiteView): Child {
  return site.configured
    ? statusPill({ variant: 'ok', text: 'yes', title: 'this folder has a project config' })
    : statusPill({
        variant: 'neutral',
        text: 'no',
        title: 'no zer0.json — the defaults apply, which is a normal state',
      });
}

function countCell(site: SiteView, value: number): Child {
  return scanned(site)
    ? el('span', {}, String(value))
    : el('span', { class: 'z-sites__unknown', title: 'this site has not been read yet' }, '—');
}

function rootsCell(site: SiteView): Child {
  if (site.contentRoots.length === 0) {
    return el(
      'span',
      { class: 'z-sites__unknown', title: 'no content folder is registered in this site' },
      '—',
    );
  }
  return el(
    'span',
    { class: 'z-sites__roots', title: site.contentRoots.join('\n') },
    site.contentRoots.slice(0, 3).join(', ') +
      (site.contentRoots.length > 3 ? ` +${site.contentRoots.length - 3}` : ''),
  );
}

// ---------------------------------------------------------------------------
// The two intents
// ---------------------------------------------------------------------------

/**
 * Why `Make active` would do nothing. Advisory — the host re-checks the id.
 */
function activateBlockers(site: SiteView): BlockerView[] {
  return site.active ? [{ kind: 'alreadyActive', message: 'this site is already active' }] : [];
}

/**
 * Why `Preview` would refuse, in the host's own words.
 *
 * These three sentences exist twice on purpose: here, to grey a button out
 * before it is pressed, and in `src/commands/site.ts`, which is where the
 * refusal actually happens. The one here is decoration; the one there is the
 * decision (decision D5).
 */
function previewBlockers(site: SiteView): BlockerView[] {
  const blockers: BlockerView[] = [];
  if (!site.trusted) {
    blockers.push({
      kind: 'untrustedWorkspace',
      message: 'this workspace is not trusted, so nothing may start a process',
    });
  }
  if (site.scheme !== 'file') {
    blockers.push({
      kind: 'virtualFolder',
      message: `a ${site.scheme} folder has no local process to start`,
    });
  }
  return blockers;
}

function actionsCell(site: SiteView): Child {
  return el(
    'div',
    { class: 'z-sites__actions' },
    gatedButton({
      label: 'Make active',
      id: 'site.setActive',
      args: { site: site.id },
      blockers: activateBlockers(site),
      verb: 'Switching',
      secondary: true,
    }),
    gatedButton({
      label: 'Preview',
      id: 'site.preview',
      args: { site: site.id },
      blockers: previewBlockers(site),
      verb: 'Preview',
      title: 'run this site’s serve command as a task',
      secondary: true,
    }),
  );
}

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

const COLUMNS = [
  'Site',
  'Platform',
  'Config',
  'Content roots',
  { label: 'Pages', numeric: true },
  { label: 'Drafts', numeric: true },
  'Fleet',
  'Actions',
];

function row(site: SiteView): Child[] {
  return [
    nameCell(site),
    platformCell(site),
    configuredCell(site),
    rootsCell(site),
    countCell(site, site.counts.pages),
    countCell(site, site.counts.drafts),
    site.manifestPresent
      ? statusPill({ variant: 'neutral', text: 'manifest', title: 'this site carries a fleet manifest' })
      : el('span', { class: 'z-sites__unknown' }, '—'),
    actionsCell(site),
  ];
}

/** The provenance strip: what this table is a view of. */
function summary(sites: readonly SiteView[], activeName: string): HTMLElement {
  const unscanned = sites.filter((site) => !scanned(site)).length;
  return keyValueList(
    [
      { key: 'Open folders', value: String(sites.length) },
      { key: 'Active site', value: activeName },
      {
        key: 'Configured',
        value: `${sites.filter((site) => site.configured).length} of ${sites.length}`,
        title: 'folders that carry a project config',
      },
      ...(unscanned === 0
        ? []
        : [
            {
              key: 'Not scanned',
              value: `${unscanned}`,
              title:
                'activation constructs a store per folder and scans none of them; ' +
                'these fill in as each site is read',
            },
          ]),
    ],
    'z-sites__summary',
  );
}

export function render(host: HTMLElement, state: DashboardState): void {
  clear(host);

  const sites = state.sites;
  if (sites === undefined || sites.sites.length === 0) {
    host.appendChild(
      emptyState({
        icon: 'book',
        message: 'No folder is open.',
        hint: 'Open a folder — or a multi-root workspace — and every one of them gets a row here.',
      }),
    );
    return;
  }

  const active = sites.sites.find((site) => site.active);
  host.appendChild(summary(sites.sites, active?.name ?? '(none)'));

  host.appendChild(
    el(
      'section',
      { class: 'z-lane z-sites' },
      dataTable({
        columns: COLUMNS,
        className: 'z-sites__table',
        label: 'Open sites',
        rows: sites.sites.map(row),
        empty: 'No folder is open.',
      }),
    ),
  );

  if (!sites.multi) {
    host.appendChild(
      el(
        'p',
        { class: 'z-sites__note' },
        'One folder is open, so the site switcher and the Sites tree stay hidden. ' +
          'Add a folder to this workspace and both appear.',
      ),
    );
  }
}
