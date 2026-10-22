// The story budget as a board: a column per status of the newsroom workflow,
// a card per story. Each column is its own page of the story list — the stories
// in the making by priority and deadline, the published ones most recently
// changed first — with its true count, and "Show more" while it has more, so a
// story is never dropped from the board without a word. Drag a card to another
// column to move it (@hello-pangea/dnd, its <style> carrying the page's CSP
// nonce), or use the card's "Move" menu — the same move, for a keyboard or a
// single pointer. A move the workflow does not allow from where the story
// stands is refused here before anything is sent; one that needs a word from
// the person (an assignee, a reason, a time, a note) or that publishes asks
// first; and the platform has the last say.
import { DragDropContext, Draggable, Droppable, type DropResult } from '@hello-pangea/dnd';
import { ActionIcon, Alert, Anchor, Badge, Button, Card, Group, Loader, Menu, Paper, ScrollArea, Stack, Text, useMantineStyleNonce } from '@mantine/core';
import { useQueries } from '@tanstack/react-query';
import type { Story, StoryStatus } from '@zer0/api';
import { useState } from 'react';

import { errorText } from '../call';
import { useApi } from '../context';
import { MoveDialog } from './MoveDialog';
import { IN_PROGRESS, moveLabel, needOf, PRIORITIES, PUBLISHED, STATUSES, statusOf, storiesQuery, useMove, when, type StoriesQuery } from './shared';

const PAGE = 50;
const MOST = 200; // the platform's largest page

/** Where a drop on the board asks a story to go, if anywhere. */
export function dropTarget(result: Pick<DropResult, 'draggableId' | 'destination'>, stories: Story[]) {
  const story = stories.find((s) => s.id === result.draggableId);
  const to = STATUSES.find((s) => s.value === result.destination?.droppableId)?.value;
  return story && to && to !== story.status ? { story, to } : null;
}

export function Board({ query, onOpen }: { query: StoriesQuery; onOpen: (id: string) => void }) {
  const api = useApi();
  const move = useMove();
  const nonce = useMantineStyleNonce()?.();
  const [sizes, setSizes] = useState<Partial<Record<StoryStatus, number>>>({});
  const [asking, setAsking] = useState<{ story: Story; to: StoryStatus } | null>(null);
  const [refused, setRefused] = useState('');
  const columns = useQueries({
    queries: STATUSES.map((s) =>
      storiesQuery(api, { ...query, status: [s.value], ...(PUBLISHED.includes(s.value) ? { ordering: '-updated_at' } : {}) }, sizes[s.value] ?? PAGE),
    ),
  });
  const failed = columns.find((c) => c.isError);
  const all = columns.flatMap((c) => c.data?.results ?? []);

  const request = (story: Story, to: StoryStatus) => {
    setRefused('');
    move.reset();
    if (!story.moves.includes(to)) {
      const allowed = story.moves.map((m) => statusOf(m).label.toLowerCase()).join(' or ') || 'nowhere';
      setRefused(`“${story.headline}” moves from ${statusOf(story.status).label.toLowerCase()} to ${allowed}, not to ${statusOf(to).label.toLowerCase()}.`);
    } else if (needOf(story.status, to)) {
      setAsking({ story, to });
    } else {
      move.mutate({ story: story.id, body: { status: to } });
    }
  };
  const onDragEnd = (result: DropResult) => {
    const target = dropTarget(result, all);
    if (target) request(target.story, target.to);
  };

  return (
    <Stack>
      {failed?.error ? <Alert color="red">{errorText(failed.error)}</Alert> : null}
      {refused ? <Alert color="orange">{refused}</Alert> : null}
      {move.error ? <Alert color="red">{errorText(move.error)}</Alert> : null}
      <ScrollArea type="auto" offsetScrollbars>
        <DragDropContext onDragEnd={onDragEnd} nonce={nonce}>
          <Group align="flex-start" wrap="nowrap" gap="sm">
            {STATUSES.map((status, at) => {
              const page = columns[at]?.data;
              const column = (page?.results ?? []).filter((s) => s.status === status.value);
              const size = sizes[status.value] ?? PAGE;
              const more = (page?.count ?? 0) - column.length;
              return (
                <Droppable key={status.value} droppableId={status.value}>
                  {(drop) => (
                    <Paper ref={drop.innerRef} {...drop.droppableProps} withBorder p="xs" w={230} miw={230} mih={240} aria-label={`${status.label} column`}>
                      <Group justify="space-between" mb="xs">
                        <Text fw={600}>{status.label}</Text>
                        {page ? (
                          <Badge size="sm" variant="light" color={status.color}>
                            {page.count}
                          </Badge>
                        ) : (
                          <Loader size="xs" />
                        )}
                      </Group>
                      <Stack gap="xs">
                        {column.map((story, index) => (
                          <Draggable key={story.id} draggableId={story.id} index={index}>
                            {(drag) => (
                              <Card ref={drag.innerRef} {...drag.draggableProps} {...drag.dragHandleProps} withBorder padding="xs">
                                <StoryCard story={story} onOpen={onOpen} onMove={request} />
                              </Card>
                            )}
                          </Draggable>
                        ))}
                        {drop.placeholder}
                        {more > 0 ? (
                          <Stack gap={2}>
                            <Text size="xs" c="dimmed">
                              {more} more not shown{size >= MOST ? ' — pick a desk to narrow the board' : ''}
                            </Text>
                            {size < MOST ? (
                              <Button size="compact-xs" variant="subtle" onClick={() => setSizes({ ...sizes, [status.value]: Math.min(size + PAGE, MOST) })}>
                                Show more
                              </Button>
                            ) : null}
                          </Stack>
                        ) : null}
                      </Stack>
                    </Paper>
                  )}
                </Droppable>
              );
            })}
          </Group>
        </DragDropContext>
      </ScrollArea>
      {asking ? <MoveDialog story={asking.story} to={asking.to} onClose={() => setAsking(null)} /> : null}
    </Stack>
  );
}

function StoryCard({ story, onOpen, onMove }: { story: Story; onOpen: (id: string) => void; onMove: (story: Story, to: StoryStatus) => void }) {
  const late = !!story.deadline && new Date(story.deadline) < new Date() && IN_PROGRESS.includes(story.status);
  return (
    <Stack gap={4}>
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Anchor component="button" type="button" ta="left" fw={500} size="sm" onClick={() => onOpen(story.id)}>
          {story.headline}
        </Anchor>
        <Menu position="bottom-end" withinPortal>
          <Menu.Target>
            <ActionIcon variant="subtle" size="sm" aria-label={`Move “${story.headline}”`}>
              ⋯
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Label>Move</Menu.Label>
            {story.moves.map((to) => (
              <Menu.Item key={to} onClick={() => onMove(story, to)}>
                {moveLabel(story.status, to)}
              </Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      </Group>
      <Group gap={4}>
        {story.priority && story.priority < 3 ? (
          <Badge size="xs" color={story.priority === 1 ? 'red' : 'orange'}>
            {PRIORITIES.find((p) => p.value === String(story.priority))?.label}
          </Badge>
        ) : null}
        {story.breaking ? (
          <Badge size="xs" color="red" variant="filled">
            Breaking
          </Badge>
        ) : null}
        {story.embargo ? (
          <Badge size="xs" variant="outline" title={`Embargoed until ${when(story.embargo)}`}>
            Embargo
          </Badge>
        ) : null}
      </Group>
      <Text size="xs" c="dimmed">
        {story.assignee ? story.assignee.name : 'Unassigned'}
        {story.deadline ? ` · due ${when(story.deadline)}` : ''}
      </Text>
      {late ? (
        <Text size="xs" c="red">
          Past its deadline
        </Text>
      ) : null}
    </Stack>
  );
}
