/**
 * The four tail sections of the panel: Actions, Recently modified, Global
 * settings and Other actions.
 *
 * They are four separate `Section`s rather than one, for two reasons. The
 * reconciler rebuilds at section granularity, so a snapshot that only changed
 * the recent-files list must not tear down the settings toggles the user is
 * halfway through clicking. And `zer0Cms.panel.sections` selects them
 * individually — a workspace that wants the panel to be nothing but metadata
 * and governance says so by listing two ids, and the other five never mount.
 *
 * ### Collapse ids are not section ids
 *
 * `Section.id` is the configuration vocabulary (`recent`, `other`); the
 * *collapse* key is Front Matter's (`content` / `base_content`,
 * `other_actions` / `base_other_actions`). Keeping the old keys means a user
 * upgrading from the fork keeps the sections they had closed, closed.
 *
 * ### The settings toggles write settings, not state
 *
 * Each posts `{type:'command', id:'updateSetting', args:{key, value}}`, and the
 * host holds a four-entry allow-list mapping those keys onto
 * `zer0Cms.*` settings. The webview cannot name an arbitrary setting: the
 * closed `CommandId` union gets it as far as "I would like to update a
 * setting", and the host decides which ones exist (D5). The control repaints
 * from the next snapshot, not from its own click, so a write that is refused
 * visibly springs back.
 */

import { toggle } from '../shared/components';
import { el, icon } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type { PanelSettingsState, PanelState, RecentFolder } from '../shared/protocol';
import { staleOn, type Section } from '../shared/state';
import { DOCS_URL, commandButton, linkRow, panelSection } from './chrome';

const msg = getMessenger();

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/**
 * Five of Front Matter's eight buttons, in its order.
 *
 * "Optimize slug" and "Smart rename" collapsed into one **Regenerate slug**:
 * `zer0Cms.generateSlug` builds the slug *and* offers to rename the file to
 * match, so two buttons would have been two names for one command. Preview,
 * Open on website, Start/Stop server and the custom-script buttons are gone
 * with the subsystems behind them (PLAN §3.1).
 */
export const actionsSection: Section<PanelState> = {
  id: 'actions',
  stale: staleOn(
    (state) => state.sections.includes('actions'),
    (state) => state.filePath,
    (state) => state.metadata === null,
    (state) => state.initialized,
  ),
  render(state, host) {
    if (!state.sections.includes('actions')) {
      return;
    }
    const hasFile = state.filePath !== null;
    host.appendChild(
      panelSection(
        { id: 'actions', title: 'Actions', hasFile, className: 'article__actions' },
        commandButton({ label: 'Open dashboard', id: 'dashboard' }),
        commandButton({
          label: 'Regenerate slug',
          id: 'generateSlug',
          title: 'Build the slug from the title, and offer to rename the file',
          secondary: true,
          // Gated on "a file with front matter is open" rather than on the
          // title itself: the panel does not know which key is the title when
          // the SEO section is switched off, and the command already reports a
          // missing title by name.
          disabled: state.metadata === null,
        }),
        commandButton({ label: 'Create content', id: 'createContent', secondary: true }),
        commandButton({
          label: 'Insert image',
          id: 'insertImage',
          secondary: true,
          disabled: !hasFile,
        }),
      ),
    );
  },
};

// ---------------------------------------------------------------------------
// Recently modified
// ---------------------------------------------------------------------------

function fileList(folder: RecentFolder): HTMLElement {
  const noun = folder.files.length === 1 ? 'file' : 'files';
  const items = el('ul', { class: 'file_list__items' });
  for (const file of folder.files) {
    items.appendChild(
      el(
        'li',
        {
          class: 'file_list__items__item',
          title: file.path,
          onclick: () => {
            msg.command('openFile', { path: file.path });
          },
        },
        icon(file.markdown ? 'markdown' : 'file'),
        el('span', {}, file.name),
      ),
    );
  }
  return el(
    'div',
    { class: 'file_list' },
    el('label', {}, `${folder.title} - ${noun}: ${folder.totalFiles}`),
    items,
  );
}

/** Ten files per folder, capped host-side. Absent entirely when there are none. */
export const recentSection: Section<PanelState> = {
  id: 'recent',
  stale: staleOn(
    (state) => state.sections.includes('recent'),
    (state) => state.filePath !== null,
    (state) =>
      state.recent
        .map((folder) => `${folder.title}:${folder.totalFiles}:${folder.files.length}`)
        .join('|'),
    (state) => state.recent.map((folder) => folder.files.map((f) => f.path).join(',')).join('|'),
  ),
  render(state, host) {
    if (!state.sections.includes('recent') || state.recent.length === 0) {
      return;
    }
    host.appendChild(
      panelSection(
        {
          // Front Matter's key, kept so an upgrade keeps the user's choice.
          id: 'content',
          title: 'Recently modified',
          hasFile: state.filePath !== null,
          className: 'information',
        },
        ...state.recent.map(fileList),
      ),
    );
  },
};

// ---------------------------------------------------------------------------
// Global settings
// ---------------------------------------------------------------------------

interface SettingRow {
  label: string;
  text: string;
  key: keyof PanelSettingsState;
}

/** The four booleans. Front Matter's two text inputs went with the preview and
 *  terminal subsystems they configured. */
const SETTING_ROWS: readonly SettingRow[] = [
  { label: 'Modified date', text: 'Auto-update modified date', key: 'autoUpdateModifiedDate' },
  { label: 'Metadata panel', text: 'Open panel for supported files', key: 'openOnSupportedFile' },
  { label: 'SEO', text: 'Show SEO status', key: 'seoEnabled' },
  { label: 'AI agent', text: 'Enable AI agent', key: 'agentEnabled' },
];

function settingRow(row: SettingRow, settings: PanelSettingsState): HTMLElement {
  const control = toggle({
    checked: settings[row.key],
    label: row.text,
    onChange(checked) {
      msg.command('updateSetting', { key: row.key, value: checked });
    },
  });
  return el('div', { class: 'base__action' }, el('label', {}, row.label), control.el);
}

export const settingsSection: Section<PanelState> = {
  id: 'settings',
  stale: staleOn(
    (state) => state.sections.includes('settings'),
    (state) => state.filePath !== null,
    (state) => state.settings.autoUpdateModifiedDate,
    (state) => state.settings.openOnSupportedFile,
    (state) => state.settings.seoEnabled,
    (state) => state.settings.agentEnabled,
  ),
  render(state, host) {
    if (!state.sections.includes('settings')) {
      return;
    }
    host.appendChild(
      panelSection(
        {
          id: 'settings',
          title: 'Global settings',
          hasFile: state.filePath !== null,
          className: 'base__actions',
        },
        ...SETTING_ROWS.map((row) => settingRow(row, state.settings)),
      ),
    );
  },
};

// ---------------------------------------------------------------------------
// Other actions
// ---------------------------------------------------------------------------

export const otherActionsSection: Section<PanelState> = {
  id: 'other',
  stale: staleOn(
    (state) => state.sections.includes('other'),
    (state) => state.filePath,
  ),
  render(state, host) {
    if (!state.sections.includes('other')) {
      return;
    }
    const filePath = state.filePath;
    host.appendChild(
      panelSection(
        {
          id: 'other_actions',
          title: 'Other actions',
          hasFile: filePath !== null,
          className: 'other_actions',
        },
        linkRow({
          label: 'Reveal file in folder',
          icon: 'file',
          disabled: filePath === null,
          onClick: () => {
            if (filePath !== null) {
              msg.command('revealFile', { path: filePath });
            }
          },
        }),
        linkRow({
          label: 'Reveal project folder',
          icon: 'folder-opened',
          onClick: () => {
            msg.command('openProject');
          },
        }),
        linkRow({
          label: 'Run CMS engine',
          icon: 'play',
          title: 'Rebuild the .cms/ contract',
          onClick: () => {
            msg.command('contract.run');
          },
        }),
        linkRow({
          label: 'Normalize front matter (preview)',
          icon: 'symbol-ruler',
          title: 'Show what the normalizer would change. Writes nothing.',
          onClick: () => {
            msg.command('contract.normalizePreview');
          },
        }),
        linkRow({
          label: 'Open documentation',
          icon: 'book',
          onClick: () => {
            msg.command('openLink', { url: DOCS_URL });
          },
        }),
      ),
    );
  },
};
