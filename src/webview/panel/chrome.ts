/**
 * The panel's frame: the collapsible section wrapper and its collapse memory,
 * the loading overlay, and the three rows of PLAN §3.1 that are not sections
 * (the developer bar, the initialize action, and the `.base__empty` state).
 *
 * Two things here are load-bearing.
 *
 * **The collapse key.** Front Matter remembered a section's open/closed state
 * under `collapse_<id>`, and switched to `base_<id>` when no supported file was
 * open — so "I always keep Metadata closed while editing" and "I always keep
 * Other actions open on the General view" are two different memories rather
 * than one that fights itself. `collapseKey()` is the whole of that rule and
 * every section goes through it; `Messenger.isCollapsed`/`setCollapsed` already
 * mirror the value into workspace state, so the host survives a reload.
 *
 * **The spinner is force-cleared after five seconds.** A webview that mounts,
 * posts `ready`, and never hears back — because the host was mid-refresh, or a
 * message was dropped while the view was hidden — would otherwise show a
 * loading bar forever with no way out. Five seconds and it clears itself, logs
 * why, and lets whatever state does arrive paint over it. A stuck spinner is a
 * bug report; an empty panel is a refresh away from being right.
 *
 * The section registry exists for exactly one caller: the `zer0Cms.collapseSections`
 * title-bar command, which arrives as a `collapseAll` host message. Handles are
 * pruned on every use by `isConnected`, because the reconciler rebuilds a stale
 * section by clearing its host — the old handle's element is detached, not
 * disposed, and holding it would leak one entry per re-render.
 */

import { collapsible, spinner, type CollapsibleHandle } from '../shared/components';
import { el, icon, type Child } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type { CommandId } from '../shared/protocol';

const msg = getMessenger();

/** How long the mount spinner may survive without a snapshot. */
export const LOADING_TIMEOUT_MS = 5000;

/** Where "Open documentation" goes. The repository, not a marketing site. */
export const DOCS_URL = 'https://github.com/bamr87/zer0-CMS#readme';

// ---------------------------------------------------------------------------
// Collapse memory
// ---------------------------------------------------------------------------

/**
 * The persisted key for a section, `base_`-prefixed on the no-file view.
 *
 * `hasFile` is "is a supported file open", not "does this section have data" —
 * the whole point is that the two *views* of the panel remember separately.
 */
export function collapseKey(id: string, hasFile: boolean): string {
  return hasFile ? id : `base_${id}`;
}

interface Registered {
  key: string;
  handle: CollapsibleHandle;
}

const live: Registered[] = [];

function prune(): void {
  for (let i = live.length - 1; i >= 0; i--) {
    const entry = live[i];
    if (entry === undefined || !entry.handle.el.isConnected) {
      live.splice(i, 1);
    }
  }
}

export interface SectionFrameOptions {
  /** The base id from §3.1 — `governance`, `metadata`, `seo`, `actions`… */
  id: string;
  title: string;
  /** `false` switches the persisted key to its `base_` form. */
  hasFile: boolean;
  /** Extra class on the body: `article__actions`, `governance__block`, … */
  className?: string;
  /** Trailing element in the header row. */
  badge?: Child;
}

/** A collapsible panel section whose open/closed state is remembered. */
export function panelSection(options: SectionFrameOptions, ...children: Child[]): HTMLElement {
  const key = collapseKey(options.id, options.hasFile);
  const handle = collapsible(
    {
      id: key,
      title: options.title,
      // Default open, exactly as Front Matter did: only a persisted `'false'`
      // closes a section, so an id nobody has ever toggled starts open.
      open: !msg.isCollapsed(key),
      onToggle: (_id, open) => {
        msg.setCollapsed(key, open);
      },
      // `exactOptionalPropertyTypes`: an absent option is an absent key.
      ...(options.className === undefined ? {} : { className: options.className }),
      ...(options.badge === undefined ? {} : { badge: options.badge }),
    },
    ...children,
  );
  prune();
  live.push({ key, handle });
  return handle.el;
}

/**
 * Close every section on screen and remember that. Fired by the host's
 * `collapseAll` message, which is the `zer0Cms.collapseSections` command.
 */
export function closeAllSections(): void {
  prune();
  for (const entry of live) {
    entry.handle.setOpen(false);
    msg.setCollapsed(entry.key, false);
  }
}

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

export interface CommandButtonOptions {
  label: string;
  id: CommandId;
  /** A target, never an override — decision D5. */
  args?: unknown;
  title?: string;
  disabled?: boolean;
  secondary?: boolean;
}

/**
 * A full-width button that posts one intent.
 *
 * `args` carries a *target* (which file, which draft) and nothing else. The
 * host re-reads state from disk and re-runs every gate before it acts, in the
 * same function the command palette calls, so `disabled` here is a courtesy to
 * the reader rather than a control (D5).
 */
export function commandButton(options: CommandButtonOptions): HTMLElement {
  return el(
    'button',
    {
      class: options.secondary === true ? 'z-btn z-btn--secondary' : 'z-btn',
      type: 'button',
      title: options.title ?? options.label,
      disabled: options.disabled === true,
      onclick: () => {
        msg.command(options.id, options.args);
      },
    },
    options.label,
  );
}

export interface LinkRowOptions {
  label: string;
  /** Codicon name. */
  icon: string;
  title?: string;
  disabled?: boolean;
  /** Primary colours instead of secondary — Front Matter's `.active` variant. */
  active?: boolean;
  onClick(): void;
}

/**
 * The `.ext_link_block` secondary link-button used by "Other actions": a
 * full-width inline-flex row, 26px line-height, icon then ellipsised label.
 */
export function linkRow(options: LinkRowOptions): HTMLElement {
  return el(
    'div',
    { class: 'ext_link_block' },
    el(
      'button',
      {
        class: options.active === true ? 'active' : '',
        type: 'button',
        title: options.title ?? options.label,
        disabled: options.disabled === true,
        onclick: options.onClick,
      },
      icon(options.icon),
      el('span', {}, options.label),
    ),
  );
}

// ---------------------------------------------------------------------------
// The three non-section rows
// ---------------------------------------------------------------------------

/**
 * Reload and DevTools, on the debugging-coloured bar. Gated host-side on
 * `extensionMode !== Production`, and the two `command:` URIs are the only ones
 * the webview's `enableCommandUris` allow-list contains.
 */
export function developerBar(): HTMLElement {
  return el(
    'div',
    { class: 'developer__bar' },
    el(
      'a',
      {
        href: 'command:workbench.action.webview.reloadWebviewAction',
        title: 'Reload the panel',
      },
      'Reload',
    ),
    el(
      'a',
      { href: 'command:workbench.action.webview.openDeveloperTools', title: 'Open the DevTools' },
      'DevTools',
    ),
  );
}

/** The single full-width button shown until `zer0.json` exists. */
export function initializeAction(): HTMLElement {
  return el(
    'div',
    { class: 'initialize_actions' },
    commandButton({ label: 'Initialize project', id: 'init', title: 'Initialize project' }),
  );
}

/** Shown when every configurable section is switched off. */
export function emptyState(): HTMLElement {
  return el('div', { class: 'base__empty' }, el('p', {}, 'Open a file to see more actions'));
}

// ---------------------------------------------------------------------------
// The loading overlay
// ---------------------------------------------------------------------------

export interface Loading {
  /** Idempotent: clears the overlay and cancels the safety timer. */
  done(): void;
  /** Show it again — the host's `progress` message with a panel scope. */
  show(message: string | null): void;
}

/**
 * Mount the loader over `host` and arm the five-second escape hatch.
 *
 * The overlay is `position: fixed`, so it covers the panel wherever it is
 * appended; it goes in after `mountSections` because that call clears its root.
 */
export function mountLoading(host: HTMLElement): Loading {
  let overlay: HTMLElement | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const remove = (): void => {
    overlay?.remove();
    overlay = undefined;
  };

  const done = (): void => {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
    remove();
  };

  const show = (message: string | null): void => {
    remove();
    overlay = message === null ? spinner() : spinner(message);
    host.appendChild(overlay);
  };

  show(null);
  timer = setTimeout(() => {
    timer = undefined;
    if (overlay !== undefined) {
      // A dropped snapshot must not read as a permanently loading panel.
      msg.log('warn', `panel: no state within ${LOADING_TIMEOUT_MS}ms; clearing the spinner`);
      remove();
    }
  }, LOADING_TIMEOUT_MS);

  return { done, show };
}
