// Who sees a board, a collection, an idea or a source — only its owner, the
// editors of one site, or everyone signed in — and the small form that names
// and shares a board or a collection. The platform decides: a row belongs only
// to a site its owner edits, and only the owner (or staff) changes who sees it,
// so a refusal comes back as the server's message, never a rule kept here.
import { Alert, Button, Select, Stack, Textarea, TextInput, type MantineSize } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import type { Visibility } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from './call';
import { useApi } from './context';

export interface Shared {
  visibility: Visibility;
  site: number | null;
}

export const WHO: Record<Visibility, string> = { private: 'Only me', site: 'Editors of a site', shared: 'Everyone signed in' };

/** A row's sharing as the form edits it; a new row (`siteId` given) starts in the studio's site, private. */
export const sharedOf = (row: { visibility?: Visibility; site?: number | null }, siteId?: number): Shared => ({
  visibility: row.visibility ?? 'private',
  site: row.site ?? siteId ?? null,
});

interface SharingProps {
  value: Shared;
  onChange: (next: Shared) => void;
  size?: MantineSize;
}

export function Sharing({ value, onChange, size }: SharingProps) {
  const api = useApi();
  const sites = useQuery({ queryKey: ['sites'], queryFn: () => call(api.GET('/api/v2/sites/')) });
  const mine = sites.data ?? [];
  const who = (Object.keys(WHO) as Visibility[]).map((v) => ({ value: v, label: WHO[v], disabled: v === 'site' && !mine.length }));
  const pick = (visibility: Visibility) => onChange({ visibility, site: visibility === 'site' ? (value.site ?? mine[0]?.id ?? null) : value.site });
  return (
    <Stack gap="xs">
      <Select size={size} label="Who sees it" data={who} value={value.visibility} allowDeselect={false} onChange={(v) => pick((v ?? 'private') as Visibility)} />
      {value.visibility === 'site' ? (
        <Select
          size={size}
          label="Site"
          data={mine.map((s) => ({ value: String(s.id), label: s.name }))}
          value={value.site ? String(value.site) : null}
          allowDeselect={false}
          onChange={(v) => onChange({ ...value, site: v ? Number(v) : null })}
        />
      ) : null}
    </Stack>
  );
}

export interface ListValues extends Shared {
  name: string;
  description: string;
}

interface ListFormProps {
  initial?: { name: string; description?: string; visibility?: Visibility; site?: number | null };
  /** The studio's site, a new board's or collection's site until the person picks another. */
  siteId?: number;
  action: string;
  pending: boolean;
  error: unknown;
  onSubmit: (values: ListValues) => void;
}

/** A board's or a collection's name, description and who sees it: to make one, or to change it. */
export function ListForm({ initial, siteId, action, pending, error, onSubmit }: ListFormProps) {
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [shared, setShared] = useState(initial ? sharedOf(initial) : sharedOf({}, siteId));
  return (
    <Stack
      gap="xs"
      component="form"
      aria-label={action}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ name: name.trim(), description, ...shared });
      }}
    >
      <TextInput size="xs" label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} />
      <Textarea size="xs" label="Description" autosize value={description} onChange={(e) => setDescription(e.currentTarget.value)} />
      <Sharing size="xs" value={shared} onChange={setShared} />
      {error ? <Alert color="red">{errorText(error)}</Alert> : null}
      <Button size="xs" type="submit" disabled={!name.trim()} loading={pending}>
        {action}
      </Button>
    </Stack>
  );
}
