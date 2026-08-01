/**
 * The Metadata section: the content-type validator hint, the front-matter
 * error state, and the field list.
 *
 * This module owns the *frame*; the eighteen field controls belong to
 * `./fields` (WP12) and are reached through one call, `createField(ctx)`. That
 * boundary is the point: this file knows that a field has a value, a path and
 * an `onChange`, and knows nothing about how a slug field talks to the host or
 * how a tag picker flips its dropdown above the input.
 *
 * ### The widget registry
 *
 * Two host messages address a control rather than the page — `focus` (from the
 * `zer0Cms.focusTags` / `focusCategories` keybindings) and `progress` with a
 * `field` scope. Neither can be expressed as state, so this module keeps the
 * live widgets in a list and routes those two messages to them.
 *
 * The list is rebuilt on every render and every widget's `dispose()` is called
 * first. The reconciler rebuilds a stale section by clearing its host, which
 * detaches the old nodes but does not unhook their listeners — without the
 * explicit dispose, a panel left open across a day of editing would accumulate
 * one listener set per snapshot.
 *
 * ### Values go out whole, not as diffs
 *
 * `onChange` posts `{type:'updateField', path, value}` and the host performs
 * the line surgery that changes only that key's lines (decision D7). The
 * webview never sends "front matter", only "this key is now this value", so a
 * panel rendered from a stale snapshot cannot overwrite a key somebody else
 * edited in the meantime.
 */

import { el, icon } from '../shared/dom';
import { getMessenger } from '../shared/messenger';
import type {
  ActionItem,
  Field,
  FieldWidget,
  FmValue,
  PanelState,
} from '../shared/protocol';
import { staleOn, type Section } from '../shared/state';
import { panelSection } from './chrome';
import { createField } from './fields';

const msg = getMessenger();

interface LiveField {
  field: Field;
  key: string;
  widget: FieldWidget;
}

let live: LiveField[] = [];

function disposeAll(): void {
  for (const entry of live) {
    entry.widget.dispose();
  }
  live = [];
}

/**
 * Move focus into the tags or categories control.
 *
 * `search` is a dashboard target and never arrives here; it is accepted so the
 * caller can forward the whole `focus` message without narrowing it first.
 */
export function focusTaxonomyField(target: 'tags' | 'categories' | 'search'): void {
  if (target === 'search') {
    return;
  }
  const entry = live.find((candidate) => candidate.field.type === target);
  if (entry === undefined) {
    msg.log('verbose', `panel: no ${target} field to focus on this content type`);
    return;
  }
  entry.widget.focus();
}

/**
 * Route a `progress` message with a `field` scope. An absent path addresses
 * every field, which is how the host clears a stuck overlay after an error.
 */
export function setFieldProgress(path: readonly string[] | undefined, message: string | null): void {
  const key = path === undefined ? undefined : path.join('.');
  for (const entry of live) {
    if (key === undefined || entry.key === key) {
      entry.widget.setLoading(message);
    }
  }
}

// ---------------------------------------------------------------------------
// The two non-field bodies
// ---------------------------------------------------------------------------

/**
 * The content-type mismatch hint: a warning block naming the difference, then
 * the three remediation buttons the host supplied. The actions arrive as data
 * so that "which repairs are offered" stays a host decision.
 */
function contentTypeHint(message: string, actions: readonly ActionItem[]): HTMLElement {
  const block = el(
    'div',
    { class: 'metadata__hint' },
    el(
      'div',
      { class: 'metadata_field__label' },
      icon('warning'),
      el('span', {}, 'Content-type'),
    ),
  );
  for (const line of message.split('\n')) {
    if (line.trim() !== '') {
      block.appendChild(el('p', { class: 'inline_hint' }, line));
    }
  }
  for (const action of actions) {
    block.appendChild(
      el(
        'button',
        {
          class: 'z-btn z-btn--secondary',
          type: 'button',
          title: action.title ?? action.label,
          disabled: action.disabled === true,
          onclick: () => {
            msg.command(action.id, action.args);
          },
        },
        action.label,
      ),
    );
  }
  return block;
}

/**
 * The front-matter parse-error state. The fields are replaced entirely: a form
 * rendered over a block we could not read would invite an edit that rewrites
 * whatever survived parsing, which is how you lose the rest of the block.
 */
function errorState(message: string): HTMLElement {
  return el(
    'div',
    { class: 'metadata__error' },
    el('p', {}, message),
    el(
      'button',
      {
        class: 'z-btn z-btn--secondary',
        type: 'button',
        title: 'Check the problems view for more information',
        onclick: () => {
          msg.command('showProblems');
        },
      },
      'Check the problems view for more information',
    ),
  );
}

// ---------------------------------------------------------------------------
// The field list
// ---------------------------------------------------------------------------

function fieldList(state: PanelState): HTMLElement {
  const container = el('div', { class: 'metadata_fields' });
  const data = state.metadata ?? {};

  for (const field of state.fields) {
    const value: FmValue | undefined = data[field.name];
    const widget = createField({
      field,
      parents: [],
      value,
      state,
      msg,
      onChange(next: FmValue | undefined) {
        // `undefined` means "clear this key"; the host maps it to the field's
        // empty value rather than writing the literal string "undefined".
        msg.updateField([field.name], next);
      },
    });
    if (widget === null) {
      // A hidden field, a `when` clause that is false, or a type with no
      // factory. All three are "render nothing", and the dispatcher has
      // already logged the third.
      continue;
    }
    live.push({ field, key: field.name, widget });
    container.appendChild(widget.el);
  }

  return container;
}

// ---------------------------------------------------------------------------
// The section
// ---------------------------------------------------------------------------

function digest(state: PanelState): string {
  // The host builds a fresh `PanelState` for every post, so comparing object
  // identity would make this section stale on every snapshot and defeat the
  // reconciler's focus preservation. Front matter is a few hundred bytes.
  return state.metadata === null ? '' : JSON.stringify(state.metadata);
}

export const metadataSection: Section<PanelState> = {
  id: 'metadata',
  stale: staleOn(
    (state) => state.sections.includes('metadata'),
    (state) => state.filePath,
    (state) => state.contentTypeName,
    (state) => state.fmError,
    (state) => state.contentTypeHint?.message ?? null,
    (state) => state.fields.map((field) => `${field.name}:${field.type}`).join('|'),
    (state) => state.violations.map((violation) => violation.path.join('.')).join('|'),
    (state) => digest(state),
    (state) => state.taxonomy.tags.join('|'),
    (state) => state.taxonomy.categories.join('|'),
  ),
  render(state, host) {
    disposeAll();
    if (!state.sections.includes('metadata') || state.metadata === null) {
      return;
    }

    const title =
      state.contentTypeName === null ? 'Metadata' : `Metadata (${state.contentTypeName})`;
    const children: Array<HTMLElement | null> = [];

    if (state.contentTypeHint !== null) {
      children.push(contentTypeHint(state.contentTypeHint.message, state.contentTypeHint.actions));
    }
    children.push(state.fmError === null ? fieldList(state) : errorState(state.fmError));

    host.appendChild(
      panelSection({ id: 'metadata', title, hasFile: true, className: 'inherit' }, ...children),
    );
  },
};
