/**
 * `stagedForm` — a settings form whose edits are staged and flushed by Save,
 * keyed by a form id rather than by module scope.
 *
 * The Settings route invented this pattern and held its `pending` map at module
 * scope, which worked for exactly as long as there was one form on the screen.
 * PR4's lane-scaffolding form and PR3's site profile are the second and third
 * users, and two module-scoped maps under one key is not a bug you find by
 * reading — it is a bug you find when somebody's half-typed cron minute lands
 * in somebody else's page size. So the staging map is `Map<formKey, Map<setting
 * key, value>>` and the form id is a required argument.
 *
 * ## What staging buys
 *
 * **"Save is disabled until something changed" becomes a fact about the data**
 * rather than a flag somebody has to remember to set: the button is disabled
 * exactly when the staged map is empty.
 *
 * **The map survives a state snapshot.** A half-typed value must not be erased
 * by an unrelated refresh, so `reconcile()` drops only two kinds of entry: one
 * whose key the host no longer offers, and one whose staged value the host has
 * caught up with. What is left is exactly "changes not yet on disk" — which
 * means a *refused* write visibly stays dirty instead of quietly pretending it
 * landed.
 *
 * ## Decision D5, in a form
 *
 * `onSave` is handed `{key, value}` pairs and nothing else. `SettingItem.key`
 * arrived *from* the host, so a form can only ever hand back a key the host
 * itself offered; the caller turns each pair into one `updateSetting` intent
 * and the host decides what that key means and where it lands. Nothing here
 * writes anything, and `secretName` is the whole reason that sentence has to be
 * exact: the console handles the *name* of a credential and never its value.
 */

import { menuButton, toggle } from './components';
import { clear, el } from './dom';
import type { SettingItem } from './protocol';

export type SettingValue = string | number | boolean;

/** One staged change, as `onSave` receives it. */
export interface StagedChange {
  key: string;
  value: SettingValue;
}

export interface StagedFormOptions {
  /** The form id. Two forms with different ids never share staged edits. */
  key: string;
  items: readonly SettingItem[];
  /** Called with every changed key. The caller posts the intents. */
  onSave(changes: readonly StagedChange[]): void;
  /** Called after the staged edits are dropped, if the caller needs to know. */
  onCancel?(): void;
  saveLabel?: string;
  cancelLabel?: string;
  /** Drawn instead of the rows when `items` is empty. */
  emptyMessage?: string;
  /** Extra class on the form root. */
  className?: string;
}

export interface StagedFormHandle {
  el: HTMLElement;
  /** True while at least one edit has not been saved. */
  dirty(): boolean;
  /** The staged edits, as `onSave` would receive them. */
  changes(): StagedChange[];
  /** Drop the staged edits and repaint. What Cancel does. */
  reset(): void;
}

/**
 * Every form's staged edits, keyed by form id then by setting key.
 *
 * Module-scoped on purpose: a form is rebuilt from scratch on every snapshot
 * (the reconciler's teardown is `clear(host)` plus `render`), so the staging
 * has to outlive the elements. It is *keyed* so that outliving them is the only
 * thing it does.
 */
const staged = new Map<string, Map<string, SettingValue>>();

function bucket(formKey: string): Map<string, SettingValue> {
  let map = staged.get(formKey);
  if (map === undefined) {
    map = new Map<string, SettingValue>();
    staged.set(formKey, map);
  }
  return map;
}

/** The staged edits for one form, for a caller that renders its own buttons. */
export function stagedChanges(formKey: string): StagedChange[] {
  return [...bucket(formKey)].map(([key, value]) => ({ key, value }));
}

/** Forget one form's staged edits, or every form's when the id is omitted. */
export function resetStagedForm(formKey?: string): void {
  if (formKey === undefined) {
    staged.clear();
  } else {
    staged.delete(formKey);
  }
}

/**
 * Drop staged edits the host has caught up with, and edits whose key is no
 * longer offered. Exported because a route may want to reconcile before it
 * decides whether to draw the form at all.
 */
export function reconcileStagedForm(formKey: string, items: readonly SettingItem[]): void {
  const map = bucket(formKey);
  const offered = new Map(items.map((item) => [item.key, item.value] as const));
  for (const key of [...map.keys()]) {
    if (!offered.has(key) || Object.is(offered.get(key), map.get(key))) {
      map.delete(key);
    }
  }
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

/** A `multichoice` value travels as a comma-separated list of choice ids. */
export function splitMultichoice(value: SettingValue): string[] {
  return String(value)
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part !== '');
}

/** The inverse. Order is the user's selection order, never re-sorted. */
export function joinMultichoice(values: readonly string[]): string {
  return values.join(', ');
}

function currentValue(map: Map<string, SettingValue>, item: SettingItem): SettingValue {
  const value = map.get(item.key);
  return value === undefined ? item.value : value;
}

function stage(
  map: Map<string, SettingValue>,
  item: SettingItem,
  value: SettingValue,
  onDirty: () => void,
): void {
  if (Object.is(value, item.value)) {
    map.delete(item.key);
  } else {
    map.set(item.key, value);
  }
  onDirty();
}

function textControl(
  map: Map<string, SettingValue>,
  item: SettingItem,
  onDirty: () => void,
): HTMLElement {
  const value = currentValue(map, item);
  const monospaced = item.kind === 'path' || item.kind === 'secretName';
  const input = el('input', {
    class: monospaced ? 'z-field__input z-field__input--mono' : 'z-field__input',
    type: item.kind === 'number' ? 'number' : 'text',
    value: String(value),
    attrs: {
      'aria-label': item.label,
      ...(monospaced ? { spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off' } : {}),
      ...(item.kind === 'path' ? { placeholder: 'workspace-relative path' } : {}),
      ...(item.kind === 'secretName' ? { placeholder: 'SECRET_NAME' } : {}),
    },
    on: {
      input: (event) => {
        const target = event.target;
        if (!(target instanceof HTMLInputElement)) {
          return;
        }
        if (item.kind === 'number') {
          const parsed = Number(target.value);
          stage(map, item, Number.isFinite(parsed) ? parsed : 0, onDirty);
        } else {
          stage(map, item, target.value, onDirty);
        }
      },
    },
  });
  const field = el('div', { class: 'z-field' }, input);
  if (item.kind === 'secretName') {
    // The console reads a secret's *name*. It has no business holding the
    // value, and saying so where the value would be typed is cheaper than
    // explaining it after somebody has pasted one.
    field.appendChild(
      el('p', { class: 'z-form__hint' }, 'The name of the secret. Never its value.'),
    );
  }
  if (item.kind === 'path') {
    field.appendChild(
      el('p', { class: 'z-form__hint' }, 'Resolved by the host, relative to the site root.'),
    );
  }
  return field;
}

function choiceControl(
  map: Map<string, SettingValue>,
  item: SettingItem,
  onDirty: () => void,
): HTMLElement {
  const value = String(currentValue(map, item));
  const select = el('select', {
    attrs: { 'aria-label': item.label },
    on: {
      change: (event) => {
        const target = event.target;
        if (target instanceof HTMLSelectElement) {
          stage(map, item, target.value, onDirty);
        }
      },
    },
  });
  const choices = item.choices ?? [];
  for (const choice of choices) {
    select.appendChild(el('option', { value: choice, selected: choice === value }, choice));
  }
  // A value the host offers no choice for is still the truth about the
  // configuration; showing it beats silently selecting the first option.
  if (!choices.includes(value)) {
    select.insertBefore(el('option', { value, selected: true }, value), select.firstChild);
  }
  return select;
}

function multichoiceControl(
  map: Map<string, SettingValue>,
  item: SettingItem,
  onDirty: () => void,
  repaint: () => void,
): HTMLElement {
  const selected = splitMultichoice(currentValue(map, item));
  const choices = item.choices ?? [];
  if (choices.length === 0) {
    // With nothing to pick from, a menu with an empty list is a dead control.
    // The free-text field at least shows what is configured.
    return textControl(map, item, onDirty);
  }
  return menuButton({
    label: item.label,
    value: selected.length === 0 ? 'None' : joinMultichoice(selected),
    align: 'end',
    items: choices.map((choice) => ({
      id: choice,
      label: choice,
      checked: selected.includes(choice),
    })),
    onSelect(id) {
      const next = selected.includes(id)
        ? selected.filter((choice) => choice !== id)
        : [...selected, id];
      stage(map, item, joinMultichoice(next), onDirty);
      // The trigger shows the selection, so the menu has to be rebuilt for the
      // tick to move. Every other control paints its own value in place.
      repaint();
    },
  });
}

function control(
  map: Map<string, SettingValue>,
  item: SettingItem,
  onDirty: () => void,
  repaint: () => void,
): HTMLElement {
  switch (item.kind) {
    case 'boolean':
      return toggle({
        checked: currentValue(map, item) === true,
        onChange(checked) {
          stage(map, item, checked, onDirty);
        },
      }).el;
    case 'choice':
      return choiceControl(map, item, onDirty);
    case 'multichoice':
      return multichoiceControl(map, item, onDirty, repaint);
    default:
      return textControl(map, item, onDirty);
  }
}

function settingRow(
  map: Map<string, SettingValue>,
  item: SettingItem,
  onDirty: () => void,
  repaint: () => void,
): HTMLElement {
  return el(
    'div',
    { class: 'z-settings__row' },
    el(
      'div',
      {},
      el('label', {}, item.label),
      item.description === undefined
        ? null
        : el('p', { class: 'z-settings__description' }, item.description),
    ),
    control(map, item, onDirty, repaint),
  );
}

// ---------------------------------------------------------------------------
// The form
// ---------------------------------------------------------------------------

/**
 * Build one staged form. The returned root repaints itself on Cancel and on a
 * `multichoice` selection; every other control updates in place.
 */
export function stagedForm(options: StagedFormOptions): StagedFormHandle {
  const map = bucket(options.key);
  reconcileStagedForm(options.key, options.items);

  const root = el('div', {
    class: options.className ? `z-form ${options.className}` : 'z-form',
    dataset: { form: options.key },
  });

  const paint = (): void => {
    clear(root);

    if (options.items.length === 0) {
      root.appendChild(
        el('p', { class: 'z-empty' }, options.emptyMessage ?? 'Nothing to configure.'),
      );
      return;
    }

    const save = el(
      'button',
      {
        class: 'z-btn',
        type: 'button',
        disabled: map.size === 0,
        title: 'Write the changed settings',
        onclick: () => {
          // One entry per changed key. Nothing here assumes the write
          // succeeded — the next snapshot's `reconcile` decides that.
          options.onSave([...map].map(([key, value]) => ({ key, value })));
        },
      },
      options.saveLabel ?? 'Save',
    );
    const cancel = el(
      'button',
      {
        class: 'z-btn z-btn--secondary',
        type: 'button',
        title: 'Discard the changes that have not been saved',
        onclick: () => {
          map.clear();
          paint();
          options.onCancel?.();
        },
      },
      options.cancelLabel ?? 'Cancel',
    );
    const onDirty = (): void => {
      save.disabled = map.size === 0;
    };

    for (const item of options.items) {
      root.appendChild(settingRow(map, item, onDirty, paint));
    }
    root.appendChild(el('div', { class: 'z-settings__buttons' }, cancel, save));
  };

  paint();

  return {
    el: root,
    dirty: () => map.size > 0,
    changes: () => [...map].map(([key, value]) => ({ key, value })),
    reset() {
      map.clear();
      paint();
    },
  };
}
