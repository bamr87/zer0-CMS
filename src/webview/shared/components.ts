/**
 * The shared widget library — eighteen builders that every surface reuses.
 *
 * Each is a plain `(props) => HTMLElement` (or a small handle when the caller
 * needs to talk back to a live control). There is no base class, no lifecycle
 * and no registry: a widget is a function that returns a node, and the section
 * reconciler in `state.ts` decides when to call it again.
 *
 * The visual contract lives in `media/base.css` (the kernel) with per-surface
 * layout in `media/panel.css` and `media/dashboard.css`; this file only ever
 * names classes, never colours. Where a class name looks like Front Matter's
 * (`collapsible__body`, `metadata_field__input`), that is deliberate — the
 * stylesheets carry both vocabularies so the panel code can be read against the
 * same recon that produced the CSS.
 *
 * ## The operator primitives
 *
 * `statusPill`, `dataTable`, `emptyState`, `gatedButton`, `blockerNote`,
 * `keyValueList` and `diffView` were each hand-rolled two or three times over
 * in `dashboard/{fleet,governance,catering}.ts` before they moved here. Five
 * more tabs need all seven, and three copies of "what does a grey cell mean"
 * is how two screens end up disagreeing about the same lane.
 *
 * Two of them carry a rule rather than a look:
 *
 *  - **`unknown` is not `neutral`.** A cell nobody has asked about must not
 *    render like a cell whose answer happens to be "no". `statusPill`'s
 *    `unknown` variant is dashed, italic and unfilled precisely so it reads as
 *    an absence; `neutral` is the ordinary filled badge. The Fleet route's four
 *    honest switch states are the origin of this and the reason it is enforced
 *    here rather than remembered per screen.
 *  - **`gatedButton` is a courtesy, never a control** (decision D5). It renders
 *    a disabled button plus the host's blocker sentence in the gate's own
 *    order, and posts `{id, args}` — an intent and a target. Every gate is
 *    re-checked host-side in the same function the command palette calls, so a
 *    button that renders enabled when the gate says otherwise is a cosmetic
 *    bug, not an escalation.
 */

import { append, clear, debounce, el, icon, on, srOnly, type Child } from './dom';
import { getMessenger } from './messenger';
import type { BlockerView, CommandId } from './protocol';

// ---------------------------------------------------------------------------
// collapsible
// ---------------------------------------------------------------------------

export interface CollapsibleOptions {
  /** Collapse-state key, without the `collapse_` prefix. */
  id: string;
  title: string;
  /** Defaults to open, exactly as Front Matter did. */
  open?: boolean;
  /** Extra class on the body, e.g. `article__actions`. */
  className?: string;
  /** Optional trailing element in the header row (a count, an action). */
  badge?: Child;
  onToggle?(id: string, open: boolean): void;
}

export interface CollapsibleHandle {
  el: HTMLElement;
  body: HTMLElement;
  setOpen(open: boolean): void;
  isOpen(): boolean;
}

export function collapsible(options: CollapsibleOptions, ...children: Child[]): CollapsibleHandle {
  const chevron = icon('chevron-down', 'z-collapsible__chevron');
  const body = el(
    'div',
    { class: options.className ? `section collapsible__body ${options.className}` : 'section collapsible__body' },
    ...children,
  );
  const trigger = el(
    'button',
    {
      class: 'z-collapsible__trigger',
      type: 'button',
      attrs: { 'aria-expanded': 'true', 'aria-controls': `z-sec-${options.id}` },
    },
    chevron,
    el('h3', { class: 'z-collapsible__title' }, options.title),
    options.badge ?? null,
  );
  body.id = `z-sec-${options.id}`;
  const root = el('div', { class: 'z-collapsible', dataset: { section: options.id } }, trigger, body);

  let open = options.open !== false;
  const apply = (): void => {
    root.classList.toggle('is-closed', !open);
    trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  apply();

  trigger.addEventListener('click', () => {
    open = !open;
    apply();
    options.onToggle?.(options.id, open);
  });

  return {
    el: root,
    body,
    isOpen: () => open,
    setOpen(next: boolean) {
      open = next;
      apply();
    },
  };
}

// ---------------------------------------------------------------------------
// menuButton
// ---------------------------------------------------------------------------

export interface MenuItem {
  id: string;
  label: string;
  /** Codicon name. */
  icon?: string;
  checked?: boolean;
  disabled?: boolean;
  danger?: boolean;
  separatorBefore?: boolean;
}

export interface MenuButtonOptions {
  /** Rendered with a trailing colon, as in `Sorting:`. Omit for icon menus. */
  label?: string;
  /** The current value, shown as link-coloured text next to the label. */
  value?: string;
  /** Codicon for a trigger with no label. */
  triggerIcon?: string;
  /** Accessible name when the trigger is icon-only. */
  triggerTitle?: string;
  items: MenuItem[];
  disabled?: boolean;
  align?: 'start' | 'end';
  onSelect(id: string): void;
}

export function menuButton(options: MenuButtonOptions): HTMLElement {
  const list = el('ul', {
    class: options.align === 'end' ? 'z-menu__list z-menu__list--end' : 'z-menu__list',
    attrs: { role: 'menu' },
  });
  const trigger = el(
    'button',
    {
      class: 'z-menu__trigger',
      type: 'button',
      disabled: options.disabled === true,
      title: options.triggerTitle ?? '',
      attrs: { 'aria-haspopup': 'true', 'aria-expanded': 'false' },
    },
    options.label ? el('span', { class: 'z-menu__label' }, `${options.label}:`) : null,
    options.value ? el('span', { class: 'z-menu__value' }, options.value) : null,
    options.triggerIcon ? icon(options.triggerIcon) : icon('chevron-down', 'z-menu__caret'),
    !options.label && options.triggerTitle ? srOnly(options.triggerTitle) : null,
  );
  const root = el('div', { class: 'z-menu' }, trigger, list);

  let open = false;
  let releaseOutside: (() => void) | undefined;
  const setOpen = (next: boolean): void => {
    open = next;
    root.classList.toggle('is-open', open);
    trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    releaseOutside?.();
    releaseOutside = undefined;
    if (!open) {
      return;
    }
    releaseOutside = on(document, 'mousedown', (event) => {
      if (event.target instanceof Node && !root.contains(event.target)) {
        setOpen(false);
      }
    });
  };

  for (const item of options.items) {
    if (item.separatorBefore) {
      list.appendChild(el('li', { class: 'z-menu__separator', attrs: { role: 'separator' } }));
    }
    const entry = el(
      'button',
      {
        class: item.danger ? 'z-menu__item z-menu__item--danger' : 'z-menu__item',
        type: 'button',
        disabled: item.disabled === true,
      },
      item.icon ? icon(item.icon) : null,
      el('span', {}, item.label),
      item.checked ? icon('check', 'z-menu__check') : null,
    );
    entry.addEventListener('click', () => {
      setOpen(false);
      options.onSelect(item.id);
    });
    list.appendChild(el('li', { attrs: { role: 'none' } }, entry));
  }

  trigger.addEventListener('click', () => {
    setOpen(!open);
  });
  root.addEventListener('keydown', (event) => {
    if (event instanceof KeyboardEvent && event.key === 'Escape' && open) {
      setOpen(false);
      trigger.focus();
    }
  });

  return root;
}

// ---------------------------------------------------------------------------
// modal + alert
// ---------------------------------------------------------------------------

export interface Dismissable {
  el: HTMLElement;
  body: HTMLElement;
  close(): void;
}

export interface ModalOptions {
  title: string;
  description?: string;
  okLabel?: string;
  cancelLabel?: string;
  /** Style the confirm button as destructive. */
  danger?: boolean;
  /** Omit to render a dialog with no confirm button. */
  onOk?(): void;
  onCancel?(): void;
}

/** A centred dialog. The caller appends `.el` to `document.body`. */
export function modal(options: ModalOptions, ...body: Child[]): Dismissable {
  const content = el('div', { class: 'z-modal__body' }, ...body);
  const overlay = el('div', { class: 'z-modal__overlay' });
  const panel = el('div', {
    class: 'z-modal',
    attrs: { role: 'dialog', 'aria-modal': 'true', 'aria-label': options.title },
  });
  const root = el('div', { class: 'z-modal__root' }, overlay, panel);

  let released: Array<() => void> = [];
  const close = (): void => {
    for (const release of released) {
      release();
    }
    released = [];
    root.remove();
  };
  const cancel = (): void => {
    close();
    options.onCancel?.();
  };

  const footer = el(
    'div',
    { class: 'z-modal__footer' },
    el(
      'button',
      { class: 'z-btn z-btn--secondary', type: 'button', onclick: cancel },
      options.cancelLabel ?? 'Cancel',
    ),
    options.onOk
      ? el(
          'button',
          {
            class: options.danger ? 'z-btn z-btn--danger' : 'z-btn',
            type: 'button',
            onclick: () => {
              close();
              options.onOk?.();
            },
          },
          options.okLabel ?? 'OK',
        )
      : null,
  );

  append(
    panel,
    el(
      'div',
      { class: 'z-modal__header' },
      el('h2', { class: 'z-modal__title' }, options.title),
      options.description ? el('p', { class: 'z-modal__description' }, options.description) : null,
    ),
    content,
    footer,
  );

  released.push(on(overlay, 'click', cancel));
  released.push(
    on(document, 'keydown', (event) => {
      if (event instanceof KeyboardEvent && event.key === 'Escape') {
        cancel();
      }
    }),
  );

  return { el: root, body: content, close };
}

export interface AlertOptions {
  title: string;
  description: string;
  okLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onOk(): void;
  onCancel?(): void;
}

/** The confirmation dialog every destructive action goes through. */
export function alert(options: AlertOptions): Dismissable {
  return modal({
    title: options.title,
    description: options.description,
    okLabel: options.okLabel ?? 'OK',
    cancelLabel: options.cancelLabel ?? 'Cancel',
    danger: options.danger !== false,
    onOk: options.onOk,
    ...(options.onCancel ? { onCancel: options.onCancel } : {}),
  });
}

// ---------------------------------------------------------------------------
// slideOver
// ---------------------------------------------------------------------------

export interface SlideOverOptions {
  title: string;
  description?: string;
  footer?: Child[];
  onClose?(): void;
}

/** A right-hand panel, 448px wide, sliding in over a translucent overlay. */
export function slideOver(options: SlideOverOptions, ...body: Child[]): Dismissable {
  const content = el('div', { class: 'z-slideover__body' }, ...body);
  const overlay = el('div', { class: 'z-slideover__overlay' });
  const panel = el('aside', {
    class: 'z-slideover',
    attrs: { role: 'dialog', 'aria-modal': 'true', 'aria-label': options.title },
  });
  const root = el('div', { class: 'z-slideover__root' }, overlay, panel);

  let released: Array<() => void> = [];
  const close = (): void => {
    for (const release of released) {
      release();
    }
    released = [];
    root.remove();
    options.onClose?.();
  };

  const closeButton = el(
    'button',
    { class: 'z-icon-btn', type: 'button', title: 'Close panel', onclick: close },
    icon('close'),
    srOnly('Close panel'),
  );

  append(
    panel,
    el(
      'header',
      { class: 'z-slideover__header' },
      el(
        'div',
        { class: 'z-slideover__heading' },
        el('h2', { class: 'z-slideover__title' }, options.title),
        closeButton,
      ),
      options.description ? el('p', { class: 'z-slideover__description' }, options.description) : null,
    ),
    content,
    options.footer ? el('div', { class: 'z-slideover__footer' }, ...options.footer) : null,
  );

  released.push(on(overlay, 'click', close));
  released.push(
    on(document, 'keydown', (event) => {
      if (event instanceof KeyboardEvent && event.key === 'Escape') {
        close();
      }
    }),
  );

  // Let the browser paint the off-screen position before transitioning in.
  requestAnimationFrame(() => {
    root.classList.add('is-open');
  });

  return { el: root, body: content, close };
}

// ---------------------------------------------------------------------------
// pagination
// ---------------------------------------------------------------------------

export interface PaginationOptions {
  /** Zero-based current page. */
  page: number;
  /** Zero-based index of the last page (`ceil(total / size) - 1`). */
  lastPage: number;
  onGo(page: number): void;
}

/** Classic paging: First, Previous, ±5 numbered pages, Next, Last. */
export function pagination(options: PaginationOptions): HTMLElement {
  const { page, lastPage } = options;
  const root = el('div', { class: 'z-pagination', attrs: { role: 'navigation', 'aria-label': 'Pagination' } });
  const button = (label: string, target: number, disabled: boolean, current = false): HTMLElement =>
    el(
      'button',
      {
        class: current ? 'z-pagination__btn is-current' : 'z-pagination__btn',
        type: 'button',
        disabled: disabled || current,
        onclick: () => {
          options.onGo(target);
        },
      },
      label,
    );

  root.appendChild(button('First', 0, page <= 0));
  root.appendChild(button('Previous', page - 1, page <= 0));
  // The numbered window is half-open — `i ∈ [page-5, page+5)` — matching the
  // interaction this replaces, so the strip never changes width mid-navigation.
  const from = Math.max(0, page - 5);
  const to = Math.min(lastPage, page + 4);
  for (let i = from; i <= to; i++) {
    root.appendChild(button(String(i + 1), i, false, i === page));
  }
  root.appendChild(button('Next', page + 1, page >= lastPage));
  root.appendChild(button('Last', lastPage, page >= lastPage));
  return root;
}

// ---------------------------------------------------------------------------
// spinner
// ---------------------------------------------------------------------------

/** The VS Code loader bar: a 2px animated pill pinned to the top of the view,
 *  optionally over a centred message with an animated ellipsis. */
export function spinner(message?: string): HTMLElement {
  return el(
    'div',
    { class: 'z-loader' },
    el('div', { class: 'z-loader__bar' }, el('div', { class: 'z-loader__bar__animation' })),
    message
      ? el('p', { class: 'z-loader__message' }, message, el('span', { class: 'z-loader__dots' }))
      : null,
  );
}

// ---------------------------------------------------------------------------
// tagPill
// ---------------------------------------------------------------------------

export interface TagPillOptions {
  value: string;
  /** Present in the configured taxonomy. Unknown values get the create button. */
  known: boolean;
  onRemove?(value: string): void;
  /** Offer "add this to your settings". Omit to hide the `+` affordance. */
  onCreate?(value: string): void;
  removeTitle?: string;
  createTitle?: string;
}

export function tagPill(options: TagPillOptions): HTMLElement {
  const classes = options.known
    ? 'z-tag article__tags__items__pill_exists'
    : 'z-tag z-tag--unknown article__tags__items__pill_notexists';
  return el(
    'div',
    { class: classes, title: options.value },
    el('span', { class: 'z-tag__value' }, options.value),
    options.onCreate
      ? el(
          'button',
          {
            class: 'z-tag__create',
            type: 'button',
            title: options.createTitle ?? `Add ${options.value} to your settings`,
            onclick: () => {
              options.onCreate?.(options.value);
            },
          },
          icon('add'),
          srOnly(`Add ${options.value} to your settings`),
        )
      : null,
    options.onRemove
      ? el(
          'button',
          {
            class: 'z-tag__delete tag__delete',
            type: 'button',
            title: options.removeTitle ?? `Remove ${options.value}`,
            onclick: () => {
              options.onRemove?.(options.value);
            },
          },
          icon('close'),
          srOnly(`Remove ${options.value}`),
        )
      : null,
  );
}

// ---------------------------------------------------------------------------
// validInfo
// ---------------------------------------------------------------------------

/** The green check / amber warning glyph in the SEO insights table.
 *  `undefined` means "reported, never validated" and renders a spacer. */
export function validInfo(isValid: boolean | undefined): HTMLElement {
  if (isValid === undefined) {
    return el('span', { class: 'z-valid z-valid--none' });
  }
  return el(
    'span',
    {
      class: isValid ? 'z-valid z-valid--ok' : 'z-valid z-valid--warn',
      title: isValid ? 'Within the recommended limit' : 'Over the recommended limit',
    },
    icon(isValid ? 'check' : 'warning'),
  );
}

// ---------------------------------------------------------------------------
// textField
// ---------------------------------------------------------------------------

export type FieldValidity = 'info' | 'warning' | 'error';

export interface TextFieldOptions {
  value: string;
  multiline?: boolean;
  rows?: number;
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  /** Character budget. `-1` (or omitted) disables the counter entirely. */
  limit?: number;
  /** Trailing debounce before `onChange` fires. Defaults to 300ms. */
  debounceMs?: number;
  ariaLabel?: string;
  onChange(value: string): void;
  /** Fired on Enter in a single-line field, before the debounce. */
  onSubmit?(value: string): void;
}

export interface TextFieldHandle {
  el: HTMLElement;
  input: HTMLInputElement | HTMLTextAreaElement;
  setValue(value: string): void;
  validity(): FieldValidity;
  focus(): void;
  dispose(): void;
}

/**
 * A text input or textarea carrying the three-state border (`info` normally,
 * `warning` over the limit, `error` when required and empty) and the
 * `Field limit reached x/y` counter.
 */
export function textField(options: TextFieldOptions): TextFieldHandle {
  const limit = options.limit ?? -1;
  const counter = el('div', { class: 'z-field__limit metadata_field__limit' });
  const input = options.multiline
    ? el('textarea', {
        class: 'z-field__input metadata_field__textarea',
        rows: options.rows ?? 4,
        placeholder: options.placeholder ?? '',
        disabled: options.disabled === true,
        value: options.value,
      })
    : el('input', {
        class: 'z-field__input metadata_field__input',
        type: 'text',
        placeholder: options.placeholder ?? '',
        disabled: options.disabled === true,
        value: options.value,
      });
  if (options.ariaLabel) {
    input.setAttribute('aria-label', options.ariaLabel);
  }
  const root = el('div', { class: 'z-field' }, input, counter);

  const validity = (): FieldValidity => {
    const length = input.value.length;
    if (options.required && length === 0) {
      return 'error';
    }
    if (limit > 0 && length > limit) {
      return 'warning';
    }
    return 'info';
  };

  const paint = (): void => {
    const state = validity();
    root.classList.toggle('is-error', state === 'error');
    root.classList.toggle('is-warning', state === 'warning');
    clear(counter);
    if (state === 'warning') {
      counter.appendChild(document.createTextNode(`Field limit reached ${input.value.length}/${limit}`));
    }
  };
  paint();

  const emit = debounce((value: string) => {
    options.onChange(value);
  }, options.debounceMs ?? 300);

  const released = [
    on(input, 'input', () => {
      paint();
      emit(input.value);
    }),
    on(input, 'keydown', (event) => {
      if (!options.multiline && event instanceof KeyboardEvent && event.key === 'Enter') {
        event.preventDefault();
        emit.cancel();
        if (options.onSubmit) {
          options.onSubmit(input.value);
        } else {
          options.onChange(input.value);
        }
      }
    }),
    on(input, 'blur', () => {
      emit.flush();
    }),
  ];

  return {
    el: root,
    input,
    validity,
    setValue(value: string) {
      input.value = value;
      paint();
    },
    focus() {
      input.focus();
    },
    dispose() {
      emit.cancel();
      for (const release of released) {
        release();
      }
    },
  };
}

// ---------------------------------------------------------------------------
// toggle
// ---------------------------------------------------------------------------

export interface ToggleOptions {
  checked: boolean;
  /** Text rendered next to the switch. */
  label?: string;
  disabled?: boolean;
  onChange(checked: boolean): void;
}

export interface ToggleHandle {
  el: HTMLElement;
  input: HTMLInputElement;
  setChecked(checked: boolean): void;
}

/** The 50×24 pill switch, unchanged from Front Matter's `.field__toggle`. */
export function toggle(options: ToggleOptions): ToggleHandle {
  const input = el('input', {
    type: 'checkbox',
    checked: options.checked,
    disabled: options.disabled === true,
  });
  const control = el(
    'label',
    { class: 'z-toggle field__toggle' },
    input,
    el('span', { class: 'z-toggle__slider field__toggle__slider' }),
  );
  input.addEventListener('change', () => {
    options.onChange(input.checked);
  });
  const root = options.label
    ? el('div', { class: 'z-toggle__row' }, control, el('span', { class: 'z-toggle__label' }, options.label))
    : control;
  return {
    el: root,
    input,
    setChecked(checked: boolean) {
      input.checked = checked;
    },
  };
}

// ---------------------------------------------------------------------------
// statusPill
// ---------------------------------------------------------------------------

/**
 * The five honest states a cell can be in.
 *
 * `unknown` is the one that is not an answer — nobody asked, there was no
 * credential, the tab was opened without one. It renders differently from
 * `neutral` on purpose: a grey cell that looks like every other grey cell
 * quietly claims the question was answered "no".
 */
export type StatusVariant = 'ok' | 'warn' | 'danger' | 'neutral' | 'unknown';

export interface StatusPillOptions {
  variant: StatusVariant;
  text: string;
  /** Tooltip — usually the raw value the pill is summarising. */
  title?: string;
}

export function statusPill(options: StatusPillOptions): HTMLElement {
  return el(
    'span',
    {
      class: `z-status z-status--${options.variant}`,
      title: options.title ?? '',
    },
    options.text,
  );
}

// ---------------------------------------------------------------------------
// dataTable
// ---------------------------------------------------------------------------

export interface DataColumn {
  label: string;
  /** Right-aligned and `font-variant-numeric: tabular-nums`. */
  numeric?: boolean;
  title?: string;
}

export interface DataTableOptions {
  /** A bare string is a left-aligned column with that label. */
  columns: ReadonlyArray<string | DataColumn>;
  /** One entry per row; each cell's contents are wrapped in a `<td>`. */
  rows: ReadonlyArray<ReadonlyArray<Child>>;
  /** Zero-based indices of numeric columns, merged with any `numeric` flag. */
  numeric?: readonly number[];
  /** Extra class on the `<table>`, e.g. `z-fleet__table`. */
  className?: string;
  /** Drawn instead of the table when `rows` is empty. */
  empty?: string;
  /** Accessible name for the table. */
  label?: string;
}

function asColumn(column: string | DataColumn): DataColumn {
  return typeof column === 'string' ? { label: column } : column;
}

/**
 * A table inside its own horizontal scroll box.
 *
 * The `.z-table__scroll` wrapper is the point: an operator table is wide —
 * lane, harness, triggers, switch, run, cost — and a page body that scrolls
 * sideways takes the tab bar and the toolbar with it. Wide content scrolls in
 * its own box or it does not scroll at all.
 */
export function dataTable(options: DataTableOptions): HTMLElement {
  const columns = options.columns.map(asColumn);
  const numeric = new Set<number>(options.numeric ?? []);
  columns.forEach((column, index) => {
    if (column.numeric === true) {
      numeric.add(index);
    }
  });

  if (options.rows.length === 0 && options.empty !== undefined) {
    return el('p', { class: 'z-lane__empty' }, options.empty);
  }

  const head = el(
    'thead',
    {},
    el(
      'tr',
      {},
      ...columns.map((column, index) =>
        el(
          'th',
          {
            ...(numeric.has(index) ? { class: 'z-table__num' } : {}),
            ...(column.title === undefined ? {} : { title: column.title }),
            attrs: { scope: 'col' },
          },
          column.label,
        ),
      ),
    ),
  );

  const body = el('tbody', {});
  for (const row of options.rows) {
    body.appendChild(
      el(
        'tr',
        {},
        ...row.map((cell, index) =>
          el('td', numeric.has(index) ? { class: 'z-table__num' } : {}, cell),
        ),
      ),
    );
  }

  return el(
    'div',
    { class: 'z-table__scroll' },
    el(
      'table',
      {
        class: options.className ? `z-table ${options.className}` : 'z-table',
        ...(options.label === undefined ? {} : { attrs: { 'aria-label': options.label } }),
      },
      head,
      body,
    ),
  );
}

// ---------------------------------------------------------------------------
// emptyState
// ---------------------------------------------------------------------------

export interface EmptyStateOptions {
  /** Codicon name. */
  icon: string;
  message: string;
  /** The second line: what would make this screen have something to show. */
  hint?: string;
  /** Buttons offering the thing the hint just named. */
  actions?: Child[];
}

/**
 * "There is nothing here, and here is why" — never a blank panel.
 *
 * The hint is the load-bearing half. `.cms/` absence, an unset switch and an
 * empty draft queue are all normal states (decision D9), and a screen that
 * renders nothing for them is indistinguishable from one that failed.
 */
export function emptyState(options: EmptyStateOptions): HTMLElement {
  return el(
    'div',
    { class: 'z-emptystate' },
    icon(options.icon),
    el('p', {}, options.message),
    options.hint === undefined ? null : el('p', { class: 'z-muted' }, options.hint),
    options.actions === undefined || options.actions.length === 0
      ? null
      : el('div', { class: 'z-review__actions z-emptystate__actions' }, ...options.actions),
  );
}

// ---------------------------------------------------------------------------
// blockerNote
// ---------------------------------------------------------------------------

/**
 * `Publish disabled: a; b.` — the gate's own summary, in a UI frame.
 *
 * The order is the host's, verbatim: `evaluateGates()` returns blockers
 * cheapest-and-most-fundamental first, so the sentence already leads with what
 * to fix first. Re-sorting or de-duplicating here would make this screen and
 * the confirmation modal disagree about the same draft, draft queue or lane.
 */
export function blockerNote(
  verb: string,
  blockers: readonly BlockerView[],
  className = 'z-blockers',
): HTMLElement | null {
  if (blockers.length === 0) {
    return null;
  }
  return el(
    'p',
    { class: className },
    `${verb} disabled: ${blockers.map((blocker) => blocker.message).join('; ')}.`,
  );
}

// ---------------------------------------------------------------------------
// gatedButton
// ---------------------------------------------------------------------------

export interface GatedButtonOptions {
  label: string;
  /** The intent. The closed `CommandId` union is the host's allow-list. */
  id: CommandId;
  /** The target — which lane, which draft, which folder. Never an override. */
  args?: unknown;
  /** The host's advisory blockers. Non-empty disables the button. */
  blockers: readonly BlockerView[];
  /** How the blocker sentence names the action. Defaults to `label`. */
  verb?: string;
  title?: string;
  secondary?: boolean;
  danger?: boolean;
}

/**
 * A button that is disabled when the host says the action is blocked, and the
 * blocker sentence underneath it.
 *
 * The disabled state is a courtesy to the person, not a control (decision D5).
 * The host re-reads state from disk and re-runs its gate inside the same
 * function the command palette calls; nothing travels from here but the intent
 * and its target.
 */
export function gatedButton(options: GatedButtonOptions): HTMLElement {
  const blocked = options.blockers.length > 0;
  const reason = options.blockers.map((blocker) => blocker.message).join('; ');
  const button = el(
    'button',
    {
      class: options.danger === true
        ? 'z-btn z-btn--danger'
        : options.secondary === true
          ? 'z-btn z-btn--secondary'
          : 'z-btn',
      type: 'button',
      disabled: blocked,
      title: blocked ? reason : (options.title ?? options.label),
      onclick: () => {
        // An intent and a target. See the file header, and decision D5.
        getMessenger().command(options.id, options.args);
      },
    },
    options.label,
  );
  const note = blockerNote(options.verb ?? options.label, options.blockers);
  if (note === null) {
    return button;
  }
  return el('div', { class: 'z-gated' }, button, note);
}

// ---------------------------------------------------------------------------
// keyValueList
// ---------------------------------------------------------------------------

export interface KeyValueRow {
  key: string;
  value: Child;
  title?: string;
}

/**
 * Provenance, as a definition list.
 *
 * Every operator screen has to say where its numbers came from — which
 * manifest, read at what time, from which commit, by which credential. A `<dl>`
 * says "these labels name those values" to a screen reader, which a two-column
 * table of `<div>`s does not.
 */
export function keyValueList(rows: readonly KeyValueRow[], className?: string): HTMLElement {
  const list = el('dl', { class: className ? `z-kv ${className}` : 'z-kv' });
  for (const row of rows) {
    list.appendChild(el('dt', { class: 'z-kv__key', title: row.title ?? '' }, row.key));
    list.appendChild(el('dd', { class: 'z-kv__value' }, row.value));
  }
  return list;
}

// ---------------------------------------------------------------------------
// diffView
// ---------------------------------------------------------------------------

/**
 * A unified diff, coloured one line at a time.
 *
 * The line's first character picks its class and **nothing else** — the text
 * chooses a class name, never a structure, and every character of it goes in
 * through `createTextNode`. That is what makes it safe to render a diff an
 * agent proposed or a scaffolder generated.
 *
 * The class names are the agent transcript's (`.z-agent__diff` with `.is-add`,
 * `.is-del`, `.is-meta`), which `media/base.css` styles: the approval card and
 * a lane-scaffold preview show the same kind of thing and must look identical.
 * `src/webview/agent/main.ts`'s `diffPane()` is its twin — if one changes, the
 * other changes with it.
 */
export function diffView(text: string): HTMLElement {
  const pre = el('pre', { class: 'z-agent__diff' });
  for (const line of text.split('\n')) {
    const first = line.charAt(0);
    const className =
      first === '+' ? 'is-add' : first === '-' ? 'is-del' : first === '#' ? 'is-meta' : '';
    pre.appendChild(className === '' ? el('span', {}, line) : el('span', { class: className }, line));
  }
  return pre;
}
