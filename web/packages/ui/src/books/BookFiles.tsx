// A book's other files — the act guides a chapter task reads beside the brief,
// its README — opened one at a time, edited, added or removed, each change a
// draft revision of the book saved against the revision the files were read
// from (a newer one is refused, never overwritten). The manifest, the outline,
// the notes and the chapters are edited in their own tabs.
import { Alert, Button, Grid, Group, Loader, NavLink, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';

export function BookFiles({ bookId, editable }: { bookId: number; editable: boolean }) {
  const api = useApi();
  const qc = useQueryClient();
  const files = useQuery({
    queryKey: ['book-documents', bookId],
    queryFn: () => call(api.GET('/api/v2/books/{id}/documents/', { params: { path: { id: bookId } } })),
  });
  const [open, setOpen] = useState<string | null>(null);
  const [edit, setEdit] = useState<string | null>(null);
  const [adding, setAdding] = useState('');
  const save = useMutation({
    mutationFn: (change: { path: string; text: string | null }) =>
      call(
        api.POST('/api/v2/books/{id}/documents/', {
          params: { path: { id: bookId } },
          body: { base_revision_id: files.data?.revision ?? null, ...change },
        }),
      ),
    onSuccess: (saved, change) => {
      qc.setQueryData(['book-documents', bookId], saved);
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'book-documents' });
      setEdit(null);
      setOpen(change.text === null ? null : change.path);
      notifications.show({ message: change.text === null ? 'Removed in a draft' : 'Draft saved' });
    },
  });
  if (files.isPending) return <Loader />;
  if (files.isError) return <Alert color="red">{errorText(files.error)}</Alert>;
  const current = files.data.documents.find((d) => d.path === open);
  const text = edit ?? current?.text ?? '';
  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 4 }}>
        <Stack gap={4}>
          {files.data.documents.map((d) => (
            <NavLink
              key={d.path}
              label={d.path}
              active={d.path === open}
              onClick={() => {
                setOpen(d.path);
                setEdit(null);
              }}
            />
          ))}
          {editable ? (
            <Group align="end" gap="xs" mt="sm">
              <TextInput size="xs" label="New file" placeholder="guides/act-4-chapters-15-18.md" value={adding} onChange={(e) => setAdding(e.currentTarget.value)} />
              <Button
                size="xs"
                variant="light"
                disabled={!adding.trim()}
                onClick={() => {
                  save.mutate({ path: adding.trim(), text: '' });
                  setAdding('');
                }}
              >
                Add
              </Button>
            </Group>
          ) : null}
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 8 }}>
        {save.isError ? <Alert color="red">{errorText(save.error)}</Alert> : null}
        {current ? (
          <Stack>
            <Textarea label={current.path} autosize minRows={12} value={text} disabled={!editable} onChange={(e) => setEdit(e.currentTarget.value)} />
            <Group>
              <Button disabled={!editable || edit === null || edit === current.text} loading={save.isPending} onClick={() => save.mutate({ path: current.path, text })}>
                Save draft
              </Button>
              <Button variant="subtle" color="red" disabled={!editable} onClick={() => save.mutate({ path: current.path, text: null })}>
                Remove
              </Button>
            </Group>
          </Stack>
        ) : (
          <Text c="dimmed">Pick a file. An act guide covering a chapter is what the book assistant reads beside the brief.</Text>
        )}
      </Grid.Col>
    </Grid>
  );
}
