// The story budget as a board: a column per status of the newsroom workflow,
// a card per story. Drag a card to another column to move it (@hello-pangea/dnd,
// its <style> carrying the page's CSP nonce), or use the card's "Move" menu —
// the same move, for a keyboard or a single pointer. A move the workflow does
// not allow from where the story stands is refused here before anything is
// sent; one that needs a word from the person (an assignee, a reason, a time,
// a note) asks for it first; and the platform has the last say.
import { DragDropContext, Draggable, Droppable, type DropResult } from '@hello-pangea/dnd';
import { ActionIcon, Alert, Anchor, Badge, Card, Group, Loader, Menu, Paper, ScrollArea, Stack, Text, useMantineStyleNonce } from '@mantine/core';
import type { Story, StoryStatus } from '@zer0/api';
import { useState } from 'react';

import { errorText } from '../call';
import { MoveDialog } from './MoveDialog';
import { IN_PROGRESS, moveLabel, needOf, PRIORITIES, STATUSES, statusOf, useMove, useStories, when, type StoriesQuery } from './shared';

/** Where a drop on the board asks a story to go, if anywhere. */
export function dropTarget(result: Pick<DropResult, 'draggableId' | 'destination'>, stories: Story[]) {
  const story = stories.find((s) => s.id === result.draggableId);
  const to = STATUSES.find((s) => s.value === result.destination?.droppableId)?.value;
  return story && to && to !== story.status ? { story, to } : null;
}

export function Board({ query, onOpen }: { query: StoriesQuery; onOpen: (id: string) => void }) {
  const stories = useStories(query);
  const move = useMove();
  const nonce = useMantineStyleNonce()?.();
  const [asking, setAsking] = useState<{ story: Story; to: StoryStatus } | null>(null);
  const [refused, setRefused] = useState('');

  if (stories.isPending) return <Loader />;
  if (stories.isError) return <Alert color="red">{errorText(stories.error)}</Alert>;
  const all = stories.data.results;

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
      {refused ? <Alert color="orange">{refused}</Alert> : null}
      {move.error ? <Alert color="red">{errorText(move.error)}</Alert> : null}
      <ScrollArea type="auto" offsetScrollbars>
        <DragDropContext onDragEnd={onDragEnd} nonce={nonce}>
          <Group align="flex-start" wrap="nowrap" gap="sm">
            {STATUSES.map((status) => {
              const column = all.filter((s) => s.status === status.value);
              return (
                <Droppable key={status.value} droppableId={status.value}>
                  {(drop) => (
                    <Paper ref={drop.innerRef} {...drop.droppableProps} withBorder p="xs" w={230} miw={230} mih={240} aria-label={`${status.label} column`}>
                      <Group justify="space-between" mb="xs">
                        <Text fw={600}>{status.label}</Text>
                        <Badge size="sm" variant="light" color={status.color}>
                          {column.length}
                        </Badge>
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
