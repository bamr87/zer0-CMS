// One book: its facts and progress, its outline (and the outliner's proposal
// beside it, with a diff, to take or leave), its character bible, continuity
// ledger and style guide, its other files (act guides, README), its chapters in
// reading order (open one to write it), the validation findings with the books
// package's codes, and its compiled manuscript to read and download. The book's
// fields are the page's own, saved as a draft revision through the page
// endpoints, never published here — the switch for the brand guard's built-in
// bans on its chapters among them; its other files are saved the same way, one
// at a time.
import { Alert, Anchor, Badge, Button, Card, Group, Loader, Progress, SimpleGrid, Stack, Table, Tabs, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { DiffView } from '../DiffView';
import { FieldsPanel, type FieldValues } from '../FieldsPanel';
import { StatusBadge } from '../StatusBadge';
import { BookAssist } from './BookAssist';
import { BookFiles } from './BookFiles';
import { BOOK_STATUS_COLOR } from './BookShelf';
import type { BookDetail, BookIssue } from './types';

const FACTS = [
  'book_status',
  'logline',
  'genre',
  'pov',
  'tense',
  'era',
  'protagonist',
  'acts',
  'planned_chapters',
  'target_word_count',
  'themes',
  'cast',
  'subtitle',
  'author',
  'builtin_bans',
];
const NOTES = ['character_notes', 'continuity_notes', 'style_guide'];

export function BookView({ bookId }: { bookId: number }) {
  const api = useApi();
  const go = useGo();
  const book = useQuery({
    queryKey: ['book', bookId],
    queryFn: () => call(api.GET('/api/v2/books/{id}/', { params: { path: { id: bookId } } })),
  });
  if (book.isPending) return <Loader />;
  if (book.isError) return <Alert color="red">{errorText(book.error)}</Alert>;
  const data = book.data;
  return (
    <Stack>
      <Group justify="space-between" align="start">
        <Stack gap={2}>
          <Anchor component="button" type="button" size="sm" onClick={() => go({ to: 'books' })}>
            ← The shelf
          </Anchor>
          <Group gap="xs">
            <Title order={2}>{data.title}</Title>
            <Badge color={BOOK_STATUS_COLOR[data.status] ?? 'gray'} variant="light">
              {data.status}
            </Badge>
            <StatusBadge status={data.page_status} />
          </Group>
          {data.logline ? (
            <Text size="sm" c="dimmed" maw={760}>
              {data.logline}
            </Text>
          ) : null}
        </Stack>
      </Group>
      <Tabs defaultValue="overview" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="overview">Overview</Tabs.Tab>
          <Tabs.Tab value="outline">Outline</Tabs.Tab>
          <Tabs.Tab value="notes">Characters &amp; continuity</Tabs.Tab>
          <Tabs.Tab value="files">Files</Tabs.Tab>
          <Tabs.Tab value="chapters">Chapters ({data.chapter_list.length})</Tabs.Tab>
          <Tabs.Tab value="checks">
            Checks ({data.errors} / {data.warnings})
          </Tabs.Tab>
          <Tabs.Tab value="manuscript">Manuscript</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview" pt="md">
          <Stack>
            <Stats book={data} />
            <BookFields pageId={bookId} names={FACTS} editable={data.can_edit} />
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="outline" pt="md">
          <Outline bookId={bookId} editable={data.can_edit} />
        </Tabs.Panel>
        <Tabs.Panel value="notes" pt="md">
          <BookFields pageId={bookId} names={NOTES} editable={data.can_edit} />
        </Tabs.Panel>
        <Tabs.Panel value="files" pt="md">
          <BookFiles bookId={bookId} editable={data.can_edit} />
        </Tabs.Panel>
        <Tabs.Panel value="chapters" pt="md">
          <Chapters book={data} />
        </Tabs.Panel>
        <Tabs.Panel value="checks" pt="md">
          <Checks bookId={bookId} />
        </Tabs.Panel>
        <Tabs.Panel value="manuscript" pt="md">
          <Manuscript bookId={bookId} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

function Stats({ book }: { book: BookDetail }) {
  const { stats } = book;
  const target = stats.target_word_count ? ` of ${stats.target_word_count.toLocaleString()}` : '';
  return (
    <Card withBorder>
      <Group justify="space-between">
        <Text fw={600}>
          {stats.word_count.toLocaleString()}
          {target} words of prose
        </Text>
        <Text size="sm" c="dimmed">
          {stats.chapters} of {stats.planned_chapters} chapters · {Math.round(stats.progress * 100)}%
        </Text>
      </Group>
      <Progress value={stats.progress * 100} mt="xs" aria-label="Progress" />
      <SimpleGrid cols={{ base: 1, sm: 3 }} mt="sm">
        <Group gap={4}>
          {Object.entries(stats.status_counts).map(([status, count]) => (
            <Badge key={status} variant="outline">
              {count} {status}
            </Badge>
          ))}
        </Group>
        {stats.longest ? (
          <Text size="sm">
            Longest: ch{stats.longest.number} {stats.longest.title} ({stats.longest.word_count.toLocaleString()})
          </Text>
        ) : null}
        {stats.shortest ? (
          <Text size="sm">
            Shortest: ch{stats.shortest.number} {stats.shortest.title} ({stats.shortest.word_count.toLocaleString()})
          </Text>
        ) : null}
      </SimpleGrid>
      <Text size="xs" c="dimmed" mt="xs">
        Words are the narrative only: a chapter&apos;s outline scaffolding is not counted.
      </Text>
    </Card>
  );
}

/** Some of the book page's fields, from the page endpoints, saved as a draft revision. */
export function BookFields({
  pageId,
  names,
  editable,
  incoming,
}: {
  pageId: number;
  names: string[];
  editable: boolean;
  incoming?: FieldValues;
}) {
  const api = useApi();
  const qc = useQueryClient();
  const page = useQuery({
    queryKey: ['page', pageId],
    queryFn: () => call(api.GET('/api/v2/content/pages/{id}/', { params: { path: { id: pageId } } })),
  });
  const [edits, setEdits] = useState<FieldValues>({});
  const values = { ...page.data?.fields, ...incoming, ...edits };
  const changed = Object.fromEntries(
    Object.entries({ ...incoming, ...edits }).filter(([name, value]) => JSON.stringify(value) !== JSON.stringify(page.data?.fields[name])),
  );
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH('/api/v2/content/pages/{id}/', {
          params: { path: { id: pageId } },
          body: { base_revision_id: page.data?.latest_revision?.id ?? null, fields: changed },
        }),
      ),
    onSuccess: (saved) => {
      qc.setQueryData(['page', pageId], saved);
      setEdits({});
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'page' });
      notifications.show({ message: 'Draft saved' });
    },
  });
  if (page.isPending) return <Loader />;
  if (page.isError) return <Alert color="red">{errorText(page.error)}</Alert>;
  const specs = page.data.field_specs.filter((spec) => names.includes(spec.name)).sort((a, b) => names.indexOf(a.name) - names.indexOf(b.name));
  const dirty = Object.keys(changed).length > 0;
  return (
    <Stack maw={860}>
      <FieldsPanel specs={specs} values={values} disabled={!editable} onChange={(name, value) => setEdits((e) => ({ ...e, [name]: value }))} />
      {save.isError ? <Alert color="red">{errorText(save.error)}</Alert> : null}
      <Group>
        <Button disabled={!dirty || !editable} loading={save.isPending} onClick={() => save.mutate()}>
          Save draft
        </Button>
        {dirty ? <Text size="sm" c="orange">Unsaved changes</Text> : null}
      </Group>
    </Stack>
  );
}

function Outline({ bookId, editable }: { bookId: number; editable: boolean }) {
  const api = useApi();
  const page = useQuery({
    queryKey: ['page', bookId],
    queryFn: () => call(api.GET('/api/v2/content/pages/{id}/', { params: { path: { id: bookId } } })),
  });
  const [proposed, setProposed] = useState<string | null>(null);
  const [taken, setTaken] = useState<string | null>(null);
  const current = String(page.data?.fields.outline ?? '');
  return (
    <SimpleGrid cols={{ base: 1, lg: 2 }}>
      <BookFields key={taken ?? 'outline'} pageId={bookId} names={['outline']} editable={editable} incoming={taken === null ? undefined : { outline: taken }} />
      <Stack>
        <BookAssist bookId={bookId} onOutline={setProposed} />
        {proposed !== null ? (
          <Card withBorder>
            <Text fw={600} mb="xs">
              The outliner&apos;s proposal, against the outline
            </Text>
            <DiffView before={current} after={proposed} />
            <Group mt="sm">
              <Button size="xs" disabled={!editable} onClick={() => setTaken(proposed)}>
                Use it (then save)
              </Button>
              <Button size="xs" variant="subtle" onClick={() => setProposed(null)}>
                Leave it
              </Button>
            </Group>
          </Card>
        ) : null}
      </Stack>
    </SimpleGrid>
  );
}

function Chapters({ book }: { book: BookDetail }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [title, setTitle] = useState('');
  const add = useMutation({
    mutationFn: () => call(api.POST('/api/v2/books/{id}/chapters/', { params: { path: { id: book.id } }, body: { title } })),
    onSuccess: (detail) => {
      qc.setQueryData(['book', book.id], detail);
      setTitle('');
      notifications.show({ message: 'Chapter added as a draft' });
    },
  });
  return (
    <Stack>
      <Table highlightOnHover aria-label="Chapters">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>#</Table.Th>
            <Table.Th>Title</Table.Th>
            <Table.Th>Act</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th>Point of view</Table.Th>
            <Table.Th>Words</Table.Th>
            <Table.Th>Findings</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {book.chapter_list.map((chapter) => (
            <Table.Tr key={chapter.path}>
              <Table.Td>{chapter.number ?? '?'}</Table.Td>
              <Table.Td>
                {chapter.id !== null ? (
                  <Anchor component="button" type="button" onClick={() => go({ to: 'chapter', book: book.id, id: chapter.id ?? 0 })}>
                    {chapter.title}
                  </Anchor>
                ) : (
                  chapter.title
                )}
              </Table.Td>
              <Table.Td>{chapter.act ?? '–'}</Table.Td>
              <Table.Td>{chapter.status}</Table.Td>
              <Table.Td>{chapter.pov || '–'}</Table.Td>
              <Table.Td>{chapter.word_count.toLocaleString()}</Table.Td>
              <Table.Td>
                {chapter.errors ? <Badge color="red">{chapter.errors}</Badge> : null}{' '}
                {chapter.warnings ? <Badge color="yellow">{chapter.warnings}</Badge> : null}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {book.can_add_chapter ? (
        <Group align="end">
          <TextInput label="Next chapter" placeholder="Its title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
          <Button disabled={!title.trim()} loading={add.isPending} onClick={() => add.mutate()}>
            Add chapter
          </Button>
        </Group>
      ) : null}
      {add.isError ? <Alert color="red">{errorText(add.error)}</Alert> : null}
    </Stack>
  );
}

export function Checks({ bookId, path }: { bookId: number; path?: string }) {
  const api = useApi();
  const issues = useQuery({
    queryKey: ['book-issues', bookId],
    queryFn: () => call(api.GET('/api/v2/books/{id}/issues/', { params: { path: { id: bookId } } })),
  });
  if (issues.isPending) return <Loader size="sm" />;
  if (issues.isError) return <Alert color="red">{errorText(issues.error)}</Alert>;
  const shown = issues.data.filter((issue) => path === undefined || issue.path === path);
  if (shown.length === 0) return <Text c="dimmed">No findings.</Text>;
  const byFile = new Map<string, BookIssue[]>();
  for (const issue of shown) byFile.set(issue.path, [...(byFile.get(issue.path) ?? []), issue]);
  return (
    <Stack gap="xs">
      {[...byFile.entries()].map(([file, found]) => (
        <Card key={file} withBorder padding="xs">
          <Text size="sm" fw={600}>
            {file}
          </Text>
          {found.map((issue, i) => (
            <Group key={i} gap="xs" wrap="nowrap" align="start">
              <Badge color={issue.level === 'error' ? 'red' : 'yellow'} size="sm" variant="light">
                {issue.level}
              </Badge>
              <Text size="sm">
                {issue.line ? `line ${issue.line} · ` : ''}
                <code>{issue.code}</code> {issue.message}
              </Text>
            </Group>
          ))}
        </Card>
      ))}
    </Stack>
  );
}

function Manuscript({ bookId }: { bookId: number }) {
  const api = useApi();
  const [withOutline, setWithOutline] = useState(false);
  const [asked, setAsked] = useState(false);
  const built = useQuery({
    queryKey: ['manuscript', bookId, withOutline],
    enabled: asked,
    queryFn: () =>
      call(api.GET('/api/v2/books/{id}/manuscript/', { params: { path: { id: bookId }, query: { include_outline: withOutline } } })),
  });
  return (
    <Stack>
      <Group>
        <Button onClick={() => setAsked(true)} loading={built.isFetching}>
          Build the manuscript
        </Button>
        <Button variant="subtle" onClick={() => setWithOutline(!withOutline)}>
          {withOutline ? 'Without the outline' : 'With the outline'}
        </Button>
      </Group>
      {built.isError ? <Alert color="red">{errorText(built.error)}</Alert> : null}
      {built.data ? (
        <Card withBorder>
          <Group justify="space-between">
            <Text size="sm">
              {built.data.word_count.toLocaleString()} words · title page, act headings, the prose of every chapter
            </Text>
            <Anchor href={`data:text/markdown;charset=utf-8,${encodeURIComponent(built.data.markdown)}`} download={built.data.filename}>
              Download {built.data.filename}
            </Anchor>
          </Group>
          <Text size="sm" mt="sm" className="zer0-prose" lineClamp={40}>
            {built.data.markdown}
          </Text>
        </Card>
      ) : null}
    </Stack>
  );
}
