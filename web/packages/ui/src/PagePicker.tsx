// A searchable choice of page, for the workspaces that put something on a
// page or under one: where an idea's draft goes, which page cites a source,
// which page a site's voice is resolved for. It lists the pages the person can
// find (GET /api/v2/content/pages/), only those that can hold children when it
// picks a parent, and searches on the platform (`q`, the title or the slug) as
// the person types, so a site with more pages than one answer holds still has
// every page within reach; the choice keeps its label while the search moves
// on. The platform checks the right to add or edit again when the choice is
// used.
import { Select } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

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

interface Option {
  value: string;
  label: string;
}

export function PagePicker({ label, value, onChange, parents, siteId, description }: Props) {
  const api = useApi();
  const [search, setSearch] = useState('');
  const [chosen, setChosen] = useState<Option | null>(null);
  // Choosing a page puts its label in the box; that is not a search.
  const [q] = useDebouncedValue(search === chosen?.label ? '' : search.trim(), 250);
  const query = { site: siteId, can_have_children: parents ? true : undefined, ordering: 'path', page_size: 100, q: q || undefined };
  const pages = useQuery({
    queryKey: ['pages', query],
    queryFn: () => call(api.GET('/api/v2/content/pages/', { params: { query } })),
    placeholderData: keepPreviousData,
  });
  const found: Option[] = (pages.data?.results ?? []).map((p) => ({ value: String(p.id), label: `${p.title} (${p.type_label})` }));
  const kept = chosen && chosen.value === String(value) && !found.some((o) => o.value === chosen.value) ? [chosen] : [];
  return (
    <Select
      label={label}
      description={description}
      searchable
      clearable
      placeholder={pages.isPending ? 'Loading pages…' : 'Choose a page'}
      nothingFoundMessage={pages.isFetching ? 'Searching…' : 'No page matches'}
      data={[...kept, ...found]}
      value={value ? String(value) : null}
      searchValue={search}
      onSearchChange={setSearch}
      onChange={(id, option) => {
        setChosen(id && option ? { value: option.value, label: option.label } : null);
        onChange(id ? Number(id) : null);
      }}
    />
  );
}
