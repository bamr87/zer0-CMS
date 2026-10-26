// The story budget as a board: a column per status of the newsroom workflow,
// a card per story. Each column is its own page of the story list — the stories
// in the making by priority and deadline, the published ones most recently
// changed first — with its true count, and "Show more" while it has more, so a
// story is never dropped from the board without a word. Drag a card to another
// column to move it (@dnd-kit, the library the pipelines' steps use too), or
// use the card's "Move" menu — the same move, for a keyboard or a single
// pointer. A move the workflow does not allow from where the story
// stands is refused here before anything is sent; one that needs a word from
// the person (an assignee, a reason, a time, a note) or that publishes asks
// first; and the platform has the last say.
import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import { ActionIcon, Alert, Anchor, Badge, Button, Card, Group, Loader, Menu, Paper, ScrollArea, Stack, Text } from '@mantine/core';
import { useQueries } from '@tanstack/react-query';
import type { Story, StoryStatus } from '@zer0/api';
import { useState, type ReactNode } from 'react';

import { errorText } from '../call';
import { useApi } from '../context';
import { MoveDialog } from './MoveDialog';
import { IN_PROGRESS, moveLabel, needOf, PRIORITIES, PUBLISHED, STATUSES, statusOf, storiesQuery, useMove, when, type StoriesQuery } from './shared';

const PAGE = 50;
const MOST = 200; // the platform's largest page

/** Where a drop on the board asks a story to go, if anywhere: the card dropped, and the column under it. */
export function dropTarget(drop: { story: string; column: string | null }, stories: Story[]) {
  const story = stories.find((s) => s.id === drop.story);
  const to = STATUSES.find((s) => s.value === drop.column)?.value;
  return story && to && to !== story.status ? { story, to } : null;
}

/** A column a card can be dropped on. */
function Column({ status, label, children }: { status: StoryStatus; label: string; children: ReactNode }) {
  const { setNodeRef } = useDroppable({ id: status });
  return (
    <Paper ref={setNodeRef} withBorder p="xs" w={230} miw={230} mih={240} aria-label={`${label} column`}>
      {children}
    </Paper>
  );
}

/** A card that can be picked up; a click on its headline or its menu still works (the pointer has to travel first). */
function DraggableCard({ id, children }: { id: string; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id });
  return (
    <Card ref={setNodeRef} {...attributes} {...listeners} withBorder padding="xs" style={{ transform: CSS.Translate.toString(transform), zIndex: isDragging ? 2 : undefined }}>
      {children}
    </Card>
  );
}

export function Board({ query, onOpen }: { query: StoriesQuery; onOpen: (id: string) => void }) {
  const api = useApi();
  const move = useMove();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
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
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    const target = dropTarget({ story: String(active.id), column: over ? String(over.id) : null }, all);
    if (target) request(target.story, target.to);
  };

  return (
    <Stack>
      {failed?.error ? <Alert color="red">{errorText(failed.error)}</Alert> : null}
      {refused ? <Alert color="orange">{refused}</Alert> : null}
      {move.error ? <Alert color="red">{errorText(move.error)}</Alert> : null}
      <ScrollArea type="auto" offsetScrollbars>
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
          <Group align="flex-start" wrap="nowrap" gap="sm">
            {STATUSES.map((status, at) => {
              const page = columns[at]?.data;
              const column = (page?.results ?? []).filter((s) => s.status === status.value);
              const size = sizes[status.value] ?? PAGE;
              const more = (page?.count ?? 0) - column.length;
              return (
                <Column key={status.value} status={status.value} label={status.label}>
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
                        {column.map((story) => (
                          <DraggableCard key={story.id} id={story.id}>
                            <StoryCard story={story} onOpen={onOpen} onMove={request} />
                          </DraggableCard>
                        ))}
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
                </Column>
              );
            })}
          </Group>
        </DndContext>
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
