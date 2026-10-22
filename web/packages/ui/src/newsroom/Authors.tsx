// Authors: the people bylines name — a profile (name, bio, email) added here by
// a desk's editor — and each author's page: their published stories, newest
// first, the same list a site's author page shows.
import { Alert, Anchor, Button, Card, Group, List, Loader, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';
import { when } from './shared';

export function Authors() {
  const api = useApi();
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const [form, setForm] = useState({ name: '', bio: '', email: '' });
  const authors = useQuery({
    queryKey: ['newsroom', 'authors'],
    queryFn: () => call(api.GET('/api/v2/newsroom/authors/', { params: { query: { page_size: 200 } } })),
  });
  const add = useMutation({
    mutationFn: () => call(api.POST('/api/v2/newsroom/authors/', { body: form })),
    onSuccess: (author) => {
      setForm({ name: '', bio: '', email: '' });
      setOpen(author.id);
      void qc.invalidateQueries({ queryKey: ['newsroom', 'authors'] });
    },
  });
  const set = (name: keyof typeof form) => (e: { currentTarget: { value: string } }) => setForm({ ...form, [name]: e.currentTarget.value });
  return (
    <Group align="flex-start" grow>
      <Stack>
        {authors.isPending ? (
          <Loader />
        ) : authors.isError ? (
          <Alert color="red">{errorText(authors.error)}</Alert>
        ) : authors.data.count === 0 ? (
          <Text c="dimmed">No authors yet.</Text>
        ) : (
          authors.data.results.map((a) => (
            <Anchor key={a.id} component="button" type="button" ta="left" fw={a.id === open ? 700 : 400} onClick={() => setOpen(a.id)}>
              {a.name}
            </Anchor>
          ))
        )}
        <Card withBorder>
          <Stack gap="xs">
            <Title order={5}>Add an author</Title>
            <TextInput label="Name" value={form.name} onChange={set('name')} />
            <Textarea label="Bio" autosize minRows={2} value={form.bio} onChange={set('bio')} />
            <TextInput label="Email" type="email" value={form.email} onChange={set('email')} />
            {add.error ? <Alert color="red">{errorText(add.error)}</Alert> : null}
            <Button w="fit-content" disabled={!form.name.trim()} loading={add.isPending} onClick={() => add.mutate()}>
              Add the author
            </Button>
          </Stack>
        </Card>
      </Stack>
      {open ? <AuthorPage key={open} id={open} /> : <Text c="dimmed">Choose an author to see their page.</Text>}
    </Group>
  );
}

function AuthorPage({ id }: { id: string }) {
  const api = useApi();
  const author = useQuery({
    queryKey: ['newsroom', 'author', id],
    queryFn: () => call(api.GET('/api/v2/newsroom/authors/{public_id}/', { params: { path: { public_id: id } } })),
  });
  if (author.isPending) return <Loader />;
  if (author.isError) return <Alert color="red">{errorText(author.error)}</Alert>;
  return (
    <Stack gap="xs" aria-label="Author page">
      <Title order={4}>{author.data.name}</Title>
      {author.data.bio ? <Text size="sm">{author.data.bio}</Text> : null}
      <Text size="sm" fw={500}>
        Published stories
      </Text>
      {author.data.stories.length ? (
        <List>
          {author.data.stories.map((s) => (
            <List.Item key={s.id}>
              {s.headline}{' '}
              <Text span size="xs" c="dimmed">
                {s.url_path} · {when(s.published_at)}
              </Text>
            </List.Item>
          ))}
        </List>
      ) : (
        <Text size="sm" c="dimmed">
          None yet.
        </Text>
      )}
    </Stack>
  );
}
