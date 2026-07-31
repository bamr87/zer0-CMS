/**
 * The seven scalar controls: `string`, `number`, `boolean`, `draft`,
 * `datetime`, `slug` and `list`.
 *
 * Each is a `FieldFactory` — `(ctx) => FieldWidget` — and each wears the shared
 * chrome from `./index`. Three behaviours are reproduced from Front Matter
 * exactly because authors depend on them:
 *
 *   • **The three-state input border.** `info` normally, `warning` over the
 *     character budget, `error` when the field is required and empty. The
 *     kernel's `textField()` already paints it; these factories only mirror the
 *     state onto the `.metadata_field` wrapper so the required message and the
 *     `Field limit reached x/y` counter agree with the border.
 *   • **The slug refresh button changes meaning.** When the host's generated
 *     slug differs from what is in the file, the button turns primary-coloured
 *     and its title becomes "Update available"; otherwise it is "Generate slug".
 *   • **The list editor is modal in miniature.** Add / Update / Cancel with an
 *     editing index, Enter submits, and every row carries hover-revealed edit
 *     and delete affordances.
 *
 * Dates go through `core/shared/dates.ts`, which is dependency-free and DOM-safe,
 * so the panel and the host format the same instant the same way. The date
 * control itself is a native `<input type="date">` / `datetime-local` rather
 * than a calendar widget: it is the only zero-dependency picker available, and
 * it inherits the workbench's locale for free.
 */

import { formatDate, isValidDate, parseDate } from '../../../core/shared/dates';
import { debounce, el, icon, on, srOnly } from '../../shared/dom';
import { textField, toggle } from '../../shared/components';
import type { FieldFactory, FmValue } from '../../shared/protocol';
import {
  errorText,
  fieldShell,
  labelOf,
  limitForField,
  shellWidget,
  toStringList,
  toText,
} from './index';
import { choiceField } from './pickers';

// ---------------------------------------------------------------------------
// string
// ---------------------------------------------------------------------------

/**
 * A single-line input when `field.single`, a four-row textarea otherwise —
 * Front Matter's default is the textarea, on the grounds that most string
 * fields in a CMS hold a sentence.
 */
export const stringField: FieldFactory = (ctx) => {
  const shell = fieldShell(ctx);
  const limit = limitForField(ctx.field, ctx.state);
  const handle = textField({
    value: toText(ctx.value),
    multiline: ctx.field.single !== true,
    rows: 4,
    required: ctx.field.required === true,
    limit,
    ariaLabel: labelOf(ctx.field),
    onChange: (value) => {
      ctx.onChange(value);
    },
  });
  shell.control.appendChild(handle.el);

  const sync = (): void => {
    shell.setEmpty(handle.input.value.trim() === '');
    shell.setWarning(handle.validity() === 'warning');
  };
  sync();

  const released = [on(handle.input, 'input', sync)];

  return shellWidget(shell, {
    setValue(value) {
      handle.setValue(toText(value));
      sync();
    },
    focus() {
      handle.focus();
    },
    dispose() {
      for (const release of released) {
        release();
      }
      handle.dispose();
    },
  });
};

// ---------------------------------------------------------------------------
// number
// ---------------------------------------------------------------------------

/**
 * `<input type="number">` with `min`/`max`/`step` from `numberOptions`. `step`
 * defaults to `0.1` for a decimal field and `1` otherwise, which is what makes
 * the spinner arrows produce values the field can actually hold.
 */
export const numberField: FieldFactory = (ctx) => {
  const shell = fieldShell(ctx);
  const options = ctx.field.numberOptions ?? {};
  const decimal = options.isDecimal === true;
  const input = el('input', {
    class: 'metadata_field__number',
    type: 'number',
    step: String(options.step ?? (decimal ? 0.1 : 1)),
  });
  if (options.min !== undefined) {
    input.min = String(options.min);
  }
  if (options.max !== undefined) {
    input.max = String(options.max);
  }
  input.setAttribute('aria-label', labelOf(ctx.field));
  shell.control.appendChild(input);

  const read = (): FmValue => {
    const raw = input.value.trim();
    if (raw === '') {
      return null;
    }
    const parsed = decimal ? Number.parseFloat(raw) : Number.parseInt(raw, 10);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const write = (value: FmValue | undefined): void => {
    input.value = typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
    // Front Matter marks a number field required only when it holds no number
    // at all: `0` is a value, and an author who typed it should not be nagged.
    shell.setEmpty(read() === null);
  };
  write(ctx.value);

  const emit = debounce(() => {
    ctx.onChange(read());
  }, 300);
  const released = [
    on(input, 'input', () => {
      shell.setEmpty(read() === null);
      emit();
    }),
    on(input, 'blur', () => {
      emit.flush();
    }),
  ];

  return shellWidget(shell, {
    setValue: write,
    focus() {
      input.focus();
    },
    dispose() {
      emit.cancel();
      for (const release of released) {
        release();
      }
    },
  });
};

// ---------------------------------------------------------------------------
// boolean
// ---------------------------------------------------------------------------

/** The 50×24 pill switch. Required only when the value is absent, never when
 *  it is `false` — `false` is an answer. */
export const booleanField: FieldFactory = (ctx) => {
  const shell = fieldShell(ctx);
  const handle = toggle({
    checked: ctx.value === true,
    onChange: (checked) => {
      shell.setEmpty(false);
      ctx.onChange(checked);
    },
  });
  shell.control.appendChild(handle.el);
  shell.setEmpty(ctx.value === undefined || ctx.value === null);

  return shellWidget(shell, {
    setValue(value) {
      handle.setChecked(value === true);
      shell.setEmpty(value === undefined || value === null);
    },
    focus() {
      handle.input.focus();
    },
  });
};

// ---------------------------------------------------------------------------
// draft
// ---------------------------------------------------------------------------

/**
 * `draft` is a boolean toggle or a single-select choice, depending on how the
 * project models "not published yet".
 *
 * Front Matter read `settings.draftField.type`. `PanelState` does not carry the
 * draft-field configuration, so the shape is derived from the field itself: a
 * `draft` field that declares `choices` is a choice field, everything else is a
 * toggle. A host that configures `draftField.type = "choice"` therefore has to
 * put the choices on the field it sends — which it has to do anyway for the
 * control to have anything to offer.
 */
export const draftField: FieldFactory = (ctx) => {
  const choices = ctx.field.choices;
  if (choices !== undefined && choices.length > 0) {
    return choiceField(ctx);
  }
  return booleanField(ctx);
};

// ---------------------------------------------------------------------------
// datetime
// ---------------------------------------------------------------------------

/** Front Matter's rule: show a time component when the pattern asks for one. */
function patternHasTime(pattern: string): boolean {
  return pattern === '' || /[hmsabk]/.test(pattern);
}

export const datetimeField: FieldFactory = (ctx) => {
  const shell = fieldShell(ctx);
  const pattern = ctx.field.dateFormat ?? ctx.state.dateFormat ?? 'MM/dd/yyyy HH:mm';
  const timezone = ctx.state.timezone;
  const withTime = patternHasTime(pattern);
  const controlPattern = withTime ? "yyyy-MM-dd'T'HH:mm" : 'yyyy-MM-dd';

  const input = el('input', { type: withTime ? 'datetime-local' : 'date' });
  input.setAttribute('aria-label', labelOf(ctx.field));
  const now = el('button', { class: 'z-btn z-btn--secondary', type: 'button' }, 'now');
  shell.control.appendChild(el('div', { class: 'metadata_field__datetime' }, input, now));

  const write = (value: FmValue | undefined): void => {
    const date = parseDate(value, pattern, timezone);
    input.value = date === null ? '' : formatDate(date, controlPattern, timezone);
    shell.setEmpty(date === null);
  };
  write(ctx.value);

  /** Emit in the configured pattern, or ISO-8601 when there is no pattern. */
  const emit = (date: Date | null): void => {
    if (date === null) {
      shell.setEmpty(true);
      ctx.onChange(null);
      return;
    }
    shell.setEmpty(false);
    ctx.onChange(pattern === '' ? date.toISOString() : formatDate(date, pattern, timezone));
  };

  const released = [
    on(input, 'change', () => {
      const raw = input.value.trim();
      if (raw === '') {
        emit(null);
        return;
      }
      // The control always hands back an ISO-shaped wall clock, so it is read
      // back in the display timezone rather than through `pattern`.
      emit(parseDate(raw, controlPattern, timezone));
    }),
    on(now, 'click', () => {
      const date = new Date();
      if (!isValidDate(date)) {
        return;
      }
      input.value = formatDate(date, controlPattern, timezone);
      emit(date);
    }),
  ];

  return shellWidget(shell, {
    setValue: write,
    focus() {
      input.focus();
    },
    dispose() {
      for (const release of released) {
        release();
      }
    },
  });
};

// ---------------------------------------------------------------------------
// slug
// ---------------------------------------------------------------------------

/**
 * The slug input with its refresh affordance. On mount the widget asks the host
 * to generate the slug the title would produce; when that differs from what is
 * in the file the button turns primary and offers the update, which is the only
 * signal an author gets that a renamed title left the URL behind.
 */
export const slugField: FieldFactory = (ctx) => {
  const shell = fieldShell(ctx);
  const editable = ctx.field.editable !== false;
  const input = el('input', {
    class: 'metadata_field__slug__input',
    type: 'text',
    disabled: !editable,
    value: toText(ctx.value),
  });
  input.setAttribute('aria-label', labelOf(ctx.field));
  const button = el(
    'button',
    { class: 'metadata_field__slug__button', type: 'button', title: 'Generate slug' },
    icon('refresh'),
    srOnly('Generate slug'),
  );
  shell.control.appendChild(el('div', { class: 'metadata_field__slug' }, input, button));

  let generated: string | null = null;
  let disposed = false;

  const paint = (): void => {
    shell.setEmpty(input.value.trim() === '');
    const stale = generated !== null && generated !== '' && generated !== input.value;
    button.classList.toggle('metadata_field__slug__button_update', stale);
    button.title = stale ? 'Update available' : 'Generate slug';
  };
  paint();

  const ask = (): Promise<string | null> =>
    ctx.msg
      .request<unknown>('generateSlug', {
        title: toText(ctx.state.metadata?.['title']),
        filePath: ctx.state.filePath,
        contentType: ctx.state.contentTypeName,
      })
      .then((value) => (typeof value === 'string' ? value : null))
      .catch((error: unknown) => {
        // A slug suggestion is advisory. Failing to fetch one must not put the
        // field into an error state the author has to dismiss.
        ctx.msg.log('verbose', `Slug generation failed: ${errorText(error)}`);
        return null;
      });

  void ask().then((value) => {
    if (disposed) {
      return;
    }
    generated = value;
    paint();
  });

  const emit = debounce(() => {
    ctx.onChange(input.value);
  }, 300);

  const released = [
    on(input, 'input', () => {
      paint();
      emit();
    }),
    on(input, 'blur', () => {
      emit.flush();
    }),
    on(button, 'click', () => {
      if (!editable) {
        return;
      }
      const apply = (value: string | null): void => {
        if (disposed || value === null || value === '') {
          return;
        }
        generated = value;
        input.value = value;
        emit.cancel();
        ctx.onChange(value);
        paint();
      };
      if (generated !== null && generated !== '' && generated !== input.value) {
        apply(generated);
        return;
      }
      shell.setLoading('Generating slug...');
      void ask().then((value) => {
        shell.setLoading(null);
        apply(value);
      });
    }),
  ];

  return shellWidget(shell, {
    setValue(value) {
      input.value = toText(value);
      paint();
    },
    focus() {
      input.focus();
    },
    dispose() {
      disposed = true;
      emit.cancel();
      for (const release of released) {
        release();
      }
    },
  });
};

// ---------------------------------------------------------------------------
// list
// ---------------------------------------------------------------------------

/**
 * A repeated string editor: one input, an Add/Update button pair, and a zebra
 * row list with per-row edit and delete buttons. The required message keeps the
 * label's original case here, which is Front Matter's inconsistency, preserved
 * so a project's screenshots and docs still match.
 */
export const listField: FieldFactory = (ctx) => {
  const shell = fieldShell(ctx, { rawMessageLabel: true });
  let values = toStringList(ctx.value);
  let editing: number | null = null;

  const input = el('input', { class: 'metadata_field__input', type: 'text' });
  input.setAttribute('aria-label', labelOf(ctx.field));
  const submit = el('button', { class: 'z-btn', type: 'button', disabled: true }, 'Add');
  const cancel = el('button', { class: 'z-btn z-btn--secondary', type: 'button' }, 'Cancel');
  const list = el('ul', { class: 'list_field__list' });
  const container = el(
    'div',
    { class: 'list_field' },
    input,
    el('div', { class: 'list_field__buttons' }, submit, cancel),
    list,
  );
  shell.control.appendChild(container);

  const released: Array<() => void> = [];

  const paintButtons = (): void => {
    submit.textContent = editing === null ? 'Add' : 'Update';
    submit.disabled = input.value.trim() === '';
  };

  const paintList = (): void => {
    // The row buttons are recreated with the rows; their listeners are attached
    // to nodes that are dropped here, so there is nothing to release.
    while (list.firstChild) {
      list.removeChild(list.firstChild);
    }
    values.forEach((value, index) => {
      list.appendChild(
        el(
          'li',
          {},
          el('span', {}, value),
          el(
            'span',
            { style: 'display:flex;gap:0.25rem' },
            el(
              'button',
              {
                class: 'z-icon-btn',
                type: 'button',
                title: 'Edit record',
                onclick: () => {
                  editing = index;
                  input.value = value;
                  paintButtons();
                  input.focus();
                },
              },
              icon('edit'),
              srOnly('Edit record'),
            ),
            el(
              'button',
              {
                class: 'z-icon-btn z-icon-btn--danger',
                type: 'button',
                title: 'Delete record',
                onclick: () => {
                  values = values.filter((_item, i) => i !== index);
                  if (editing === index) {
                    editing = null;
                    input.value = '';
                  }
                  commit();
                },
              },
              icon('trash'),
              srOnly('Delete record'),
            ),
          ),
        ),
      );
    });
  };

  const paintEmpty = (): void => {
    const empty = values.length === 0;
    container.classList.toggle('required', ctx.field.required === true && empty);
    shell.setEmpty(empty);
  };

  function commit(): void {
    paintList();
    paintButtons();
    paintEmpty();
    ctx.onChange(values.slice());
  }

  const accept = (): void => {
    const value = input.value.trim();
    if (value === '') {
      return;
    }
    if (editing === null) {
      values = [...values, value];
    } else {
      values = values.map((item, index) => (index === editing ? value : item));
      editing = null;
    }
    input.value = '';
    commit();
  };

  released.push(
    on(input, 'input', paintButtons),
    on(input, 'keydown', (event) => {
      if (event instanceof KeyboardEvent && event.key === 'Enter') {
        event.preventDefault();
        accept();
      }
    }),
    on(submit, 'click', accept),
    on(cancel, 'click', () => {
      editing = null;
      input.value = '';
      paintButtons();
    }),
  );

  paintList();
  paintButtons();
  paintEmpty();

  return shellWidget(shell, {
    setValue(value) {
      values = toStringList(value);
      editing = null;
      input.value = '';
      paintList();
      paintButtons();
      paintEmpty();
    },
    focus() {
      input.focus();
    },
    dispose() {
      for (const release of released) {
        release();
      }
    },
  });
};
