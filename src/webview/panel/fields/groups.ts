/**
 * The four structural types: `fields`, `fieldCollection`, `divider`, `heading`.
 *
 * `fields` is the only one that does real work. It draws the dashed
 * `.metadata_field__box`, centres its own title, and renders its sub-fields
 * recursively through `createFieldWidget` — which is what makes the eighteen
 * types compose rather than nest by special case.
 *
 * Two decisions worth stating:
 *
 *   1. **Nested edits are leaf-addressed.** A child's change posts
 *      `updateField` with the full key path (`['seo', 'title']`), not a rebuilt
 *      copy of the whole group object. `FieldContext.parents` exists precisely
 *      to be joined with the field name into that path; sending the merged
 *      object instead would make every keystroke in a group rewrite every
 *      sibling key, which decision D7's line surgery is designed to avoid.
 *   2. **`when` is evaluated for sub-fields here.** The panel host evaluates it
 *      for top-level fields, but nobody else ever sees the sub-object a group
 *      is rendered against. The evaluator below is a compact port of
 *      `core/content/fields.ts#evaluateWhen`, including the parent cascade and
 *      the "incomparable operands are visible" rule; it is restated rather than
 *      imported because that module reaches `core/content/placeholders.ts`,
 *      which imports `node:child_process` and cannot be bundled for a browser.
 *
 * `fieldCollection` should never reach a widget: `inlineFieldCollections()`
 * replaces it with the group's fields before the panel state is built. If one
 * arrives anyway it is rendered as a group when it carries inlined fields, and
 * as nothing when it does not — a config referencing an unknown group must not
 * put an empty box on the screen.
 */

import { el } from '../../shared/dom';
import type { Field, WhenOperator } from '../../../core/shared/types';
import type { FieldContext, FieldWidget, FieldFactory, FmValue } from '../../shared/protocol';
import { createFieldWidget, emptyWidget, fieldShell, labelOf, shellWidget } from './index';

// ---------------------------------------------------------------------------
// `when`, ported for the browser bundle
// ---------------------------------------------------------------------------

function lowerValue(value: unknown): unknown {
  if (typeof value === 'string') {
    return value.toLowerCase();
  }
  if (Array.isArray(value)) {
    return value.map((item) => (typeof item === 'string' ? item.toLowerCase() : item));
  }
  return value;
}

/** Returning `true` for operands that cannot be compared is deliberate: a
 *  config whose types drifted should show too much, never hide a required
 *  field the author then cannot fill in. */
function compare(operator: WhenOperator, left: unknown, right: unknown): boolean {
  switch (operator) {
    case 'eq':
      return left === right;
    case 'neq':
      return left !== right;
    case 'contains':
      if (typeof left === 'string') {
        return left.includes(String(right));
      }
      if (Array.isArray(left)) {
        return left.some((item) => item === right);
      }
      return true;
    case 'notContains':
      if (typeof left === 'string') {
        return !left.includes(String(right));
      }
      if (Array.isArray(left)) {
        return !left.some((item) => item === right);
      }
      return true;
    case 'startsWith':
      return typeof left === 'string' ? left.startsWith(String(right)) : true;
    case 'endsWith':
      return typeof left === 'string' ? left.endsWith(String(right)) : true;
    case 'gt':
      return typeof left === 'number' && typeof right === 'number' ? left > right : true;
    case 'gte':
      return typeof left === 'number' && typeof right === 'number' ? left >= right : true;
    case 'lt':
      return typeof left === 'number' && typeof right === 'number' ? left < right : true;
    case 'lte':
      return typeof left === 'number' && typeof right === 'number' ? left <= right : true;
    default:
      return true;
  }
}

function evaluate(
  field: Field,
  data: Record<string, FmValue>,
  all: readonly Field[],
  seen: Set<string>,
): boolean {
  const when = field.when;
  if (when === undefined) {
    return true;
  }
  const parent = all.find((candidate) => candidate.name === when.fieldRef);
  if (parent !== undefined && parent.when !== undefined && !seen.has(parent.name)) {
    seen.add(parent.name);
    if (!evaluate(parent, data, all, seen)) {
      return false;
    }
  }
  let value: FmValue | undefined = data[when.fieldRef];
  if (value === undefined && parent !== undefined && parent.default !== undefined) {
    value = parent.default;
  }
  const sensitive = when.caseSensitive ?? true;
  return sensitive
    ? compare(when.operator, value, when.value)
    : compare(when.operator, lowerValue(value), lowerValue(when.value));
}

/**
 * Should this field be shown? `all` is the sibling set the `fieldRef` is
 * resolved against — the content type's fields at the top level, the nested set
 * inside a group. Exported because the dispatcher applies the same rule to
 * top-level fields, which nobody else evaluates.
 */
export function fieldIsVisible(
  field: Field,
  data: Record<string, FmValue>,
  all: readonly Field[],
): boolean {
  return evaluate(field, data, all, new Set([field.name]));
}

// ---------------------------------------------------------------------------
// fields / fieldCollection
// ---------------------------------------------------------------------------

/** The group's value as a plain object, whatever nonsense the file held. */
function asObject(value: FmValue | undefined): Record<string, FmValue> {
  if (value !== null && value !== undefined && typeof value === 'object' && !Array.isArray(value)) {
    return { ...value };
  }
  return {};
}

function renderGroup(ctx: FieldContext, children: readonly Field[]): FieldWidget {
  const shell = fieldShell(ctx, { centred: true, icon: null });
  const box = el('div', { class: 'metadata_field__box metadata_fields' });
  shell.control.appendChild(box);

  const childParents = [...ctx.parents, ctx.field.name];
  let data = asObject(ctx.value);
  let widgets: Array<{ field: Field; widget: FieldWidget }> = [];

  const build = (): void => {
    for (const entry of widgets) {
      entry.widget.dispose();
    }
    widgets = [];
    while (box.firstChild) {
      box.removeChild(box.firstChild);
    }

    for (const child of children) {
      if (child.hidden === true || !fieldIsVisible(child, data, children)) {
        continue;
      }
      // A default is adopted for display only. Writing it upstream unasked
      // would turn opening a file into an edit, which is the host's decision
      // to make, not a widget's.
      const stored = data[child.name];
      const current: FmValue | undefined = stored === undefined ? child.default : stored;
      const childCtx: FieldContext = {
        field: child,
        parents: childParents,
        value: current,
        state: ctx.state,
        msg: ctx.msg,
        onChange: (next) => {
          if (next === undefined) {
            delete data[child.name];
          } else {
            data[child.name] = next;
          }
          ctx.msg.updateField([...childParents, child.name], next === undefined ? null : next);
        },
      };
      const widget = createFieldWidget(childCtx);
      if (widget === null) {
        continue;
      }
      widgets.push({ field: child, widget });
      box.appendChild(widget.el);
    }
    shell.setEmpty(Object.keys(data).length === 0);
  };
  build();

  return shellWidget(shell, {
    setValue(value) {
      const next = asObject(value);
      // A `when` clause can make a sibling appear or vanish, so the child set
      // is rebuilt whenever the group's own object changes shape. Values that
      // only changed content are pushed into the existing widgets instead.
      const sameShape =
        Object.keys(next).length === Object.keys(data).length &&
        Object.keys(next).every((key) => key in data);
      data = next;
      if (!sameShape) {
        build();
        return;
      }
      for (const entry of widgets) {
        const held = data[entry.field.name];
        entry.widget.setValue(held === undefined ? entry.field.default : held);
      }
      shell.setEmpty(Object.keys(data).length === 0);
    },
    focus() {
      widgets[0]?.widget.focus();
    },
    dispose() {
      for (const entry of widgets) {
        entry.widget.dispose();
      }
      widgets = [];
    },
  });
}

export const fieldsGroupField: FieldFactory = (ctx) => renderGroup(ctx, ctx.field.fields ?? []);

export const fieldCollectionField: FieldFactory = (ctx) => {
  const children = ctx.field.fields ?? [];
  if (children.length === 0) {
    ctx.msg.log(
      'verbose',
      `Field collection "${ctx.field.name}" resolved to no fields; nothing rendered.`,
    );
    return emptyWidget();
  }
  return renderGroup(ctx, children);
};

// ---------------------------------------------------------------------------
// divider / heading
// ---------------------------------------------------------------------------

/** A 1px rule inset from both edges. Carries no value and no chrome. */
export const dividerField: FieldFactory = () => emptyWidget(el('div', { class: 'metadata_field__divider' }));

/** A sub-heading inside the field stack, with an optional description below. */
export const headingField: FieldFactory = (ctx) => {
  const description = ctx.field.description;
  return emptyWidget(
    el(
      'div',
      { class: 'metadata_field__heading' },
      el('h3', {}, labelOf(ctx.field)),
      description !== undefined && description.trim() !== ''
        ? el('p', { class: 'metadata_field__description' }, description)
        : null,
    ),
  );
};
