/**
 * What a field *means*: which values count as empty, when a field is visible,
 * what a `fieldCollection` expands to, and which required fields a document is
 * still missing.
 *
 * This is the module the panel, the diagnostics collection, `processFields` and
 * the MCP server all consult, so every question about a field is answered in
 * one place and answered the same way. It knows nothing about the DOM and
 * nothing about the filesystem — hand it a `Field` and an `FmValue` and it
 * tells you the truth about them.
 *
 * Three properties are load-bearing:
 *
 *   1. **All 18 field types have an empty value and an emptiness test.** A type
 *      that falls through to a `default:` branch is a type whose new documents
 *      get the wrong shape, and nobody notices until a site build fails.
 *   2. **`when` hides a field, it never invents one.** An operator that cannot
 *      compare the values it was given returns `true` (visible) rather than
 *      guessing — Front Matter's leniency, kept deliberately, because a config
 *      whose types drifted should show too much, not silently hide a required
 *      field the author then cannot fill in.
 *   3. **`inlineFieldCollections` does not mutate its input.** FM spliced the
 *      resolved group straight into the settings object it had just read, so
 *      the *config* changed shape as a side effect of reading it. Here the
 *      expansion is a new array and the function is idempotent.
 *
 * The four `when` operators Front Matter declares but never implements
 * (`minimum`, `maximum`, `exlusiveMinimum` (sic), `exclusiveMaximum`) are not
 * in `WhenOperator` at all — an unimplemented operator that silently evaluates
 * to "visible" is a config that lies to its author.
 */

import { humanize } from '../shared/text';
import type { Field, FieldGroup, WhenOperator, Zer0Config } from '../shared/types';
import type { FmValue, FrontMatter } from './frontmatter';
import { FAULTY_PLACEHOLDER } from './placeholders';

// ---------------------------------------------------------------------------
// Field collections
// ---------------------------------------------------------------------------

/** UI-only field types: they carry no front-matter key of their own. */
const PRESENTATION_TYPES: ReadonlySet<string> = new Set(['divider', 'heading']);

function inline(
  fields: readonly Field[],
  groups: readonly FieldGroup[],
  seen: ReadonlySet<string>,
): Field[] {
  const out: Field[] = [];

  for (const field of fields) {
    if (field.type === 'fieldCollection') {
      const id = field.fieldGroup;
      // A collection with no group, an unknown group, or a group that (directly
      // or transitively) contains itself expands to nothing. Leaving the
      // placeholder field in place would render a control for a type that has
      // no widget; recursing would not terminate.
      if (id === undefined || seen.has(id)) {
        continue;
      }
      const group = groups.find((candidate) => candidate.id === id);
      if (group === undefined) {
        continue;
      }
      const nested = new Set(seen);
      nested.add(id);
      out.push(...inline(group.fields, groups, nested));
      continue;
    }

    if (field.type === 'fields') {
      out.push({ ...field, fields: inline(field.fields ?? [], groups, seen) });
      continue;
    }

    out.push(field);
  }

  return out;
}

/**
 * Replace every `fieldCollection` with the fields of the group it names, in
 * place of the collection and in the group's own order. Nested `fields` sets
 * are expanded too. Running it twice changes nothing.
 */
export function inlineFieldCollections(
  fields: readonly Field[],
  groups: readonly FieldGroup[],
): Field[] {
  return inline(fields, groups, new Set<string>());
}

/** The first field with this name, searching nested `fields` sets depth-first. */
export function findField(fields: readonly Field[], name: string): Field | undefined {
  for (const field of fields) {
    if (field.name === name) {
      return field;
    }
    if (field.type === 'fields' && field.fields) {
      const nested = findField(field.fields, name);
      if (nested !== undefined) {
        return nested;
      }
    }
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// `when` clauses
// ---------------------------------------------------------------------------

/** Lowercase a scalar or a list of scalars; anything else passes through. */
function lowerValue(value: unknown): unknown {
  if (typeof value === 'string') {
    return value.toLowerCase();
  }
  if (Array.isArray(value)) {
    return value.map((item) => (typeof item === 'string' ? item.toLowerCase() : item));
  }
  return value;
}

/**
 * Apply one operator. Returning `true` for a comparison whose operands are not
 * comparable is FM's behaviour and is kept on purpose: `startsWith` against a
 * number means the config drifted, and hiding the field would hide the drift.
 */
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
  data: FrontMatter,
  all: readonly Field[],
  seen: Set<string>,
): boolean {
  const when = field.when;
  if (when === undefined) {
    return true;
  }

  const parent = all.find((candidate) => candidate.name === when.fieldRef);

  // Parent cascade: a field conditioned on a field that is itself hidden is
  // hidden too, however its own comparison would come out. `seen` stops a
  // config whose `when` clauses form a loop from recursing forever.
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

  // `caseSensitive` defaults to true — an unset flag means "compare exactly".
  const sensitive = when.caseSensitive ?? true;
  return sensitive
    ? compare(when.operator, value, when.value)
    : compare(when.operator, lowerValue(value), lowerValue(when.value));
}

/**
 * Should this field be shown (and, during creation, written)? `all` is the
 * sibling set the `fieldRef` is resolved against; pass the content type's
 * fields, or the nested set when evaluating inside a `fields` group.
 */
export function evaluateWhen(field: Field, data: FrontMatter, all: readonly Field[] = []): boolean {
  return evaluate(field, data, all, new Set([field.name]));
}

/** The subset of `fields` whose `when` clause is satisfied, in declaration order. */
export function visibleFields(fields: readonly Field[], data: FrontMatter): Field[] {
  return fields.filter((field) => evaluateWhen(field, data, fields));
}

// ---------------------------------------------------------------------------
// Empty values
// ---------------------------------------------------------------------------

/**
 * The value a new document gets for this field when nothing else supplies one.
 *
 * Every one of the 18 types is listed explicitly. `divider` and `heading` are
 * presentation-only and answer `null`, which `processFields` reads as "write
 * nothing at all" — they have no front-matter key. `fieldCollection` never
 * survives `inlineFieldCollections`, so reaching it here means a caller skipped
 * the expansion; `null` keeps that mistake out of the file.
 */
export function emptyValueFor(field: Field, cfg: Zer0Config): FmValue {
  switch (field.type) {
    case 'string':
    case 'slug':
      return '';
    case 'number':
      return 0;
    case 'boolean':
      return false;
    case 'datetime':
      return null;
    case 'image':
    case 'file':
    case 'contentRelationship':
    case 'choice':
      return field.multiple === true ? [] : '';
    case 'tags':
    case 'categories':
    case 'taxonomy':
    case 'list':
      return [];
    case 'draft':
      // A new document is a draft. When the configured draft field marks
      // *published* instead (`invert`), that same statement is `false`.
      if (cfg.draftField.type === 'choice') {
        return cfg.draftField.choices?.[0] ?? '';
      }
      return cfg.draftField.invert !== true;
    case 'fields':
      return {};
    case 'divider':
    case 'heading':
    case 'fieldCollection':
      return null;
    default:
      return null;
  }
}

/**
 * Does this field hold no usable value? `false` and `0` are values, not
 * emptiness — only a missing key, a blank string, an empty list or object, and
 * the `<failed to process>` placeholder sentinel count.
 */
export function isEmpty(field: Field, value: FmValue | undefined): boolean {
  if (PRESENTATION_TYPES.has(field.type) || field.type === 'fieldCollection') {
    return true;
  }
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

// ---------------------------------------------------------------------------
// Labels, limits, validation
// ---------------------------------------------------------------------------

/** The label a UI shows: the configured `title`, else a readable form of `name`. */
export function labelOf(field: Field): string {
  const title = field.title;
  if (title !== undefined && title.trim() !== '') {
    return title;
  }
  return humanize(field.name) || field.name;
}

/**
 * The character budget shown next to a text control, or `-1` for "no limit".
 *
 * Only the two SEO fields have one, and only while SEO is enabled: a threshold
 * of `0` or less means the author switched that check off, which is `-1` here
 * rather than "a limit of zero characters".
 */
export function limitFor(field: Field, cfg: Zer0Config): number {
  if (!cfg.seo.enabled) {
    return -1;
  }
  if (field.name === cfg.seo.titleField) {
    return cfg.seo.titleLength > 0 ? cfg.seo.titleLength : -1;
  }
  if (field.name === cfg.seo.descriptionField) {
    return cfg.seo.descriptionLength > 0 ? cfg.seo.descriptionLength : -1;
  }
  return -1;
}

/** One required field with nothing in it. `path` is the key path from the root. */
export interface FieldViolation {
  path: string[];
  field: Field;
  message: string;
}

function collect(
  fields: readonly Field[],
  data: FrontMatter,
  cfg: Zer0Config,
  parents: readonly string[],
  out: FieldViolation[],
): void {
  for (const field of fields) {
    if (!evaluateWhen(field, data, fields)) {
      // A field the author cannot see is a field they cannot fill in.
      continue;
    }

    // Values are read at the level being walked; `parents` exists only to
    // report where the violation is. Looking the value up by its full path
    // against a nested object would look for `seo.seo.title`.
    const path = [...parents, field.name];
    const value: FmValue | undefined = data[field.name];

    if (field.type === 'fields' && field.fields) {
      const nested =
        value !== null && value !== undefined && typeof value === 'object' && !Array.isArray(value)
          ? value
          : {};
      collect(field.fields, nested, cfg, path, out);
      continue;
    }

    if (field.required === true && isEmpty(field, value)) {
      out.push({ path, field, message: `${labelOf(field)} is required.` });
    }
  }
}

/**
 * Every required field that is empty, depth-first, in declaration order.
 * Returns nothing at all when validation is switched off, so the one setting
 * governs the panel, the diagnostics and the MCP status tool together.
 *
 * Nested `fields` groups are walked against their own sub-object, so a
 * violation's `path` addresses the exact leaf (`['seo', 'title']`).
 */
export function validateFields(
  fields: readonly Field[],
  data: FrontMatter,
  cfg: Zer0Config,
): FieldViolation[] {
  if (!cfg.validation.enabled) {
    return [];
  }
  const out: FieldViolation[] = [];
  collect(fields, data, cfg, [], out);
  return out;
}
