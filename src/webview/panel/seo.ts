/**
 * The SEO Status section: the insights table, the keywords table, and the
 * hidden-chrome keyword editor.
 *
 * Everything numeric here was computed by `core/content/seo.ts` and arrives in
 * `PanelState.seo` already decided. This file draws it and nothing else — it
 * does not re-derive a length, re-check a threshold or re-run a density
 * calculation, because the same numbers are shown by the dashboard and reported
 * by the MCP `zer0_status` tool, and three implementations of "is this title
 * too long" is three chances to disagree.
 *
 * Four rules from the recon that are easy to lose and worth naming:
 *
 *  - **A threshold of `<= 0` suppresses its row.** That is the host's job, and
 *    it means an absent row is a deliberate "do not tell me about this", not a
 *    missing measurement. This file renders `state.seo.rows` in array order and
 *    adds nothing to it.
 *  - **Article length is never validated.** It carries a recommendation and no
 *    `isValid`, so it renders the em-dash spacer rather than a tick or a
 *    warning. A 1,200-word article is not wrong; it is shorter than the goal.
 *  - **The insights table is two-state, never red.** Green check or amber
 *    warning. There is no error state in SEO advice — advice you cannot ignore
 *    is a gate, and gates live in the governance section.
 *  - **The density band is `>= 0.75 && < 1.5`.** Inside it the frequency reads
 *    green, outside amber, and a keyword with no word count to divide by shows
 *    nothing at all rather than `0.00 %`.
 *
 * The keyword editor reproduces Front Matter's oddest and best idea: the picker
 * renders with its label and its pill list hidden by CSS, so the section shows
 * one bare input while the pills live in the table above where they can carry
 * their own scores.
 */

import { tagPill, validInfo } from '../shared/components';
import { clear, el, on } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type { KeywordInfoView, PanelState, SeoRowView, SeoState } from '../shared/protocol';
import { staleOn, type Section } from '../shared/state';
import { panelSection } from './chrome';

const msg = getMessenger();

/** The band the panel paints green. Mirrors `DENSITY_MIN`/`DENSITY_MAX` in
 *  `src/core/content/seo.ts`, which cannot be imported into a browser bundle. */
export const DENSITY_MIN = 0.75;
export const DENSITY_MAX = 1.5;

function isHealthyDensity(density: number | null): boolean {
  return density !== null && density >= DENSITY_MIN && density < DENSITY_MAX;
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------

function insightRow(row: SeoRowView): HTMLElement {
  const value =
    row.recommendation === undefined ? String(row.value) : `${row.value}/${row.recommendation}`;
  return el(
    'tr',
    {},
    el('td', { class: 'seo__table__label' }, row.label),
    el('td', {}, el('div', { class: 'seo__table__value' }, validInfo(row.isValid), value)),
  );
}

function insights(seo: SeoState): HTMLElement {
  const table = el('table', { class: 'seo__table' });
  const rows = el('tbody', {});
  for (const row of seo.rows) {
    rows.appendChild(insightRow(row));
  }
  table.appendChild(rows);
  return el(
    'section',
    { class: 'seo__insights' },
    el('h4', {}, 'Insights'),
    el('div', { style: 'overflow-x: auto;' }, table),
  );
}

// ---------------------------------------------------------------------------
// Keywords
// ---------------------------------------------------------------------------

/** The six presence checks, as a plain-text tooltip. No tooltip library. */
function checksTitle(info: KeywordInfoView): string {
  const lines = info.checks.map((check) => `${check.name}: ${check.passed ? 'yes' : 'no'}`);
  return ['Keyword present in:', ...lines].join('\n');
}

function checksBadge(info: KeywordInfoView): HTMLElement {
  const passed = info.passed === info.total;
  return el(
    'span',
    {
      class: passed ? 'seo__keyword__check valid' : 'seo__keyword__check warning',
      title: checksTitle(info),
    },
    validInfo(passed),
    `${info.passed}/${info.total}`,
  );
}

function frequencyCell(info: KeywordInfoView): HTMLElement {
  if (info.density === null) {
    return el('td', {});
  }
  return el(
    'td',
    {},
    el(
      'span',
      {
        class: isHealthyDensity(info.density)
          ? 'seo__keyword__check valid'
          : 'seo__keyword__check warning',
        title: `Recommended frequency: ${DENSITY_MIN}% - ${DENSITY_MAX}%`,
      },
      `${info.density.toFixed(2)}* %`,
    ),
  );
}

function removeKeyword(seo: SeoState, value: string): void {
  const next = seo.keywords
    .map((info) => info.keyword)
    .filter((keyword) => keyword.toLowerCase() !== value.toLowerCase());
  msg.updateField(['keywords'], next);
}

function keywordsTable(seo: SeoState): HTMLElement | null {
  if (seo.keywords.length === 0) {
    return null;
  }
  const head = el(
    'tr',
    {},
    el('th', {}, 'Keyword'),
    el('th', {}, 'Checks'),
    el('th', { title: 'Keyword density' }, 'Frequency'),
  );
  const rows = el('tbody', {});
  for (const info of seo.keywords) {
    rows.appendChild(
      el(
        'tr',
        {},
        el(
          'td',
          {},
          tagPill({
            value: info.keyword,
            known: true,
            removeTitle: `Be aware, this keyword "${info.keyword}" is not saved in your settings. Once removed, it will be gone forever.`,
            onRemove: (value) => {
              removeKeyword(seo, value);
            },
          }),
        ),
        el('td', {}, checksBadge(info)),
        frequencyCell(info),
      ),
    );
  }
  const table = el('table', { class: 'seo__table' }, el('thead', {}, head), rows);
  return el(
    'section',
    { class: 'seo__keywords' },
    el('h4', {}, 'Keywords'),
    el('div', { style: 'overflow-x: auto;' }, table),
    seo.wordCount > 0
      ? el(
          'p',
          { class: 'z-muted' },
          '* A keyword density of 1-1.5% is sufficient in most cases.',
        )
      : null,
  );
}

// ---------------------------------------------------------------------------
// The keyword editor
// ---------------------------------------------------------------------------

/**
 * The bare input. Enter (or the `+` button) splits on commas, trims, drops
 * duplicates case-insensitively, and posts the whole list back — front matter
 * is written as a value, not as a diff, so sending the full array is what makes
 * the host's write a single key change.
 */
function keywordEditor(seo: SeoState): HTMLElement {
  const existing = seo.keywords.map((info) => info.keyword);
  const input = el('input', {
    type: 'text',
    placeholder: 'Pick your keywords',
    attrs: { 'aria-label': 'Add a keyword' },
  });
  const menu = el('ul', { class: 'field_dropdown article__tags__dropbox closed' });

  const commit = (): void => {
    const raw = input.value;
    if (raw.trim() === '') {
      return;
    }
    const seen = new Set(existing.map((keyword) => keyword.toLowerCase()));
    const next = [...existing];
    for (const part of raw.split(',')) {
      const keyword = part.trim();
      if (keyword === '' || seen.has(keyword.toLowerCase())) {
        continue;
      }
      seen.add(keyword.toLowerCase());
      next.push(keyword);
    }
    input.value = '';
    renderMenu();
    msg.updateField(['keywords'], next);
  };

  const add = el(
    'button',
    {
      class: 'article__tags__input__button',
      type: 'button',
      title: 'Add the keyword',
      onclick: commit,
    },
    '+',
  );

  function renderMenu(): void {
    clear(menu);
    const query = input.value.trim().toLowerCase();
    const taken = new Set(existing.map((keyword) => keyword.toLowerCase()));
    const options = seo.suggestions.filter(
      (option) =>
        !taken.has(option.toLowerCase()) &&
        (query === '' || option.toLowerCase().includes(query)),
    );
    const open = options.length > 0 && document.activeElement === input;
    menu.className = open
      ? 'field_dropdown article__tags__dropbox open'
      : 'field_dropdown article__tags__dropbox closed';
    for (const option of options.slice(0, 50)) {
      menu.appendChild(
        el(
          'li',
          {
            attrs: { role: 'option' },
            onclick: () => {
              input.value = option;
              commit();
            },
          },
          option,
        ),
      );
    }
  }

  on(input, 'input', renderMenu);
  on(input, 'focus', renderMenu);
  // `focusout` rather than `blur`: clicking an option must not close the menu
  // before the click lands, and the timeout lets the option's handler win.
  on(input, 'blur', () => {
    setTimeout(renderMenu, 150);
  });
  on(input, 'keydown', (event) => {
    if (event instanceof KeyboardEvent && event.key === 'Enter') {
      event.preventDefault();
      commit();
    }
  });
  renderMenu();

  return el(
    'div',
    { class: 'seo__keywords__picker article__tags' },
    el('div', { class: 'article__tags__input' }, input, add, menu),
  );
}

// ---------------------------------------------------------------------------
// The section
// ---------------------------------------------------------------------------

export const seoSection: Section<PanelState> = {
  id: 'seo',
  stale: staleOn(
    (state) => state.sections.includes('seo'),
    (state) => state.filePath,
    (state) => state.seo === null,
    (state) => state.seo?.rows.map((row) => `${row.label}:${row.value}:${row.isValid}`).join('|') ?? '',
    (state) =>
      state.seo?.keywords
        .map((info) => `${info.keyword}:${info.passed}:${info.density ?? ''}`)
        .join('|') ?? '',
    (state) => state.seo?.suggestions.join('|') ?? '',
    (state) => state.seo?.hasTitle ?? false,
    (state) => state.seo?.hasDescription ?? false,
  ),
  render(state, host) {
    const seo = state.seo;
    if (!state.sections.includes('seo') || seo === null || state.metadata === null) {
      return;
    }

    // Neither a title nor a description: there is nothing to measure, and the
    // honest answer is which field to write first.
    if (!seo.hasTitle && !seo.hasDescription) {
      host.appendChild(
        panelSection(
          { id: 'seo', title: 'SEO Status', hasFile: true },
          el(
            'div',
            { class: 'seo__status__empty' },
            el('p', {}, `${seo.titleField} or ${seo.descriptionField} is required.`),
          ),
        ),
      );
      return;
    }

    host.appendChild(
      panelSection(
        { id: 'seo', title: 'SEO Status', hasFile: true, className: 'seo' },
        insights(seo),
        keywordsTable(seo),
        keywordEditor(seo),
      ),
    );
  },
};
