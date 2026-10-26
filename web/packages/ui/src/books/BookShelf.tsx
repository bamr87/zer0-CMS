// The shelf: every book of the library a person may open, with its status and
// progress, and two ways to start one — from the template (a title, a logline,
// a genre), or from a premise the outliner turns into an outline that the
// person reads before anything is made. Accepting it makes the book as a draft
// with a stub per planned chapter; nothing is published. Books live in the
// library, not in a site, so the shelf is the same whichever site is picked.
import { Alert, Anchor, Badge, Button, Card, Group, Loader, Progress, SimpleGrid, Stack, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import type { BookSummary } from './types';

export const BOOK_STATUS_COLOR: Record<string, string> = {
  idea: 'gray',
  outlining: 'violet',
  drafting: 'blue',
  revising: 'orange',
  complete: 'teal',
  archived: 'dark',
};

export function BookShelf() {
  const api = useApi();
  const [starting, setStarting] = useState<'template' | 'premise' | null>(null);
  const shelf = useQuery({ queryKey: ['books'], queryFn: () => call(api.GET('/api/v2/books/')) });
  return (
    <Stack>
      <Group>
        <Button onClick={() => setStarting(starting === 'template' ? null : 'template')}>New book</Button>
        <Button variant="light" onClick={() => setStarting(starting === 'premise' ? null : 'premise')}>
          From a premise
        </Button>
      </Group>
      {starting === 'template' ? <NewBook /> : null}
      {starting === 'premise' ? <PremiseToBook /> : null}
      {shelf.isPending ? <Loader /> : null}
      {shelf.isError ? <Alert color="red">{errorText(shelf.error)}</Alert> : null}
      {shelf.data && shelf.data.length === 0 ? <Text c="dimmed">No books yet.</Text> : null}
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {(shelf.data ?? []).map((book) => (
          <BookCard key={book.id} book={book} />
        ))}
      </SimpleGrid>
    </Stack>
  );
}

function BookCard({ book }: { book: BookSummary }) {
  const go = useGo();
  const target = book.target_word_count ? ` of ${book.target_word_count.toLocaleString()}` : '';
  return (
    <Card withBorder padding="md">
      <Group justify="space-between" align="start" wrap="nowrap">
        <Anchor component="button" type="button" fw={600} onClick={() => go({ to: 'book', id: book.id })}>
          {book.title}
        </Anchor>
        <Badge color={BOOK_STATUS_COLOR[book.status] ?? 'gray'} variant="light">
          {book.status}
        </Badge>
      </Group>
      {book.logline ? (
        <Text size="sm" c="dimmed" mt={4} lineClamp={3}>
          {book.logline}
        </Text>
      ) : null}
      <Progress value={book.progress * 100} mt="sm" aria-label={`${book.title}: ${Math.round(book.progress * 100)}%`} />
      <Text size="xs" c="dimmed" mt={4}>
        {book.chapters} of {book.planned_chapters} chapters · {book.word_count.toLocaleString()}
        {target} words · {Math.round(book.progress * 100)}%
      </Text>
    </Card>
  );
}

function NewBook() {
  const api = useApi();
  const go = useGo();
  const [fields, setFields] = useState({ title: '', logline: '', genre: '' });
  const create = useMutation({
    mutationFn: () => call(api.POST('/api/v2/books/', { body: fields })),
    onSuccess: (book) => go({ to: 'book', id: book.id }),
  });
  return (
    <Card withBorder maw={640}>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          The book starts from the library&apos;s template: its manifest, its outline skeleton and its files.
        </Text>
        <TextInput label="Title" required value={fields.title} onChange={(e) => setFields({ ...fields, title: e.currentTarget.value })} />
        <TextInput
          label="Logline"
          description="One sentence: who wants what, and what stands in the way."
          value={fields.logline}
          onChange={(e) => setFields({ ...fields, logline: e.currentTarget.value })}
        />
        <TextInput label="Genre" value={fields.genre} onChange={(e) => setFields({ ...fields, genre: e.currentTarget.value })} />
        {create.isError ? <Alert color="red">{errorText(create.error)}</Alert> : null}
        <Group>
          <Button disabled={!fields.title.trim()} loading={create.isPending} onClick={() => create.mutate()}>
            Create book
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}

interface Outline {
  title: string;
  logline: string;
  genre: string;
  synopsis: string;
  themes: { name: string; argument: string }[];
  chapters: { number: number; act: number; title: string; beat: string }[];
}

const isOutline = (value: unknown): value is Outline =>
  typeof value === 'object' && value !== null && Array.isArray((value as { chapters?: unknown }).chapters);

export function PremiseToBook() {
  const api = useApi();
  const go = useGo();
  const [premise, setPremise] = useState('');
  const [briefId, setBriefId] = useState<string | null>(null);
  const outline = useMutation({
    mutationFn: () => call(api.POST('/api/v2/books/premise/', { body: { premise } })),
    onSuccess: (accepted) => setBriefId(accepted.brief.id),
  });
  const brief = useQuery({
    queryKey: ['brief', briefId],
    enabled: briefId !== null,
    queryFn: () => call(api.GET('/api/v2/ai/briefs/{public_id}/', { params: { path: { public_id: briefId ?? '' } } })),
    refetchInterval: (query) => (query.state.data?.status === 'generating' ? 1000 : false),
  });
  const create = useMutation({
    mutationFn: () => call(api.POST('/api/v2/books/premise/{brief}/create/', { params: { path: { brief: briefId ?? '' } } })),
    onSuccess: (book) => go({ to: 'book', id: book.id }),
  });
  const ready = brief.data?.status === 'ready' && isOutline(brief.data.result) ? brief.data.result : null;

  return (
    <Card withBorder maw={820}>
      <Stack gap="sm">
        <Textarea
          label="Premise"
          description="One or two sentences — a premise, a protagonist or just a theme. The outliner proposes the book; you decide."
          autosize
          minRows={2}
          value={premise}
          disabled={briefId !== null}
          onChange={(e) => setPremise(e.currentTarget.value)}
        />
        {briefId === null ? (
          <Group>
            <Button disabled={!premise.trim()} loading={outline.isPending} onClick={() => outline.mutate()}>
              Outline it
            </Button>
          </Group>
        ) : null}
        {outline.isError ? <Alert color="red">{errorText(outline.error)}</Alert> : null}
        {brief.data?.status === 'generating' ? (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm">The outliner is writing…</Text>
          </Group>
        ) : null}
        {brief.data?.status === 'failed' ? <Alert color="red">{brief.data.error || 'The outline failed.'}</Alert> : null}
        {ready ? (
          <Stack gap="xs">
            <Title order={3}>{ready.title}</Title>
            <Text size="sm">
              <b>{ready.genre}</b> — {ready.logline}
            </Text>
            <Text size="sm" className="zer0-prose">
              {ready.synopsis}
            </Text>
            <Group gap={4}>
              {ready.themes.map((theme) => (
                <Badge key={theme.name} variant="outline" title={theme.argument}>
                  {theme.name}
                </Badge>
              ))}
            </Group>
            <Table aria-label="Chapter plan">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>Act</Table.Th>
                  <Table.Th>Title</Table.Th>
                  <Table.Th>Beat</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {ready.chapters.map((chapter) => (
                  <Table.Tr key={chapter.number}>
                    <Table.Td>{chapter.number}</Table.Td>
                    <Table.Td>{chapter.act}</Table.Td>
                    <Table.Td>{chapter.title}</Table.Td>
                    <Table.Td>{chapter.beat}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            {create.isError ? <Alert color="red">{errorText(create.error)}</Alert> : null}
            <Group>
              <Button loading={create.isPending} onClick={() => create.mutate()}>
                Create this book
              </Button>
              <Button variant="subtle" onClick={() => setBriefId(null)}>
                Start over
              </Button>
            </Group>
            <Text size="xs" c="dimmed">
              It is made as a draft: the outline, the facts, and a stub for each planned chapter. Nothing is published.
            </Text>
          </Stack>
        ) : null}
      </Stack>
    </Card>
  );
}
