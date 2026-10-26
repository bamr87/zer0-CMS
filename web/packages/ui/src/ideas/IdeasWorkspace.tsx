// Ideas: the boards and the inbox (ideas on no board), a board's ideas in
// columns by status with their votes, capture, a brainstorm session, the
// clusters and likely duplicates found by meaning, and one idea in a drawer —
// edit, link research, share, promote. A board is made and changed — named,
// and shared with a site's editors or everyone — beside the list of boards.
// Every change goes through /api/v2/ideas/.
import { Alert, Anchor, Badge, Button, Card, Group, Loader, Menu, NavLink, SegmentedControl, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Idea, IdeaStatus } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';
import { ListForm, WHO, type ListValues } from '../Sharing';
import { Brainstorm } from './Brainstorm';
import { CaptureIdea } from './CaptureIdea';
import { Clusters } from './Clusters';
import { IdeaDrawer, STATUSES } from './IdeaDrawer';

const INBOX = 'none';
const COLUMNS = STATUSES.filter((s) => s.value !== 'archived');

export function IdeasWorkspace({ siteId }: { siteId?: number }) {
  const api = useApi();
  const qc = useQueryClient();
  const [board, setBoard] = useState(INBOX);
  const [view, setView] = useState<'board' | 'clusters'>('board');
  const [panel, setPanel] = useState<'capture' | 'brainstorm' | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [editing, setEditing] = useState<'new' | 'board' | null>(null);
  const boards = useQuery({
    queryKey: ['boards', siteId],
    queryFn: () => call(api.GET('/api/v2/ideas/boards/', { params: { query: { site: siteId, page_size: 200 } } })),
  });
  const query = { board, site: siteId, page_size: 200, ordering: '-vote_count' };
  const ideas = useQuery({ queryKey: ['ideas', query], queryFn: () => call(api.GET('/api/v2/ideas/', { params: { query } })) });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['ideas'] });
  const boardsChanged = () => {
    setEditing(null);
    void qc.invalidateQueries({ queryKey: ['boards'] });
  };
  const addBoard = useMutation({
    mutationFn: (values: ListValues) => call(api.POST('/api/v2/ideas/boards/', { body: values })),
    onSuccess: (made) => {
      setBoard(made.id);
      boardsChanged();
    },
  });
  const saveBoard = useMutation({
    mutationFn: (values: ListValues) => call(api.PATCH('/api/v2/ideas/boards/{public_id}/', { params: { path: { public_id: board } }, body: values })),
    onSuccess: boardsChanged,
  });
  const vote = useMutation({
    mutationFn: (idea: Idea) => {
      const path = { params: { path: { public_id: idea.id } } };
      return idea.voted ? call(api.DELETE('/api/v2/ideas/{public_id}/vote/', path)) : call(api.POST('/api/v2/ideas/{public_id}/vote/', path));
    },
    onSuccess: refresh,
  });
  const move = useMutation({
    mutationFn: ({ idea, status }: { idea: Idea; status: IdeaStatus }) =>
      call(api.PATCH('/api/v2/ideas/{public_id}/', { params: { path: { public_id: idea.id } }, body: { status } })),
    onSuccess: refresh,
  });
  const boardList = boards.data?.results ?? [];
  const onBoard = board === INBOX ? null : board;
  const current = boardList.find((b) => b.id === board);
  const failure = vote.error ?? move.error;

  return (
    <Group align="start" wrap="nowrap" gap="lg">
      <Stack w={220} gap={4} aria-label="Boards">
        <NavLink component="button" label="Inbox" description="Ideas on no board" active={board === INBOX} onClick={() => setBoard(INBOX)} />
        {boardList.map((b) => (
          <NavLink
            component="button"
            key={b.id}
            label={b.name}
            description={b.visibility && b.visibility !== 'private' ? WHO[b.visibility] : undefined}
            active={board === b.id}
            onClick={() => {
              setBoard(b.id);
              setEditing(null);
            }}
          />
        ))}
        <Group gap={4} mt="xs">
          <Button size="xs" variant={editing === 'new' ? 'filled' : 'light'} onClick={() => setEditing(editing === 'new' ? null : 'new')}>
            New board
          </Button>
          {current ? (
            <Button size="xs" variant={editing === 'board' ? 'filled' : 'subtle'} onClick={() => setEditing(editing === 'board' ? null : 'board')}>
              Board settings
            </Button>
          ) : null}
        </Group>
        {editing === 'new' ? <ListForm siteId={siteId} action="Add board" pending={addBoard.isPending} error={addBoard.error} onSubmit={addBoard.mutate} /> : null}
        {editing === 'board' && current ? (
          <ListForm key={current.id} initial={current} action="Save board" pending={saveBoard.isPending} error={saveBoard.error} onSubmit={saveBoard.mutate} />
        ) : null}
      </Stack>
      <Stack flex={1} miw={0}>
        <Group justify="space-between">
          <SegmentedControl
            value={view}
            onChange={(value) => setView(value as typeof view)}
            data={[
              { value: 'board', label: 'Board' },
              { value: 'clusters', label: 'Clusters' },
            ]}
          />
          <Group gap="xs">
            <Button variant={panel === 'capture' ? 'filled' : 'light'} onClick={() => setPanel(panel === 'capture' ? null : 'capture')}>
              Capture
            </Button>
            <Button variant={panel === 'brainstorm' ? 'filled' : 'light'} onClick={() => setPanel(panel === 'brainstorm' ? null : 'brainstorm')}>
              Brainstorm
            </Button>
          </Group>
        </Group>
        {panel ? (
          <Card withBorder>
            {panel === 'capture' ? <CaptureIdea boardId={onBoard} /> : <Brainstorm key={board} boardId={onBoard} />}
          </Card>
        ) : null}
        {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}
        {view === 'clusters' ? <Clusters board={board} onOpen={setOpen} /> : null}
        {view === 'board' && ideas.isPending ? <Loader /> : null}
        {view === 'board' && ideas.isError ? <Alert color="red">{errorText(ideas.error)}</Alert> : null}
        {view === 'board' && ideas.data ? (
          <SimpleGrid cols={{ base: 1, md: 2, lg: 4 }}>
            {COLUMNS.map((column) => {
              const here = ideas.data.results.filter((idea) => (idea.status ?? 'new') === column.value);
              return (
                <Stack key={column.value} gap="xs" aria-label={column.label}>
                  <Group gap="xs">
                    <Title order={5}>{column.label}</Title>
                    <Badge variant="light" color="gray">
                      {here.length}
                    </Badge>
                  </Group>
                  {here.map((idea) => (
                    <IdeaCard
                      key={idea.id}
                      idea={idea}
                      onOpen={() => setOpen(idea.id)}
                      onVote={() => vote.mutate(idea)}
                      onMove={(status) => move.mutate({ idea, status })}
                    />
                  ))}
                </Stack>
              );
            })}
          </SimpleGrid>
        ) : null}
      </Stack>
      <IdeaDrawer ideaId={open} boards={boardList} onClose={() => setOpen(null)} />
    </Group>
  );
}

interface CardProps {
  idea: Idea;
  onOpen: () => void;
  onVote: () => void;
  onMove: (status: IdeaStatus) => void;
}

function IdeaCard({ idea, onOpen, onVote, onMove }: CardProps) {
  return (
    <Card withBorder padding="xs" component="article" aria-label={idea.title}>
      <Anchor component="button" type="button" fw={600} size="sm" ta="left" onClick={onOpen}>
        {idea.title}
      </Anchor>
      {idea.notes ? (
        <Text size="xs" c="dimmed" lineClamp={2}>
          {idea.notes}
        </Text>
      ) : null}
      <Group gap={4} mt={4}>
        {(idea.tags ?? []).map((tag) => (
          <Badge key={tag} size="xs" variant="outline">
            {tag}
          </Badge>
        ))}
        {idea.sources.length ? (
          <Badge size="xs" variant="light">
            {idea.sources.length} source{idea.sources.length === 1 ? '' : 's'}
          </Badge>
        ) : null}
      </Group>
      <Group gap={4} mt="xs" justify="space-between">
        <Button size="compact-xs" variant={idea.voted ? 'filled' : 'light'} aria-pressed={idea.voted} onClick={onVote}>
          {idea.voted ? 'Voted' : 'Vote'} · {idea.votes}
        </Button>
        <Menu position="bottom-end">
          <Menu.Target>
            <Button size="compact-xs" variant="subtle" aria-label={`Move ${idea.title}`}>
              Move
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            {STATUSES.filter((s) => s.value !== (idea.status ?? 'new')).map((s) => (
              <Menu.Item key={s.value} onClick={() => onMove(s.value)}>
                {s.label}
              </Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      </Group>
    </Card>
  );
}
