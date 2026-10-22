// Pages across a site (or every site), any status, with the filters an editor
// reaches for first — status, type and text — paginated by the platform, and
// a title to open each one in the editor. The tree is walked a level at a
// time: a page with pages under it opens to them, and the trail leads back.
import { Alert, Anchor, Breadcrumbs, Button, Group, Loader, Pagination, Select, Stack, Table, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useQuery } from '@tanstack/react-query';
import type { PageStatus } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from './call';
import { useApi, useGo } from './context';
import { STATUS_OPTIONS, StatusBadge } from './StatusBadge';

const PAGE_SIZE = 25;

export function PageList({ siteId }: { siteId?: number }) {
  const api = useApi();
  const go = useGo();
  const [status, setStatus] = useState<string | null>(null);
  const [type, setType] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [q] = useDebouncedValue(text, 250);
  const [page, setPage] = useState(1);
  const [trail, setTrail] = useState<{ id: number; title: string }[]>([]);
  const types = useQuery({ queryKey: ['types'], queryFn: () => call(api.GET('/api/v2/content/types/')) });
  const query = {
    site: siteId,
    parent: trail.at(-1)?.id,
    status: (status ?? undefined) as PageStatus | undefined,
    type: type ?? undefined,
    q: q || undefined,
    page,
    page_size: PAGE_SIZE,
  };
  const pages = useQuery({
    queryKey: ['pages', query],
    queryFn: () => call(api.GET('/api/v2/content/pages/', { params: { query } })),
  });
  const filter = (set: (value: string | null) => void) => (value: string | null) => {
    set(value);
    setPage(1);
  };
  const walk = (next: { id: number; title: string }[]) => {
    setTrail(next);
    setPage(1);
  };

  return (
    <Stack>
      <Breadcrumbs aria-label="Where in the tree">
        <Anchor component="button" type="button" onClick={() => walk([])}>
          All pages
        </Anchor>
        {trail.map((step, i) => (
          <Anchor key={step.id} component="button" type="button" onClick={() => walk(trail.slice(0, i + 1))}>
            {step.title}
          </Anchor>
        ))}
      </Breadcrumbs>
      <Group grow>
        <Select label="Status" placeholder="Any status" clearable data={STATUS_OPTIONS} value={status} onChange={filter(setStatus)} />
        <Select
          label="Type"
          placeholder="Any type"
          clearable
          data={(types.data ?? []).map((t) => ({ value: t.type, label: t.label }))}
          value={type}
          onChange={filter(setType)}
        />
        <TextInput
          label="Search"
          placeholder="Title or slug"
          value={text}
          onChange={(event) => {
            setText(event.currentTarget.value);
            setPage(1);
          }}
        />
      </Group>
      {pages.isPending ? (
        <Loader />
      ) : pages.isError ? (
        <Alert color="red">{errorText(pages.error)}</Alert>
      ) : pages.data.count === 0 ? (
        <Text c="dimmed">No pages match.</Text>
      ) : (
        <>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Title</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Last edited</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {pages.data.results.map((p) => (
                <Table.Tr key={p.id}>
                  <Table.Td>
                    <Anchor component="button" type="button" onClick={() => go({ to: 'page', id: p.id })}>
                      {p.title}
                    </Anchor>
                    <Text size="xs" c="dimmed">
                      {p.url_path}
                    </Text>
                  </Table.Td>
                  <Table.Td>{p.type_label}</Table.Td>
                  <Table.Td>
                    <StatusBadge status={p.status} />
                  </Table.Td>
                  <Table.Td>{p.latest_revision_created_at ? new Date(p.latest_revision_created_at).toLocaleString() : '—'}</Table.Td>
                  <Table.Td>
                    {p.children ? (
                      <Button size="compact-xs" variant="subtle" onClick={() => walk([...trail, { id: p.id, title: p.title }])}>
                        {p.children} inside
                      </Button>
                    ) : null}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              {pages.data.count} page{pages.data.count === 1 ? '' : 's'}
            </Text>
            <Pagination total={Math.ceil(pages.data.count / PAGE_SIZE)} value={page} onChange={setPage} />
          </Group>
        </>
      )}
    </Stack>
  );
}
