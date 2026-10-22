// Research: collections of sources and everything gathered — pages captured
// from the web, documents, notes, feed items, web search hits — with their
// fetch status; asking the sources; feeds; and a research brief on a topic.
// A source opens on its own page (SourceView), as the host routes it.
import { Alert, Anchor, Badge, Button, Code, Group, Loader, NavLink, Stack, Table, Tabs, Text, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { AskPanel } from './AskPanel';
import { CaptureSource } from './CaptureSource';
import { FeedsPanel } from './FeedsPanel';
import { ResearchBrief } from './ResearchBrief';
import { WAITING } from './runs';

const KIND: Record<string, string> = { url: 'web page', feed: 'feed item', document: 'document', note: 'note' };
const STATUS_COLOR: Record<string, string> = { ready: 'teal', failed: 'red', pending: 'yellow', fetching: 'yellow' };

interface Props {
  siteId?: number;
  /** A page address to capture, as a bookmarklet handed it to the host; captured only when the person says so. */
  captureUrl?: string;
  /** The host's bookmarklet, shown to copy into a browser's bookmarks (only the host knows its own address). */
  bookmarklet?: string;
}

export function ResearchWorkspace({ siteId, captureUrl, bookmarklet }: Props) {
  const api = useApi();
  const qc = useQueryClient();
  const [collection, setCollection] = useState<string | null>(null);
  const [name, setName] = useState('');
  const collections = useQuery({
    queryKey: ['collections', siteId],
    queryFn: () => call(api.GET('/api/v2/research/collections/', { params: { query: { site: siteId, page_size: 200 } } })),
  });
  const add = useMutation({
    mutationFn: () => call(api.POST('/api/v2/research/collections/', { body: { name } })),
    onSuccess: (made) => {
      setName('');
      setCollection(made.id);
      void qc.invalidateQueries({ queryKey: ['collections'] });
    },
  });

  return (
    <Group align="start" wrap="nowrap" gap="lg">
      <Stack w={220} gap={4} aria-label="Collections">
        <NavLink component="button" label="All sources" active={collection === null} onClick={() => setCollection(null)} />
        {(collections.data?.results ?? []).map((c) => (
          <NavLink component="button" key={c.id} label={c.name} description={c.description || undefined} active={collection === c.id} onClick={() => setCollection(c.id)} />
        ))}
        <Group gap={4} mt="xs" wrap="nowrap">
          <TextInput size="xs" placeholder="New collection" aria-label="New collection" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <Button size="xs" variant="light" disabled={!name.trim()} loading={add.isPending} onClick={() => add.mutate()}>
            Add
          </Button>
        </Group>
        {add.isError ? <Alert color="red">{errorText(add.error)}</Alert> : null}
      </Stack>
      <Tabs defaultValue="sources" keepMounted={false} flex={1} miw={0}>
        <Tabs.List>
          <Tabs.Tab value="sources">Sources</Tabs.Tab>
          <Tabs.Tab value="ask">Ask</Tabs.Tab>
          <Tabs.Tab value="feeds">Feeds</Tabs.Tab>
          <Tabs.Tab value="brief">Research brief</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="sources" pt="md">
          <Stack>
            <CaptureSource collection={collection} initialUrl={captureUrl} />
            {bookmarklet ? (
              <Text size="xs" c="dimmed">
                Capture from any page: save <Code>{bookmarklet}</Code> as a bookmark, and click it on the page.
              </Text>
            ) : null}
            <SourceList collection={collection} />
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="ask" pt="md">
          <AskPanel collection={collection} />
        </Tabs.Panel>
        <Tabs.Panel value="feeds" pt="md">
          <FeedsPanel collection={collection} />
        </Tabs.Panel>
        <Tabs.Panel value="brief" pt="md">
          {collection ? <ResearchBrief key={collection} collection={collection} /> : <Text c="dimmed">Choose a collection to write a research brief from.</Text>}
        </Tabs.Panel>
      </Tabs>
    </Group>
  );
}

function SourceList({ collection }: { collection: string | null }) {
  const api = useApi();
  const go = useGo();
  const [words, setWords] = useState('');
  const query = { collection: collection ?? undefined, q: words || undefined, page_size: 100 };
  const sources = useQuery({
    queryKey: ['sources', query],
    queryFn: () => call(api.GET('/api/v2/research/sources/', { params: { query } })),
    refetchInterval: (q) => (q.state.data?.results.some((s) => WAITING.has(s.status)) ? 1500 : false),
  });
  return (
    <Stack gap="xs">
      <TextInput placeholder="Find a source" aria-label="Find a source" value={words} onChange={(e) => setWords(e.currentTarget.value)} />
      {sources.isPending ? <Loader /> : null}
      {sources.isError ? <Alert color="red">{errorText(sources.error)}</Alert> : null}
      {sources.data?.results.length === 0 ? <Text c="dimmed">No sources here yet.</Text> : null}
      {sources.data?.results.length ? (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Source</Table.Th>
              <Table.Th>Kind</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Added</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {sources.data.results.map((s) => (
              <Table.Tr key={s.id}>
                <Table.Td>
                  <Anchor component="button" type="button" ta="left" onClick={() => go({ to: 'source', id: s.id })}>
                    {s.title || s.url || 'Untitled'}
                  </Anchor>
                  {s.error ? (
                    <Text size="xs" c="red">
                      {s.error}
                    </Text>
                  ) : null}
                </Table.Td>
                <Table.Td>{KIND[s.kind] ?? s.kind}</Table.Td>
                <Table.Td>
                  <Badge color={STATUS_COLOR[s.status] ?? 'gray'} variant="light">
                    {s.status}
                  </Badge>
                </Table.Td>
                <Table.Td>{new Date(s.created_at).toLocaleDateString()}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </Stack>
  );
}
