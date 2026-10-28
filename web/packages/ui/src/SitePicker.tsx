// The site picker: every site the person can work in, and "All sites". The
// host keeps the choice (the studio per browser, the extension per panel);
// this only lists the sites and reports which one was picked.
import { Select } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';

import { call } from './call';
import { useApi } from './context';

export function SitePicker({ value, onChange }: { value: number | undefined; onChange: (id: number | undefined) => void }) {
  const api = useApi();
  const sites = useQuery({ queryKey: ['sites'], queryFn: () => call(api.GET('/api/v2/sites/')) });
  return (
    <Select
      aria-label="Site"
      size="xs"
      w={190}
      data={[{ value: '', label: 'All sites' }, ...(sites.data ?? []).map((s) => ({ value: String(s.id), label: s.name }))]}
      value={value ? String(value) : ''}
      allowDeselect={false}
      onChange={(next) => onChange(Number(next) || undefined)}
    />
  );
}
