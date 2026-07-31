/**
 * The five selection controls: `choice`, `tags`, `categories`, `taxonomy` and
 * `contentRelationship`.
 *
 * All five share one dropdown idiom — a trigger, a `.field_dropdown` list that
 * flips above the anchor when it would overflow the enclosing section, and a
 * strip of removable pills underneath — but they differ in where the options
 * come from and in what an unknown value means:
 *
 *   • `choice` offers a closed list from `field.choices`, which may be
 *     `string[]` or `{id, title}[]`. A choice with an **empty title** is Front
 *     Matter's escape hatch and renders as `Clear value`.
 *   • The three taxonomy pickers offer the project's configured vocabulary and,
 *     when `zer0Cms.panel.freeformTaxonomy` is on, accept values that are not
 *     in it. Unknown values are styled differently and carry a much blunter
 *     delete tooltip, because removing one destroys it.
 *   • `contentRelationship` asks the host for pages of a content type and
 *     stores either the page's slug or its path.
 *
 * Nothing here decides anything: a pill's `+` button posts an `addTaxonomy`
 * intent and the host decides whether to write it to the configuration. That is
 * decision D5 applied to the smallest button on the screen.
 */

import { clear, debounce, el, icon, on, srOnly } from '../../shared/dom';
import { tagPill } from '../../shared/components';
import type { Field, FieldChoice } from '../../../core/shared/types';
import type { FieldContext, FieldFactory, PageEntry } from '../../shared/protocol';
import { errorText, fieldShell, labelOf, packList, shellWidget, toStringList } from './index';

// ---------------------------------------------------------------------------
// Shared dropdown mechanics
// ---------------------------------------------------------------------------

/** Rows are 28px when the list has not been measured — Front Matter's constant. */
const ROW_HEIGHT = 28;

/**
 * Flip the list above its anchor when opening it downwards would push it out
 * of the enclosing collapsible body. Measured from the live rects rather than
 * from `offsetTop`, so it stays correct while the panel is scrolled.
 */
function positionDropdown(list: HTMLElement, anchor: HTMLElement): void {
  const body = anchor.closest('.collapsible__body');
  if (body === null) {
    list.classList.remove('above');
    return;
  }
  const height = list.offsetHeight > 0 ? list.offsetHeight : list.childElementCount * ROW_HEIGHT;
  const overflows = anchor.getBoundingClientRect().bottom + height > body.getBoundingClientRect().bottom;
  list.classList.toggle('above', overflows);
}

interface DropdownHandle {
  list: HTMLElement;
  isOpen(): boolean;
  setOpen(open: boolean): void;
  dispose(): void;
}

/**
 * A `.field_dropdown` bound to an anchor: opens, closes on an outside click or
 * Escape, and positions itself on every open. The outside-click listener is on
 * `document`, so releasing it in `dispose()` is what keeps five hundred
 * mount/dispose cycles from piling up handlers on the page.
 */
function dropdown(anchor: HTMLElement, extraClass: string): DropdownHandle {
  const list = el('ul', {
    class: `field_dropdown ${extraClass} closed`,
    attrs: { role: 'listbox' },
  });
  let open = false;
  let releaseOutside: (() => void) | undefined;

  const setOpen = (next: boolean): void => {
    open = next;
    list.classList.toggle('closed', !open);
    list.classList.toggle('open', open);
    releaseOutside?.();
    releaseOutside = undefined;
    if (!open) {
      list.classList.remove('above');
      return;
    }
    positionDropdown(list, anchor);
    releaseOutside = on(document, 'mousedown', (event) => {
      const target = event.target;
      if (target instanceof Node && !anchor.contains(target) && !list.contains(target)) {
        setOpen(false);
      }
    });
  };

  const releaseKeys = on(anchor, 'keydown', (event) => {
    if (event instanceof KeyboardEvent && event.key === 'Escape' && open) {
      event.preventDefault();
      setOpen(false);
    }
  });

  return {
    list,
    isOpen: () => open,
    setOpen,
    dispose() {
      releaseOutside?.();
      releaseOutside = undefined;
      releaseKeys();
    },
  };
}

/** One `<li>` in a `.field_dropdown`. `hint` renders the smaller, dimmer text
 *  the `Clear value` entry and the relationship slugs use. */
function option(label: string, onSelect: () => void, hint?: string): HTMLLIElement {
  return el(
    'li',
    { attrs: { role: 'option' }, onclick: onSelect },
    el('span', {}, label),
    hint === undefined ? null : el('span', { class: 'field_dropdown__hint' }, ` ${hint}`),
  );
}

// ---------------------------------------------------------------------------
// choice
// ---------------------------------------------------------------------------

interface NormalChoice {
  id: string;
  title: string;
}

/** `string[]` and `{id, title}[]` normalise to the same shape. An entry whose
 *  title is empty keeps its empty title — that is what makes it `Clear value`. */
function normalizeChoices(choices: readonly FieldChoice[] | undefined): NormalChoice[] {
  const out: NormalChoice[] = [];
  for (const choice of choices ?? []) {
    if (typeof choice === 'string') {
      out.push({ id: choice, title: choice });
    } else if (choice !== null && typeof choice === 'object') {
      out.push({ id: choice.id, title: choice.title });
    }
  }
  return out;
}

export const choiceField: FieldFactory = (ctx) => {
  const field = ctx.field;
  const label = labelOf(field);
  const multi = field.multiple === true;
  const choices = normalizeChoices(field.choices);
  const shell = fieldShell(ctx);

  let selected = toStringList(ctx.value);

  const trigger = el(
    'button',
    { class: 'metadata_field__choice__toggle', type: 'button' },
    el('span', {}, `Select ${label}`),
    icon('chevron-down'),
  );
  const menu = dropdown(trigger, 'metadata_field__choice_list');
  const pills = el('div', { class: 'article__tags__items' });
  shell.control.appendChild(el('div', { style: 'position:relative' }, trigger, menu.list));
  shell.control.appendChild(pills);

  const remaining = (): NormalChoice[] =>
    multi ? choices.filter((choice) => !selected.includes(choice.id)) : choices;

  const emit = (): void => {
    shell.setEmpty(selected.length === 0);
    ctx.onChange(multi ? packList(field, selected) : (selected[0] ?? ''));
  };

  const paint = (): void => {
    clear(menu.list);
    const options = remaining();
    trigger.disabled = options.length === 0;
    for (const choice of options) {
      // Front Matter's convention: a choice with no title clears the field.
      const empty = choice.title.trim() === '';
      menu.list.appendChild(
        empty
          ? el(
              'li',
              {
                attrs: { role: 'option' },
                style: 'opacity:0.8',
                onclick: () => {
                  selected = [];
                  menu.setOpen(false);
                  paint();
                  emit();
                },
              },
              'Clear value',
            )
          : option(choice.title, () => {
              selected = multi ? [...selected, choice.id] : [choice.id];
              menu.setOpen(false);
              paint();
              emit();
            }),
      );
    }

    clear(pills);
    for (const value of selected) {
      const known = choices.find((choice) => choice.id === value);
      pills.appendChild(
        tagPill({
          value: known ? known.title || value : value,
          known: known !== undefined,
          removeTitle: `Remove ${value}`,
          onRemove: () => {
            selected = selected.filter((item) => item !== value);
            paint();
            emit();
          },
        }),
      );
    }
    shell.setEmpty(selected.length === 0);
  };
  paint();

  const released = [
    on(trigger, 'click', () => {
      menu.setOpen(!menu.isOpen());
    }),
  ];

  return shellWidget(shell, {
    setValue(value) {
      selected = toStringList(value);
      paint();
    },
    focus() {
      trigger.focus();
    },
    dispose() {
      for (const release of released) {
        release();
      }
      menu.dispose();
    },
  });
};

// ---------------------------------------------------------------------------
// tags / categories / taxonomy
// ---------------------------------------------------------------------------

type TagKind = 'tags' | 'categories' | 'custom';

/** Where this picker's vocabulary comes from, and what an `addTaxonomy` intent
 *  has to name so the host writes the new value to the right list. */
function taxonomyFor(field: Field, ctx: FieldContext): { kind: TagKind; options: string[] } {
  if (field.type === 'tags') {
    return { kind: 'tags', options: ctx.state.taxonomy.tags };
  }
  if (field.type === 'categories') {
    return { kind: 'categories', options: ctx.state.taxonomy.categories };
  }
  const id = field.taxonomyId;
  const entry = ctx.state.taxonomy.custom.find((candidate) => candidate.id === id);
  return { kind: 'custom', options: entry?.options ?? [] };
}

/** Case-insensitive sort, known values first — Front Matter's pill order. */
function sortPills(values: readonly string[], known: ReadonlySet<string>): string[] {
  const byName = (a: string, b: string): number =>
    a.toLowerCase().localeCompare(b.toLowerCase());
  const inside = values.filter((value) => known.has(value.toLowerCase())).sort(byName);
  const outside = values.filter((value) => !known.has(value.toLowerCase())).sort(byName);
  return [...inside, ...outside];
}

/**
 * The taxonomy picker. Reproduces, in order: the `(Max.: n)` title suffix, the
 * limit-reached placeholder and disabled input, freeform gating of the `+`
 * button, comma-splitting on Enter with case-insensitive matching against the
 * vocabulary, the known/unknown pill split with their two very different delete
 * tooltips, the flip-above dropdown, and the host's `focusTags`/`focusCategories`
 * command.
 */
function tagPicker(ctx: FieldContext, focusTarget: 'tags' | 'categories' | null): ReturnType<FieldFactory> {
  const field = ctx.field;
  const label = labelOf(field) || field.type;
  const { kind, options } = taxonomyFor(field, ctx);
  const freeform = ctx.state.taxonomy.freeform;
  const limit = field.taxonomyLimit !== undefined && field.taxonomyLimit > 0 ? field.taxonomyLimit : 0;
  const knownLower = new Set(options.map((value) => value.toLowerCase()));

  const shell = fieldShell(ctx, {
    rootClass: 'article__tags',
    ...(limit > 0 ? { labelSuffix: ` (Max.: ${limit})` } : {}),
  });

  let selected = toStringList(ctx.value);

  const input = el('input', { type: 'text' });
  input.setAttribute('aria-label', label);
  const addButton = el(
    'button',
    {
      class: 'article__tags__input__button',
      type: 'button',
      title: 'Add the unknown tag',
      disabled: true,
    },
    icon('add'),
    srOnly('Add the unknown tag'),
  );
  const inputRow = el(
    'div',
    { class: freeform ? 'article__tags__input freeform' : 'article__tags__input' },
    input,
    freeform ? addButton : null,
  );
  const menu = dropdown(inputRow, 'article__tags__dropbox');
  const pills = el('div', { class: 'article__tags__items' });
  shell.control.appendChild(inputRow);
  shell.control.appendChild(menu.list);
  shell.control.appendChild(pills);

  const atLimit = (): boolean => limit > 0 && selected.length >= limit;

  const emit = (): void => {
    shell.setEmpty(selected.length === 0);
    ctx.onChange(packList(field, selected));
  };

  const add = (values: readonly string[]): void => {
    // `Set` deduplication, then the limit, then one update. Adding three tags
    // from one comma-separated entry must be one message, not three.
    const next = new Set(selected);
    for (const raw of values) {
      const value = raw.trim();
      if (value === '') {
        continue;
      }
      const match = options.find((candidate) => candidate.toLowerCase() === value.toLowerCase());
      if (match === undefined && !freeform) {
        continue;
      }
      if (limit > 0 && next.size >= limit) {
        break;
      }
      next.add(match ?? value);
    }
    selected = [...next];
    input.value = '';
    paint();
    emit();
  };

  function paint(): void {
    const reached = atLimit();
    inputRow.classList.toggle('required', field.required === true && selected.length === 0);
    input.disabled = reached;
    input.placeholder = reached
      ? `You have reached the limit of ${limit} ${label}`
      : `Pick your ${label}`;
    addButton.disabled = reached || input.value.trim() === '';

    const query = input.value.trim().toLowerCase();
    clear(menu.list);
    const offered = options.filter(
      (value) => !selected.includes(value) && (query === '' || value.toLowerCase().includes(query)),
    );
    for (const value of offered) {
      menu.list.appendChild(
        option(value, () => {
          add([value]);
          menu.setOpen(false);
        }),
      );
    }
    if (offered.length === 0) {
      menu.list.appendChild(el('li', {}, el('span', { class: 'field_dropdown__hint' }, 'No options')));
    }

    clear(pills);
    for (const value of sortPills(selected, knownLower)) {
      const known = knownLower.has(value.toLowerCase());
      pills.appendChild(
        tagPill({
          value,
          known,
          removeTitle: known
            ? `Remove ${value}`
            : `Be aware, this tag "${value}" is not saved in your settings. Once removed, it will be gone forever.`,
          onRemove: () => {
            selected = selected.filter((item) => item !== value);
            paint();
            emit();
          },
          ...(known
            ? {}
            : {
                createTitle: `Add ${value} to your settings`,
                onCreate: () => {
                  ctx.msg.post(
                    kind === 'custom'
                      ? {
                          type: 'addTaxonomy',
                          kind,
                          value,
                          ...(field.taxonomyId === undefined ? {} : { taxonomyId: field.taxonomyId }),
                        }
                      : { type: 'addTaxonomy', kind, value },
                  );
                },
              }),
        }),
      );
    }
    shell.setEmpty(selected.length === 0);
  }
  paint();

  let focusTimer: ReturnType<typeof setTimeout> | undefined;
  const released: Array<() => void> = [
    on(input, 'focus', () => {
      menu.setOpen(true);
    }),
    on(input, 'click', () => {
      menu.setOpen(true);
    }),
    on(input, 'input', () => {
      paint();
      if (!menu.isOpen()) {
        menu.setOpen(true);
      }
    }),
    on(input, 'keydown', (event) => {
      if (!(event instanceof KeyboardEvent) || event.key !== 'Enter') {
        return;
      }
      event.preventDefault();
      // No highlighted item: the raw text is split on commas and each part is
      // matched against the vocabulary, keeping unknown parts only when the
      // project allows freeform values.
      add(input.value.split(','));
      menu.setOpen(false);
    }),
    on(input, 'blur', () => {
      // Close on the next tick so a click on a dropdown row still lands.
      setTimeout(() => {
        if (!menu.list.matches(':hover')) {
          menu.setOpen(false);
        }
      }, 0);
    }),
    on(addButton, 'click', () => {
      add([input.value]);
    }),
    ctx.msg.onMessage((message) => {
      if (message.type !== 'focus' || focusTarget === null || message.target !== focusTarget) {
        return;
      }
      // The host sends this while the panel is still rendering the snapshot
      // that contains the field, so the focus is deferred exactly as FM did.
      focusTimer = setTimeout(() => {
        input.focus();
      }, 100);
    }),
  ];

  return shellWidget(shell, {
    setValue(value) {
      selected = toStringList(value);
      paint();
    },
    focus() {
      input.focus();
    },
    dispose() {
      if (focusTimer !== undefined) {
        clearTimeout(focusTimer);
      }
      for (const release of released) {
        release();
      }
      menu.dispose();
    },
  });
}

export const tagsField: FieldFactory = (ctx) => tagPicker(ctx, 'tags');
export const categoriesField: FieldFactory = (ctx) => tagPicker(ctx, 'categories');
export const taxonomyField: FieldFactory = (ctx) => tagPicker(ctx, null);

// ---------------------------------------------------------------------------
// contentRelationship
// ---------------------------------------------------------------------------

function isPageEntry(value: unknown): value is PageEntry {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof Reflect.get(value, 'title') === 'string' &&
    typeof Reflect.get(value, 'slug') === 'string'
  );
}

/**
 * A combobox over another content type's pages. The stored value is the page's
 * slug or its path, per `field.contentTypeValue`; the label shown is always the
 * page title with its slug beside it, because two pages with the same title is
 * the normal case and the slug is what tells them apart.
 */
export const contentRelationshipField: FieldFactory = (ctx) => {
  const field = ctx.field;
  const label = labelOf(field);
  const multi = field.multiple === true;
  const shell = fieldShell(ctx);

  let selected = toStringList(ctx.value);
  let pages: PageEntry[] = [];
  let disposed = false;

  const input = el('input', { type: 'text', placeholder: `Select ${label}` });
  input.setAttribute('aria-label', label);
  const chevron = el(
    'button',
    { class: 'z-icon-btn', type: 'button', title: `Show ${label} options` },
    icon('chevron-down'),
    srOnly(`Show ${label} options`),
  );
  const combo = el(
    'div',
    { class: 'article__tags__input' },
    input,
    chevron,
  );
  const menu = dropdown(combo, 'metadata_field__relationship_list');
  const pills = el('div', { class: 'article__tags__items' });
  shell.control.appendChild(combo);
  shell.control.appendChild(menu.list);
  shell.control.appendChild(pills);

  const valueOf = (page: PageEntry): string =>
    field.contentTypeValue === 'path' ? page.relPath : page.slug;

  const emit = (): void => {
    shell.setEmpty(selected.length === 0);
    ctx.onChange(multi ? selected.slice() : (selected[0] ?? ''));
  };

  const paint = (): void => {
    combo.classList.toggle('required', field.required === true && selected.length === 0);
    const query = input.value.trim().toLowerCase();
    clear(menu.list);
    const offered = pages.filter((page) => {
      if (selected.includes(valueOf(page))) {
        return false;
      }
      return query === '' || `${page.title} ${page.slug}`.toLowerCase().includes(query);
    });
    for (const page of offered) {
      menu.list.appendChild(
        option(
          page.title,
          () => {
            selected = multi ? [...selected, valueOf(page)] : [valueOf(page)];
            input.value = '';
            menu.setOpen(false);
            paint();
            emit();
          },
          page.slug,
        ),
      );
    }
    if (offered.length === 0) {
      menu.list.appendChild(
        el(
          'li',
          { style: 'text-align:center' },
          el('span', { class: 'field_dropdown__hint' }, 'No results'),
        ),
      );
    }

    clear(pills);
    for (const value of selected) {
      const page = pages.find((candidate) => valueOf(candidate) === value);
      pills.appendChild(
        tagPill({
          value: page ? page.title : value,
          known: page !== undefined,
          removeTitle: `Remove ${value}`,
          onRemove: () => {
            selected = selected.filter((item) => item !== value);
            paint();
            emit();
          },
        }),
      );
    }
    shell.setEmpty(selected.length === 0);
  };
  paint();

  shell.setLoading('Fetching possible values...');
  void ctx.msg
    .request<unknown>('searchContent', {
      type: field.contentTypeName ?? null,
      sameLocale: field.sameContentLocale ?? true,
      activePath: ctx.state.filePath,
    })
    .then((value) => {
      if (disposed) {
        return;
      }
      pages = Array.isArray(value) ? value.filter(isPageEntry) : [];
      shell.setLoading(null);
      paint();
    })
    .catch((error: unknown) => {
      if (disposed) {
        return;
      }
      shell.setLoading(null);
      shell.setError(`Could not load ${label} options: ${errorText(error)}`);
    });

  const search = debounce(() => {
    paint();
  }, 200);

  const released = [
    on(input, 'input', () => {
      menu.setOpen(true);
      search();
    }),
    on(input, 'focus', () => {
      menu.setOpen(true);
    }),
    on(chevron, 'click', () => {
      menu.setOpen(!menu.isOpen());
    }),
  ];

  return shellWidget(shell, {
    setValue(value) {
      selected = toStringList(value);
      paint();
    },
    focus() {
      input.focus();
    },
    dispose() {
      disposed = true;
      search.cancel();
      for (const release of released) {
        release();
      }
      menu.dispose();
    },
  });
};
