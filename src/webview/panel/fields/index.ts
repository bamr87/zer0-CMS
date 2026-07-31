/**
 * The field registry, the dispatcher, and the chrome every field control wears.
 *
 * `createFieldWidget()` is the one entry point the panel calls. It looks the
 * field's type up in `FIELD_FACTORIES` — a complete `Record<FieldType,
 * FieldFactory>` over all eighteen types — and wraps the result in an error
 * boundary. Two properties are load-bearing:
 *
 *   1. **A type with no factory renders nothing and never throws.** Front
 *      Matter's config files are hand-written JSON; a typo in `type` must cost
 *      the author one missing control, not the whole panel.
 *   2. **A field that throws while building takes only itself down.** Every
 *      widget is built inside `boundary()`, which catches, logs, and swaps in
 *      the `Failed viewing the field` row with a Retry button that re-runs the
 *      factory. One broken field cannot blank the metadata section.
 *
 * The shared chrome — title row, required asterisk, the mutually-exclusive
 * required/description message, the loading overlay and the error row — lives
 * in `fieldShell()` rather than in each widget, so the eighteen controls differ
 * only in the control itself.
 *
 * Sibling modules (`inputs`, `pickers`, `media`, `groups`) import their helpers
 * from here and this module imports their factories, which is a deliberate
 * cycle: every reference in both directions is a hoisted `function` used inside
 * a call, never a value read during module evaluation.
 *
 * Why this file re-states a little of `core/content/fields.ts`: that module
 * imports `core/content/placeholders.ts`, which imports `node:child_process`
 * and `node:fs/promises`. The panel is bundled for the browser, so the two
 * pure helpers it needs (`labelOf` and the `<failed to process>` sentinel) are
 * restated here and kept byte-identical by review rather than by import.
 */

import { humanize } from '../../../core/shared/text';
import type { Field, FieldType } from '../../../core/shared/types';
import { clear, el, icon } from '../../shared/dom';
import type {
  FieldContext,
  FieldFactory,
  FieldWidget,
  FmValue,
  PanelState,
} from '../../shared/protocol';
import { booleanField, datetimeField, draftField, listField, numberField, slugField, stringField } from './inputs';
import {
  categoriesField,
  choiceField,
  contentRelationshipField,
  tagsField,
  taxonomyField,
} from './pickers';
import {
  dividerField,
  fieldCollectionField,
  fieldIsVisible,
  fieldsGroupField,
  headingField,
} from './groups';
import { fileField, previewImageField } from './media';

// ---------------------------------------------------------------------------
// Constants shared with the core
// ---------------------------------------------------------------------------

/**
 * `core/content/placeholders.ts#FAULTY_PLACEHOLDER`. A value equal to this is
 * a placeholder that failed to resolve, and every control treats it as empty
 * rather than as text the author typed.
 */
export const FAULTY_PLACEHOLDER = '<failed to process>';

/** Front Matter's SEO budgets, used when the insights table cannot supply one. */
export const DEFAULT_TITLE_LIMIT = 60;
export const DEFAULT_DESCRIPTION_LIMIT = 160;

/**
 * The codicon drawn to the left of each field label. Types with no entry
 * (`fields`, `fieldCollection`, `divider`, `heading`) render a bare label, as
 * Front Matter did.
 */
export const FIELD_ICONS: Partial<Record<FieldType, string>> = {
  string: 'edit',
  number: 'symbol-number',
  boolean: 'symbol-boolean',
  draft: 'symbol-boolean',
  datetime: 'clock',
  image: 'file-media',
  file: 'file',
  choice: 'check',
  tags: 'tag',
  categories: 'list-unordered',
  taxonomy: 'list-unordered',
  list: 'list-ordered',
  slug: 'link',
  contentRelationship: 'references',
};

// ---------------------------------------------------------------------------
// Value helpers
// ---------------------------------------------------------------------------

/** The label a control shows: the configured `title`, else a readable `name`. */
export function labelOf(field: Field): string {
  const title = field.title;
  if (title !== undefined && title.trim() !== '') {
    return title;
  }
  return humanize(field.name) || field.name;
}

/**
 * Does this value count as nothing? `false` and `0` are values; a missing key,
 * a blank string, an empty list or object, and the faulty-placeholder sentinel
 * are not. Mirrors `core/content/fields.ts#isEmpty` for the non-presentation
 * types (the presentation types never ask).
 */
export function isValueEmpty(value: FmValue | undefined): boolean {
  if (value === undefined || value === null) {
    return true;
  }
  if (typeof value === 'string') {
    return value.trim() === '' || value === FAULTY_PLACEHOLDER;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  if (typeof value === 'object') {
    return Object.keys(value).length === 0;
  }
  return false;
}

/** A scalar rendered for a text control. Structured values render as blank. */
export function toText(value: FmValue | undefined): string {
  if (value === undefined || value === null) {
    return '';
  }
  if (typeof value === 'string') {
    return value === FAULTY_PLACEHOLDER ? '' : value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '';
}

/**
 * A value normalised to a list of strings. A lone string becomes a one-item
 * list, which is what `singleValueAsString` writes and what every multi-select
 * control has to read back.
 */
export function toStringList(value: FmValue | undefined): string[] {
  if (value === undefined || value === null) {
    return [];
  }
  if (typeof value === 'string') {
    return value.trim() === '' || value === FAULTY_PLACEHOLDER ? [] : [value];
  }
  if (Array.isArray(value)) {
    const out: string[] = [];
    for (const item of value) {
      if (typeof item === 'string' && item.trim() !== '' && item !== FAULTY_PLACEHOLDER) {
        out.push(item);
      } else if (typeof item === 'number' || typeof item === 'boolean') {
        out.push(String(item));
      }
    }
    return out;
  }
  return [];
}

/**
 * `field.singleValueAsString` writes a lone selection as a bare string instead
 * of a one-item list. Both shapes read back identically through
 * `toStringList`, so this is purely about what goes on the wire.
 */
export function packList(field: Field, values: string[]): FmValue {
  if (field.singleValueAsString === true && values.length === 1) {
    return values[0] ?? '';
  }
  return values;
}

/**
 * The character budget shown under a text control, or `-1` for "no limit".
 *
 * Only the two SEO fields have one. `SeoState` carries no explicit lengths, so
 * the budget is read out of the matching insights row's `recommendation`
 * (`"60 chars"`, produced by `core/content/seo.ts`) and falls back to Front
 * Matter's 60/160 defaults when SEO reported no row for the field.
 */
export function limitForField(field: Field, state: PanelState): number {
  const seo = state.seo;
  if (seo === null || !state.settings.seoEnabled) {
    return -1;
  }
  const isTitle = field.name === seo.titleField;
  const isDescription = field.name === seo.descriptionField;
  if (!isTitle && !isDescription) {
    return -1;
  }
  const label = labelOf(field);
  for (const row of seo.rows) {
    const recommendation = row.recommendation;
    if (row.label !== label || recommendation === undefined || !recommendation.endsWith('chars')) {
      continue;
    }
    const parsed = Number.parseInt(recommendation, 10);
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return isTitle ? DEFAULT_TITLE_LIMIT : DEFAULT_DESCRIPTION_LIMIT;
}

/** The message an unknown thrown value carries, without ever stringifying `{}`. */
export function errorText(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === 'string' && error !== '') {
    return error;
  }
  return 'Unknown error';
}

// ---------------------------------------------------------------------------
// Shared chrome
// ---------------------------------------------------------------------------

export interface FieldShellOptions {
  /** Override the computed label. */
  label?: string;
  /** Codicon name, or `null` for no icon. Defaults to `FIELD_ICONS[type]`. */
  icon?: string | null;
  /** Lighter-weight suffix after the label, e.g. `" (Max.: 3)"`. */
  labelSuffix?: string;
  /** Centre the label — the `fields` / `fieldCollection` group boxes. */
  centred?: boolean;
  /** Extra class on the root, alongside `metadata_field`. */
  rootClass?: string;
  /** Skip the title row entirely (`divider`, `heading`). */
  noTitle?: boolean;
  /** Keep the label's original case in the required message, as `list` does. */
  rawMessageLabel?: boolean;
  /** Replaces the error row's default Retry behaviour (clear the error). */
  onRetry?(): void;
}

export interface FieldShell {
  /** The `.metadata_field` root. */
  el: HTMLElement;
  /** Append the control here. */
  control: HTMLElement;
  /** The right-hand slot of the title row. Front Matter filled it with custom
   *  script buttons and a Copilot suggestion button; PLAN §3.1 drops both, so
   *  it stays empty and exists to keep the title row's layout identical. */
  actions: HTMLElement;
  /** Toggle `.required` and the required message. */
  setEmpty(empty: boolean): void;
  /** Toggle `.is-warning` — over the character budget. */
  setWarning(on: boolean): void;
  setLoading(message: string | null): void;
  setError(message: string | null): void;
  dispose(): void;
}

/**
 * Build the chrome around one control: the title row with its icon, label,
 * required asterisk and action slot; the control host; the mutually-exclusive
 * required/description message; the loading overlay; and the error row.
 */
export function fieldShell(ctx: FieldContext, options: FieldShellOptions = {}): FieldShell {
  const field = ctx.field;
  const label = options.label ?? labelOf(field);
  const required = field.required === true;
  const iconName = options.icon === undefined ? FIELD_ICONS[field.type] : options.icon;

  const root = el('div', {
    class: options.rootClass ? `metadata_field ${options.rootClass}` : 'metadata_field',
  });
  const actions = el('div', { class: 'field__title__actions', style: 'display:flex;gap:0.75rem' });
  const control = el('div', { class: 'metadata_field__control' });
  const messageHost = el('div', { class: 'metadata_field__message' });
  const errorHost = el('div', { class: 'metadata_field__error_host' });
  const overlayHost = el('div', { class: 'metadata_field__overlay_host' });

  if (options.noTitle !== true) {
    root.appendChild(
      el(
        'div',
        { class: 'field__title' },
        el(
          'label',
          {
            class: options.centred
              ? 'metadata_field__label metadata_field__label_parent'
              : 'metadata_field__label',
          },
          iconName ? icon(iconName) : null,
          el('span', { style: 'line-height:16px' }, label),
          options.labelSuffix
            ? el('span', { style: 'font-weight:lighter' }, options.labelSuffix)
            : null,
          required ? el('span', { class: 'metadata_field__required__asterix' }, '*') : null,
        ),
        actions,
      ),
    );
  }
  root.appendChild(control);
  root.appendChild(messageHost);
  root.appendChild(errorHost);
  root.appendChild(overlayHost);

  const messageLabel = options.rawMessageLabel === true ? label : label.toLowerCase();

  const paintMessage = (empty: boolean): void => {
    clear(messageHost);
    if (required && empty) {
      messageHost.appendChild(
        el(
          'div',
          { class: 'metadata_field__required__message' },
          `The ${messageLabel} field is required`,
        ),
      );
      return;
    }
    const description = field.description;
    if (description !== undefined && description.trim() !== '') {
      messageHost.appendChild(el('div', { class: 'metadata_field__description' }, description));
    }
  };

  const setEmpty = (empty: boolean): void => {
    root.classList.toggle('required', required && empty);
    paintMessage(empty);
  };
  setEmpty(isValueEmpty(ctx.value));

  const setError = (message: string | null): void => {
    clear(errorHost);
    if (message === null) {
      return;
    }
    errorHost.appendChild(
      el(
        'div',
        { class: 'metadata_field__error' },
        el('span', {}, message),
        el(
          'button',
          {
            class: 'z-btn z-btn--secondary',
            type: 'button',
            onclick: () => {
              if (options.onRetry) {
                options.onRetry();
              } else {
                setError(null);
              }
            },
          },
          'Retry',
        ),
      ),
    );
  };

  return {
    el: root,
    control,
    actions,
    setEmpty,
    setWarning(on_: boolean) {
      root.classList.toggle('is-warning', on_);
    },
    setLoading(message: string | null) {
      clear(overlayHost);
      if (message !== null) {
        overlayHost.appendChild(el('div', { class: 'metadata_field__loading' }, message));
      }
    },
    setError,
    dispose() {
      clear(overlayHost);
      clear(errorHost);
    },
  };
}

// ---------------------------------------------------------------------------
// Widget helpers
// ---------------------------------------------------------------------------

const noop = (): void => undefined;

/**
 * A widget that renders nothing and does nothing. Used by the presentation
 * types, whose node carries no value, and by a `fieldCollection` that resolved
 * to nothing. The default node is `display:none` so it cannot open a gap in the
 * `.metadata_fields` stack.
 */
export function emptyWidget(node?: HTMLElement): FieldWidget {
  return {
    el: node ?? el('div', { class: 'metadata_field__void', style: 'display:none' }),
    setValue: noop,
    setLoading: noop,
    setError: noop,
    focus: noop,
    dispose: noop,
  };
}

/**
 * Compose a widget from a shell: the four contract methods delegate to the
 * shell, and `setValue`/`focus` to the control the factory supplies.
 */
export function shellWidget(
  shell: FieldShell,
  parts: {
    setValue(value: FmValue | undefined): void;
    focus?(): void;
    dispose?(): void;
  },
): FieldWidget {
  return {
    el: shell.el,
    setValue: parts.setValue,
    setLoading(message) {
      shell.setLoading(message);
    },
    setError(message) {
      shell.setError(message);
    },
    focus: parts.focus ?? noop,
    dispose() {
      parts.dispose?.();
      shell.dispose();
    },
  };
}

// ---------------------------------------------------------------------------
// Registry and dispatcher
// ---------------------------------------------------------------------------

/**
 * Every field type, mapped to the factory that builds its control. Complete
 * over `FieldType` by construction: adding a type to the core enum without a
 * factory here is a compile error, which is the point.
 */
export const FIELD_FACTORIES: Record<FieldType, FieldFactory> = {
  string: stringField,
  number: numberField,
  boolean: booleanField,
  datetime: datetimeField,
  image: previewImageField,
  file: fileField,
  choice: choiceField,
  tags: tagsField,
  categories: categoriesField,
  taxonomy: taxonomyField,
  draft: draftField,
  list: listField,
  slug: slugField,
  fields: fieldsGroupField,
  fieldCollection: fieldCollectionField,
  divider: dividerField,
  heading: headingField,
  contentRelationship: contentRelationshipField,
};

/** Is there a control for this type? Takes a `string` on purpose: the caller
 *  is usually holding a value read out of a hand-written config file. */
export function isFieldTypeSupported(type: string): boolean {
  return Object.prototype.hasOwnProperty.call(FIELD_FACTORIES, type);
}

/**
 * The per-field error boundary. Builds the widget, and on a throw renders the
 * `Failed viewing the field` row with a Retry that re-runs the factory against
 * the most recent value the panel pushed in.
 */
function boundary(ctx: FieldContext, factory: FieldFactory): FieldWidget {
  const host = el('div', { class: 'metadata_field__boundary' });
  const label = labelOf(ctx.field);
  let inner: FieldWidget | null = null;
  let latest: FmValue | undefined = ctx.value;
  let disposed = false;

  const mount = (): void => {
    inner?.dispose();
    inner = null;
    clear(host);
    if (disposed) {
      return;
    }
    try {
      const widget = factory({ ...ctx, value: latest });
      inner = widget;
      host.appendChild(widget.el);
    } catch (error) {
      ctx.msg.log('error', `Field "${label}" failed to render: ${errorText(error)}`);
      host.appendChild(
        el(
          'div',
          { class: 'metadata_field' },
          el(
            'div',
            { class: 'field__title' },
            el('label', { class: 'metadata_field__label' }, el('span', {}, label)),
          ),
          el(
            'div',
            { class: 'metadata_field__error' },
            el('span', {}, 'Failed viewing the field'),
            el(
              'button',
              { class: 'z-btn z-btn--secondary', type: 'button', onclick: mount },
              'Retry',
            ),
          ),
        ),
      );
    }
  };
  mount();

  /** Never let a delegated call escape: a widget that throws on `setValue`
   *  would otherwise take the whole snapshot render down with it. */
  const guard = (what: string, run: () => void): void => {
    try {
      run();
    } catch (error) {
      ctx.msg.log('error', `Field "${label}" failed during ${what}: ${errorText(error)}`);
    }
  };

  return {
    el: host,
    setValue(value) {
      latest = value;
      const widget = inner;
      if (widget) {
        guard('setValue', () => {
          widget.setValue(value);
        });
      }
    },
    setLoading(message) {
      const widget = inner;
      if (widget) {
        guard('setLoading', () => {
          widget.setLoading(message);
        });
      }
    },
    setError(message) {
      const widget = inner;
      if (widget) {
        guard('setError', () => {
          widget.setError(message);
        });
      }
    },
    focus() {
      const widget = inner;
      if (widget) {
        guard('focus', () => {
          widget.focus();
        });
      }
    },
    dispose() {
      disposed = true;
      const widget = inner;
      inner = null;
      if (widget) {
        guard('dispose', () => {
          widget.dispose();
        });
      }
      clear(host);
    },
  };
}

/**
 * Build the control for one field. This is the function the panel calls, and
 * the only export of this module it needs.
 *
 * `null` means "render nothing", and covers exactly three cases: a `hidden`
 * field, a `when` clause that is false, and a type with no factory. None of the
 * three throws, and the third is logged. Everything else is built inside the
 * error boundary above, so a field that throws costs one control, not the page.
 *
 * The `when` clause is evaluated here only for top-level fields (`parents` is
 * empty): a nested field is evaluated by its group, against the group's own
 * sub-object, which is the only place that object exists.
 */
export function createFieldWidget(ctx: FieldContext): FieldWidget | null {
  if (ctx.field.hidden === true) {
    return null;
  }
  if (
    ctx.parents.length === 0 &&
    !fieldIsVisible(ctx.field, ctx.state.metadata ?? {}, ctx.state.fields)
  ) {
    return null;
  }
  const factory: FieldFactory | undefined = FIELD_FACTORIES[ctx.field.type];
  if (factory === undefined) {
    ctx.msg.log(
      'warn',
      `Unknown field type: ${String(ctx.field.type)} (field "${ctx.field.name}")`,
    );
    return null;
  }
  return boundary(ctx, factory);
}

/** Alias for `createFieldWidget`, for callers that read better without "Widget". */
export const createField = createFieldWidget;
