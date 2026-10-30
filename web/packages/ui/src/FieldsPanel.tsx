// A page's fields, rendered from the specs the platform sends with every page
// (api/pages.py field_specs) — content, SEO, the page's file and settings — so
// a new field or page type needs no change here. Values stay JSON: strings,
// numbers, string lists, ISO date-times, a switch (`noindex`), and a JSON
// object (a file's raw front matter) edited as text in Mantine's JsonInput. The
// two search fields count their characters against the lengths search engines
// show.
import { JsonInput, MultiSelect, NumberInput, Select, Stack, Switch, TagsInput, Textarea, TextInput } from '@mantine/core';
import type { FieldSpec } from '@zer0/api';
import { useState } from 'react';

export type FieldValues = Record<string, unknown>;

const SHOWN = { seo_title: 60, search_description: 160 } as Record<string, number>;

const text = (value: unknown) => (typeof value === 'string' ? value : value == null ? '' : String(value));
const list = (value: unknown) => (Array.isArray(value) ? value.map(String) : []);

/** An ISO date-time as a `datetime-local` value, in the person's own zone. */
export function toLocalInput(value: unknown): string {
  if (typeof value !== 'string' || !value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

interface Props {
  specs: FieldSpec[];
  values: FieldValues;
  onChange: (name: string, value: unknown) => void;
  group?: FieldSpec['group'];
  disabled?: boolean;
}

export function FieldsPanel({ specs, values, onChange, group, disabled }: Props) {
  return (
    <Stack gap="sm">
      {specs
        .filter((spec) => !group || spec.group === group)
        .map((spec) => (
          <Field key={spec.name} spec={spec} value={values[spec.name]} disabled={disabled} onChange={(v) => onChange(spec.name, v)} />
        ))}
    </Stack>
  );
}

/** What every input of a field shares. */
interface Common {
  label: string;
  description: string | undefined;
  required: boolean;
  disabled: boolean | undefined;
}

/** Text as the JSON it holds: empty is no value, and text that is not JSON stays text. */
export function fromJsonText(text: string): unknown {
  if (!text.trim()) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/** A JSON value edited as text. The field's value is what the text parses to, or the text itself while it does
 * not parse — so a save sends what the person sees, and the platform refuses it by field rather than an older
 * value going out unnoticed. Key order is kept: it is the order the file is written in. */
function JsonField({ common, value, onChange }: { common: Common; value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(() => (value == null ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
  return (
    <JsonInput
      {...common}
      autosize
      minRows={4}
      formatOnBlur
      validationError="Not valid JSON"
      value={text}
      onChange={(next) => {
        setText(next);
        onChange(fromJsonText(next));
      }}
    />
  );
}

function Field({ spec, value, onChange, disabled }: { spec: FieldSpec; value: unknown; onChange: (v: unknown) => void; disabled?: boolean }) {
  const limit = SHOWN[spec.name];
  const hint = [spec.help_text, limit ? `${text(value).length} / ${limit} characters shown in search results` : '']
    .filter(Boolean)
    .join(' · ');
  const common: Common = { label: spec.label, description: hint || undefined, required: spec.required, disabled };
  switch (spec.kind) {
    case 'textarea':
      return <Textarea {...common} autosize minRows={2} value={text(value)} onChange={(e) => onChange(e.currentTarget.value)} />;
    case 'datetime':
      return (
        <TextInput {...common} type="datetime-local" value={toLocalInput(value)} onChange={(e) => onChange(fromLocalInput(e.currentTarget.value))} />
      );
    case 'integer':
      return (
        <NumberInput
          {...common}
          allowDecimal={false}
          value={typeof value === 'number' ? value : ''}
          onChange={(v) => onChange(v === '' ? null : Number(v))}
        />
      );
    case 'choice':
      return <Select {...common} data={spec.choices} value={text(value) || null} allowDeselect={false} onChange={(v) => onChange(v ?? '')} />;
    case 'multichoice':
      return <MultiSelect {...common} data={spec.choices} value={list(value)} onChange={onChange} />;
    case 'tags':
      return <TagsInput {...common} value={list(value)} onChange={onChange} />;
    case 'json':
      return <JsonField common={common} value={value} onChange={onChange} />;
    case 'boolean':
      return (
        <Switch label={common.label} description={common.description} disabled={disabled} checked={value === true} onChange={(e) => onChange(e.currentTarget.checked)} />
      );
    default:
      return (
        <TextInput {...common} maxLength={spec.max_length ?? undefined} value={text(value)} onChange={(e) => onChange(e.currentTarget.value)} />
      );
  }
}
