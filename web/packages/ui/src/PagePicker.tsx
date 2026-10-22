// A searchable choice of page, for the workspaces that put something on a
// page or under one: where an idea's draft goes, which page cites a source.
// It lists the pages the person can find (GET /api/v2/content/pages/), only
// those that can hold children when it picks a parent; the platform checks
// the right to add or edit again when the choice is used.
import { Select } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';

import { call } from './call';
import { useApi } from './context';

interface Props {
  label: string;
  value: number | null;
  onChange: (id: number | null) => void;
  /** Only pages that can hold children (where a new page goes). */
  parents?: boolean;
  siteId?: number;
  description?: string;
}

export function PagePicker({ label, value, onChange, parents, siteId, description }: Props) {
  const api = useApi();
  const query = { site: siteId, can_have_children: parents ? true : undefined, ordering: 'path', page_size: 100 };
  const pages = useQuery({
    queryKey: ['pages', query],
    queryFn: () => call(api.GET('/api/v2/content/pages/', { params: { query } })),
  });
  return (
    <Select
      label={label}
      description={description}
      searchable
      clearable
      placeholder={pages.isPending ? 'Loading pages…' : 'Choose a page'}
      data={(pages.data?.results ?? []).map((p) => ({ value: String(p.id), label: `${p.title} (${p.type_label})` }))}
      value={value ? String(value) : null}
      onChange={(id) => onChange(id ? Number(id) : null)}
    />
  );
}
