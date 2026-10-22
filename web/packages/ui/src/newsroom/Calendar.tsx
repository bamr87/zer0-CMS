// The editorial calendar: a month of the budget by slot date — what runs which
// day, and where each story stands — a week to a row, Monday first. It is the
// story list's slot-date filter laid out as a month; a story opens its panel.
import { Alert, Anchor, Badge, Button, Group, Loader, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import type { Story } from '@zer0/api';
import { useState } from 'react';

import { errorText } from '../call';
import { statusOf, useStories, type StoriesQuery } from './shared';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const pad = (n: number) => String(n).padStart(2, '0');
export const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** The days a month's grid shows: whole weeks, Monday first. */
export function monthGrid(month: Date): Date[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const start = new Date(first);
  start.setDate(1 - ((first.getDay() + 6) % 7));
  const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  const days: Date[] = [];
  for (const d = new Date(start); d <= last || days.length % 7 !== 0; d.setDate(d.getDate() + 1)) days.push(new Date(d));
  return days;
}

export function Calendar({ query, onOpen, today = new Date() }: { query: StoriesQuery; onOpen: (id: string) => void; today?: Date }) {
  const [month, setMonth] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const days = monthGrid(month);
  const range = { slot_after: isoDay(days[0] ?? month), slot_before: isoDay(days[days.length - 1] ?? month) };
  const stories = useStories({ ...query, ...range });
  const byDay = new Map<string, Story[]>();
  for (const story of stories.data?.results ?? []) {
    if (story.slot_date) byDay.set(story.slot_date, [...(byDay.get(story.slot_date) ?? []), story]);
  }
  const shift = (by: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + by, 1));

  return (
    <Stack>
      <Group justify="space-between">
        <Button variant="default" size="xs" onClick={() => shift(-1)}>
          Previous month
        </Button>
        <Title order={4}>{month.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}</Title>
        <Button variant="default" size="xs" onClick={() => shift(1)}>
          Next month
        </Button>
      </Group>
      {stories.isPending ? <Loader size="sm" /> : stories.isError ? <Alert color="red">{errorText(stories.error)}</Alert> : null}
      <SimpleGrid cols={7} spacing={4} verticalSpacing={4}>
        {WEEKDAYS.map((day) => (
          <Text key={day} size="xs" fw={600} c="dimmed" ta="center">
            {day}
          </Text>
        ))}
        {days.map((day) => {
          const key = isoDay(day);
          return (
            <Paper key={key} withBorder p={4} mih={90} aria-label={key} opacity={day.getMonth() === month.getMonth() ? 1 : 0.5}>
              <Text size="xs" fw={key === isoDay(today) ? 700 : 400}>
                {day.getDate()}
              </Text>
              <Stack gap={2}>
                {(byDay.get(key) ?? []).map((story) => (
                  <Group key={story.id} gap={4} wrap="nowrap">
                    <Badge size="xs" circle color={statusOf(story.status).color} title={statusOf(story.status).label}>
                      {' '}
                    </Badge>
                    <Anchor component="button" type="button" size="xs" ta="left" lineClamp={2} onClick={() => onOpen(story.id)}>
                      {story.headline}
                    </Anchor>
                  </Group>
                ))}
              </Stack>
            </Paper>
          );
        })}
      </SimpleGrid>
    </Stack>
  );
}
