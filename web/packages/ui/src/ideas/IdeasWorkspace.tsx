// Ideas: the boards and the inbox (ideas on no board), a board's ideas in
// columns by status with their votes, capture, a brainstorm session, the
// clusters and likely duplicates found by meaning, and one idea in a drawer —
// edit, link research, promote. Every change goes through /api/v2/ideas/.
import { Alert, Anchor, Badge, Button, Card, Group, Loader, Menu, NavLink, SegmentedControl, SimpleGrid, Stack, Text, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Idea, IdeaStatus } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';
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
  const [name, setName] = useState('');
  const boards = useQuery({
    queryKey: ['boards', siteId],
    queryFn: () => call(api.GET('/api/v2/ideas/boards/', { params: { query: { site: siteId, page_size: 200 } } })),
  });
  const query = { board, site: siteId, page_size: 200, ordering: '-vote_count' };
  const ideas = useQuery({ queryKey: ['ideas', query], queryFn: () => call(api.GET('/api/v2/ideas/', { params: { query } })) });
  const refresh = () => void qc.invalidateQueries({ queryKey: ['ideas'] });
  const addBoard = useMutation({
    mutationFn: () => call(api.POST('/api/v2/ideas/boards/', { body: { name } })),
    onSuccess: (made) => {
      setName('');
      setBoard(made.id);
      void qc.invalidateQueries({ queryKey: ['boards'] });
    },
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
  const failure = vote.error ?? move.error ?? addBoard.error;

  return (
    <Group align="start" wrap="nowrap" gap="lg">
      <Stack w={220} gap={4} aria-label="Boards">
        <NavLink component="button" label="Inbox" description="Ideas on no board" active={board === INBOX} onClick={() => setBoard(INBOX)} />
        {boardList.map((b) => (
          <NavLink component="button" key={b.id} label={b.name} active={board === b.id} onClick={() => setBoard(b.id)} />
        ))}
        <Group gap={4} mt="xs" wrap="nowrap">
          <TextInput size="xs" placeholder="New board" aria-label="New board" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <Button size="xs" variant="light" disabled={!name.trim()} loading={addBoard.isPending} onClick={() => addBoard.mutate()}>
            Add
          </Button>
        </Group>
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
