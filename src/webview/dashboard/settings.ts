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
 * Each control writes into a staged map and **Save** flushes it, which is what
 * makes "Save is disabled until something changed" a fact about the data rather
 * than a flag somebody has to remember to set. The map survives a state
 * snapshot on purpose — a half-typed page size must not be erased by an
 * unrelated refresh — and an entry clears itself the moment the host reports
 * the value it was asking for. So a refused write visibly stays dirty instead
 * of quietly pretending it landed.
 *
 * That whole pattern now lives in `shared/form.ts` as `stagedForm`, **keyed by
 * a form id**. It used to be a `pending` map at this module's scope, which was
 * correct for exactly as long as there was one form on the screen; PR3's site
 * profile and PR4's lane scaffolder are the second and third users, and two
 * module-scoped maps under one key is not a bug anybody finds by reading.
 */

import { menuButton } from '../shared/components';
import { clear, el, icon } from '../shared/dom';
import { stagedForm, resetStagedForm } from '../shared/form';
import { getMessenger } from '../shared/messenger';
import type {
  CommandId,
  DashboardState,
  FolderView,
  SettingsState,
} from '../shared/protocol';

/**
 * The key under which a folder's content-type assignment is written. The value
 * is the folder's full content-type list and `path` names which folder — a
 * target, never an override.
 */
export const FOLDER_CONTENT_TYPES_KEY = 'contentFolder.contentTypes';

/** The staged-edit bucket this route owns. One form, one id. */
export const GENERAL_FORM_KEY = 'settings.general';

function post(id: CommandId, args?: unknown): void {
  getMessenger().command(id, args);
}

// ---------------------------------------------------------------------------
// General
// ---------------------------------------------------------------------------

function generalSection(settings: SettingsState): HTMLElement {
  return el(
    'section',
    { class: 'z-settings__section' },
    el('h2', {}, 'General'),
    stagedForm({
      key: GENERAL_FORM_KEY,
      items: settings.general,
      emptyMessage: 'No settings to configure.',
      onSave(changes) {
        // One intent per changed key. The host owns which keys exist and
        // re-reads its own configuration afterwards; nothing here assumes the
        // write succeeded — the next snapshot decides that.
        for (const change of changes) {
          post('updateSetting', { key: change.key, value: change.value });
        }
      },
    }).el,
  );
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

/** Test seam: forget every staged edit on this route's form. */
export function resetPending(): void {
  resetStagedForm(GENERAL_FORM_KEY);
}
