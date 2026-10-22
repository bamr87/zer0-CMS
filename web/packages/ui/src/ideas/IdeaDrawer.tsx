// One idea, beside its board: edit it, move it, tag it, link the research it
// rests on, say who sees it, and promote it — to a brief an assistant writes,
// an article draft or a book draft. What it became is shown and one step away.
import { Alert, Anchor, Button, Divider, Drawer, Group, Loader, MultiSelect, SegmentedControl, Select, Stack, Switch, TagsInput, Text, Textarea, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Board, Idea, IdeaStatus } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { PagePicker } from '../PagePicker';
import { Sharing, sharedOf } from '../Sharing';
import { BriefCard } from './BriefCard';

export const STATUSES: { value: IdeaStatus; label: string }[] = [
  { value: 'new', label: 'New' },
  { value: 'exploring', label: 'Exploring' },
  { value: 'planned', label: 'Planned' },
  { value: 'promoted', label: 'Promoted' },
  { value: 'archived', label: 'Archived' },
];

export function IdeaDrawer({ ideaId, boards, onClose }: { ideaId: string | null; boards: Board[]; onClose: () => void }) {
  // No scroll lock: it injects a <style> element without the page's CSP nonce, which a host's policy refuses.
  return (
    <Drawer opened={ideaId !== null} onClose={onClose} position="right" size="lg" title="Idea" lockScroll={false}>
      {ideaId ? <IdeaDetail key={ideaId} id={ideaId} boards={boards} onGone={onClose} /> : null}
    </Drawer>
  );
}

function IdeaDetail({ id, boards, onGone }: { id: string; boards: Board[]; onGone: () => void }) {
  const api = useApi();
  const path = { params: { path: { public_id: id } } };
  const idea = useQuery({ queryKey: ['idea', id], queryFn: () => call(api.GET('/api/v2/ideas/{public_id}/', path)) });
  if (idea.isPending) return <Loader />;
  if (idea.isError) return <Alert color="red">{errorText(idea.error)}</Alert>;
  return <IdeaForm key={idea.data.updated_at} idea={idea.data} boards={boards} onGone={onGone} />;
}

function IdeaForm({ idea, boards, onGone }: { idea: Idea; boards: Board[]; onGone: () => void }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const path = { params: { path: { public_id: idea.id } } };
  const [title, setTitle] = useState(idea.title);
  const [notes, setNotes] = useState(idea.notes ?? '');
  const [tags, setTags] = useState(idea.tags ?? []);
  const [status, setStatus] = useState<IdeaStatus>(idea.status ?? 'new');
  const [board, setBoard] = useState(idea.board ?? '');
  const [linked, setLinked] = useState(idea.sources.map((s) => s.id));
  const [shared, setShared] = useState(sharedOf(idea));
  const [into, setInto] = useState<'brief' | 'article' | 'book'>('brief');
  const [parent, setParent] = useState<number | null>(null);
  const [now, setNow] = useState(true);
  const sources = useQuery({
    queryKey: ['sources', { page_size: 200 }],
    queryFn: () => call(api.GET('/api/v2/research/sources/', { params: { query: { page_size: 200 } } })),
  });
  const done = (message: string) => {
    notifications.show({ message });
    void qc.invalidateQueries({ queryKey: ['ideas'] });
    void qc.invalidateQueries({ queryKey: ['idea', idea.id] });
  };
  const save = useMutation({
    mutationFn: () =>
      call(api.PATCH('/api/v2/ideas/{public_id}/', { ...path, body: { title, notes, tags, status, board: board || null, source_ids: linked, ...shared } })),
    onSuccess: () => done('Idea saved'),
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/v2/ideas/{public_id}/', path)),
    onSuccess: () => {
      done('Idea deleted');
      onGone();
    },
  });
  const promote = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/ideas/{public_id}/promote/', { ...path, body: { into, generate: into === 'brief' && now, ...(parent ? { parent } : {}) } })),
    onSuccess: (promoted) => {
      done(into === 'brief' ? 'Promoted to a brief' : 'Promoted to a draft');
      if (promoted.page_id) go({ to: 'page', id: promoted.page_id });
    },
  });
  const failure = save.error ?? remove.error ?? promote.error;
  const page = idea.page;
  const known = new Map([...(sources.data?.results ?? []).map((s) => [s.id, s.title || s.url] as const), ...idea.sources.map((s) => [s.id, s.title || s.url] as const)]);

  return (
    <Stack>
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
      <TextInput label="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
      <Textarea label="Notes" autosize minRows={4} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
      <TagsInput label="Tags" value={tags} onChange={setTags} />
      <Group grow>
        <Select label="Status" data={STATUSES} value={status} allowDeselect={false} onChange={(value) => setStatus((value ?? 'new') as IdeaStatus)} />
        <Select
          label="Board"
          data={[{ value: '', label: 'Inbox' }, ...boards.map((b) => ({ value: b.id, label: b.name }))]}
          value={board}
          allowDeselect={false}
          onChange={(value) => setBoard(value ?? '')}
        />
      </Group>
      <MultiSelect
        label="Research it rests on"
        searchable
        data={[...known].map(([value, label]) => ({ value, label }))}
        value={linked}
        onChange={setLinked}
      />
      <Sharing value={shared} onChange={setShared} />
      <Text size="xs" c="dimmed">
        {idea.origin} · {idea.votes} vote{idea.votes === 1 ? '' : 's'}
        {idea.url ? (
          <>
            {' · '}
            <Anchor href={idea.url} target="_blank" rel="noreferrer" size="xs">
              where it came from
            </Anchor>
          </>
        ) : null}
      </Text>
      <Group>
        <Button disabled={!title.trim()} loading={save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
        <Button variant="subtle" color="red" loading={remove.isPending} onClick={() => remove.mutate()}>
          Delete
        </Button>
      </Group>
      <Divider label="What it became" />
      {idea.brief ? <BriefCard briefId={idea.brief.id} /> : null}
      {page ? (
        <Button variant="light" onClick={() => go({ to: 'page', id: page.id })}>
          Open “{page.title}”
        </Button>
      ) : null}
      {!idea.brief && !page ? (
        <Stack gap="xs" aria-label="Promote">
          <SegmentedControl
            value={into}
            onChange={(value) => setInto(value as typeof into)}
            data={[
              { value: 'brief', label: 'A brief' },
              { value: 'article', label: 'An article draft' },
              { value: 'book', label: 'A book draft' },
            ]}
          />
          {into === 'brief' ? (
            <Switch label="Have the Article writer write it now" checked={now} onChange={(e) => setNow(e.currentTarget.checked)} />
          ) : null}
          <PagePicker label={into === 'brief' ? 'Where its draft will go (optional)' : 'Where the draft goes'} parents value={parent} onChange={setParent} />
          <Button loading={promote.isPending} disabled={into !== 'brief' && !parent} onClick={() => promote.mutate()}>
            Promote
          </Button>
        </Stack>
      ) : null}
    </Stack>
  );
}
