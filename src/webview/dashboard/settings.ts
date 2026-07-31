/**
 * The Settings route — two sections, both of which write through one host op.
 *
 * *General* is the dashboard's own preferences (open on startup, default view,
 * default sorting, page size, card fields, auto-update modified date) and
 * *Content folders* is the register / unregister / content-type-assignment
 * list.
 *
 * **Every write is `{type:'command', id:'updateSetting', args:{key, value}}`.**
 * The webview cannot name an arbitrary VS Code setting: the closed `CommandId`
 * union gets it as far as "I would like to update a setting", and the host
 * holds the allow-list that decides which keys exist and where they land
 * (decision D5). `SettingItem.key` arrives *from* the host, so this file only
 * ever hands a key back that the host itself named.
 *
 * ### Edits are staged, not streamed
 *
 * Each control writes into a module-level `pending` map and **Save** flushes
 * it, which is what makes "Save is disabled until something changed" a fact
 * about the data rather than a flag somebody has to remember to set. `pending`
 * survives a state snapshot on purpose — a half-typed page size must not be
 * erased by an unrelated refresh — and an entry clears itself the moment the
 * host reports the value it was asking for. So a refused write visibly stays
 * dirty instead of quietly pretending it landed.
 */

import { menuButton, toggle } from '../shared/components';
import { clear, el, icon } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type {
  CommandId,
  DashboardState,
  FolderView,
  SettingItem,
  SettingsState,
} from '../shared/protocol';

/**
 * The key under which a folder's content-type assignment is written. The value
 * is the folder's full content-type list and `path` names which folder — a
 * target, never an override.
 */
export const FOLDER_CONTENT_TYPES_KEY = 'contentFolder.contentTypes';

type SettingValue = string | number | boolean;

/** Staged edits, keyed by `SettingItem.key`. Cleared as the host confirms. */
const pending = new Map<string, SettingValue>();

interface Mount {
  host: HTMLElement;
  state: DashboardState;
}

let mounted: Mount | null = null;

function post(id: CommandId, args?: unknown): void {
  getMessenger().command(id, args);
}

/** Repaint from the last snapshot — used by Cancel, which drops staged edits. */
function repaint(): void {
  if (mounted !== null) {
    render(mounted.host, mounted.state);
  }
}

/**
 * Drop staged edits the host has caught up with, and edits whose key is no
 * longer offered. What remains is exactly "changes not yet on disk".
 */
function reconcile(items: readonly SettingItem[]): void {
  const offered = new Map(items.map((item) => [item.key, item.value] as const));
  for (const key of [...pending.keys()]) {
    if (!offered.has(key) || Object.is(offered.get(key), pending.get(key))) {
      pending.delete(key);
    }
  }
}

function currentValue(item: SettingItem): SettingValue {
  const staged = pending.get(item.key);
  return staged === undefined ? item.value : staged;
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

function stage(key: string, value: SettingValue, original: SettingValue, onDirty: () => void): void {
  if (Object.is(value, original)) {
    pending.delete(key);
  } else {
    pending.set(key, value);
  }
  onDirty();
}

function control(item: SettingItem, onDirty: () => void): HTMLElement {
  const value = currentValue(item);

  if (item.kind === 'boolean') {
    return toggle({
      checked: value === true,
      onChange(checked) {
        stage(item.key, checked, item.value, onDirty);
      },
    }).el;
  }

  if (item.kind === 'choice') {
    const select = el('select', {
      attrs: { 'aria-label': item.label },
      on: {
        change: (event) => {
          const target = event.target;
          if (target instanceof HTMLSelectElement) {
            stage(item.key, target.value, item.value, onDirty);
          }
        },
      },
    });
    for (const choice of item.choices ?? []) {
      select.appendChild(
        el('option', { value: choice, selected: choice === String(value) }, choice),
      );
    }
    // A value the host offers no choice for is still the truth about the
    // configuration; showing it beats silently selecting the first option.
    if (!(item.choices ?? []).includes(String(value))) {
      select.insertBefore(
        el('option', { value: String(value), selected: true }, String(value)),
        select.firstChild,
      );
    }
    return select;
  }

  const input = el('input', {
    class: 'z-field__input',
    type: item.kind === 'number' ? 'number' : 'text',
    value: String(value),
    attrs: { 'aria-label': item.label },
    on: {
      input: (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) {
          return;
        }
        if (item.kind === 'number') {
          const parsed = Number(target.value);
          stage(item.key, Number.isFinite(parsed) ? parsed : 0, item.value, onDirty);
        } else {
          stage(item.key, target.value, item.value, onDirty);
        }
      },
    },
  });
  return el('div', { class: 'z-field' }, input);
}

function settingRow(item: SettingItem, onDirty: () => void): HTMLElement {
  const label = el(
    'div',
    {},
    el('label', {}, item.label),
    item.description === undefined
      ? null
      : el('p', { class: 'z-settings__description' }, item.description),
  );
  return el('div', { class: 'z-settings__row' }, label, control(item, onDirty));
}

// ---------------------------------------------------------------------------
// General
// ---------------------------------------------------------------------------

function generalSection(settings: SettingsState): HTMLElement {
  const section = el('section', { class: 'z-settings__section' }, el('h2', {}, 'General'));

  const save = el(
    'button',
    {
      class: 'z-btn',
      type: 'button',
      disabled: pending.size === 0,
      title: 'Write the changed settings',
      onclick: () => {
        // One intent per changed key. The host owns which keys exist and
        // re-reads its own configuration afterwards; nothing here assumes the
        // write succeeded — `reconcile()` decides that on the next snapshot.
        for (const [key, value] of pending) {
          post('updateSetting', { key, value });
        }
      },
    },
    'Save',
  );
  const cancel = el(
    'button',
    {
      class: 'z-btn z-btn--secondary',
      type: 'button',
      title: 'Discard the changes that have not been saved',
      onclick: () => {
        pending.clear();
        repaint();
      },
    },
    'Cancel',
  );

  const onDirty = (): void => {
    save.disabled = pending.size === 0;
  };

  if (settings.general.length === 0) {
    section.appendChild(el('p', { class: 'z-empty' }, 'No settings to configure.'));
    return section;
  }

  for (const item of settings.general) {
    section.appendChild(settingRow(item, onDirty));
  }
  section.appendChild(el('div', { class: 'z-settings__buttons' }, cancel, save));
  return section;
}

// ---------------------------------------------------------------------------
// Content folders
// ---------------------------------------------------------------------------

function folderRow(folder: FolderView, contentTypes: readonly string[]): HTMLElement {
  const assigned = folder.contentTypes;
  const summary =
    assigned.length === 0 ? 'Any content type' : assigned.join(', ');

  const actions = el('div', { class: 'z-toolbar__group' });
  if (contentTypes.length === 0) {
    actions.appendChild(el('span', { class: 'z-muted' }, 'No content types defined'));
  } else {
    actions.appendChild(
      menuButton({
        label: 'Content types',
        value: summary,
        align: 'end',
        items: contentTypes.map((name) => ({
          id: name,
          label: name,
          checked: assigned.includes(name),
        })),
        onSelect(id) {
          const next = assigned.includes(id)
            ? assigned.filter((name) => name !== id)
            : [...assigned, id];
          post('updateSetting', { key: FOLDER_CONTENT_TYPES_KEY, path: folder.path, value: next });
        },
      }),
    );
  }
  actions.appendChild(
    el(
      'button',
      {
        class: 'z-icon-btn z-icon-btn--danger',
        type: 'button',
        title: `Unregister ${folder.title}`,
        onclick: () => {
          // The host confirms; unregistering hides content from every surface.
          post('unregisterFolder', { path: folder.path });
        },
      },
      icon('trash'),
    ),
  );

  return el(
    'div',
    { class: 'z-settings__row' },
    el(
      'div',
      {},
      el('label', { title: folder.path }, folder.title),
      el('p', { class: 'z-settings__description' }, folder.relPath),
    ),
    actions,
  );
}

function foldersSection(settings: SettingsState): HTMLElement {
  const section = el('section', { class: 'z-settings__section' }, el('h2', {}, 'Content folders'));
  if (settings.folders.length === 0) {
    section.appendChild(
      el('p', { class: 'z-empty' }, 'No content folders are registered yet.'),
    );
  } else {
    for (const folder of settings.folders) {
      section.appendChild(folderRow(folder, settings.contentTypes));
    }
  }
  section.appendChild(
    el(
      'div',
      { class: 'z-settings__buttons' },
      el(
        'button',
        {
          class: 'z-btn',
          type: 'button',
          title: 'Pick a folder to register as content',
          onclick: () => {
            post('registerFolder');
          },
        },
        'Register a folder',
      ),
      el(
        'button',
        {
          class: 'z-btn z-btn--secondary',
          type: 'button',
          title: 'Open the project configuration file',
          onclick: () => {
            post('openProject');
          },
        },
        'Open project configuration',
      ),
    ),
  );
  return section;
}

// ---------------------------------------------------------------------------
// The route
// ---------------------------------------------------------------------------

export function render(host: HTMLElement, state: DashboardState): void {
  mounted = { host, state };
  reconcile(state.settings.general);
  clear(host);
  host.appendChild(
    el(
      'div',
      { class: 'z-settings' },
      generalSection(state.settings),
      foldersSection(state.settings),
    ),
  );
}

/** Test seam: forget every staged edit. */
export function resetPending(): void {
  pending.clear();
}
