// What the newsroom's parts share: the workflow's statuses in board order with
// their labels and colours, what a move asks of a person before it is sent,
// the priorities, and the queries and the move every view uses — one cache key
// (['newsroom', …]) so a move anywhere refreshes the board, the calendar, the
// assignments and the story's panel together. A list says how many it did not
// show (`count`) rather than dropping them; the published-story picker loads
// the newest first and searches the platform as the person types.
import { useDebouncedValue } from '@mantine/hooks';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ApiClient, components, StoryStatus } from '@zer0/api';
import { useState } from 'react';

import { call } from '../call';
import { useApi } from '../context';

interface StatusInfo {
  value: StoryStatus;
  label: string;
  color: string;
}

const PITCH: StatusInfo = { value: 'pitch', label: 'Pitch', color: 'gray' };

export const STATUSES: StatusInfo[] = [
  PITCH,
  { value: 'assigned', label: 'Assigned', color: 'indigo' },
  { value: 'drafting', label: 'Drafting', color: 'blue' },
  { value: 'editing', label: 'Editing', color: 'cyan' },
  { value: 'copy', label: 'Copy', color: 'teal' },
  { value: 'scheduled', label: 'Scheduled', color: 'yellow' },
  { value: 'published', label: 'Published', color: 'green' },
  { value: 'updated', label: 'Updated', color: 'lime' },
  { value: 'corrected', label: 'Corrected', color: 'orange' },
];

export const statusOf = (value: string) => STATUSES.find((s) => s.value === value) ?? PITCH;

/** The statuses of a story still being made: the ones a deadline and an assignment are about. */
export const IN_PROGRESS: StoryStatus[] = ['pitch', 'assigned', 'drafting', 'editing', 'copy'];
export const PUBLISHED: StoryStatus[] = ['published', 'updated', 'corrected'];

export const PRIORITIES = [
  { value: '1', label: 'Top' },
  { value: '2', label: 'High' },
  { value: '3', label: 'Normal' },
  { value: '4', label: 'Low' },
];

/** What a move needs from a person before it is sent, if anything: going live always asks first. */
export type Need = 'assignee' | 'comment' | 'when' | 'reason' | 'note' | 'confirm';

export function needOf(from: StoryStatus, to: StoryStatus): Need | null {
  if (to === 'assigned') return 'assignee';
  if (to === 'drafting' && (from === 'editing' || from === 'copy')) return 'comment';
  if (to === 'scheduled') return 'when';
  if (to === 'published') return from === 'editing' ? 'reason' : 'confirm';
  if (to === 'updated' || to === 'corrected') return 'note';
  return null;
}

export const moveLabel = (from: StoryStatus, to: StoryStatus) =>
  to === 'drafting' && (from === 'editing' || from === 'copy')
    ? 'Send back'
    : to === 'published'
      ? from === 'editing'
        ? 'Breaking: publish now'
        : 'Publish now'
      : to === 'corrected'
        ? 'Add a correction'
        : to === 'updated'
          ? 'Add an update'
          : `To ${statusOf(to).label.toLowerCase()}`;

export interface StoriesQuery {
  desk?: string;
  site?: number;
  status?: StoryStatus[];
  assignee?: string;
  my_desks?: boolean;
  slot_after?: string;
  slot_before?: string;
  ordering?: string;
  q?: string;
}

/** One page of stories, `size` long (the platform's most is 200): a query for useQuery or useQueries. */
export function storiesQuery(api: ApiClient, query: StoriesQuery, size = 200) {
  const params = { ...query, page_size: size };
  return {
    queryKey: ['newsroom', 'stories', params],
    queryFn: () => call(api.GET('/api/v2/newsroom/stories/', { params: { query: params } })),
  };
}

export function useStories(query: StoriesQuery, enabled = true) {
  const api = useApi();
  return useQuery({ ...storiesQuery(api, query), enabled });
}

/** "Showing n of N" when a list has more than it shows, else nothing. */
export const shownOf = (data: { count: number; results: unknown[] } | undefined) =>
  data && data.count > data.results.length ? `Showing ${data.results.length} of ${data.count}` : '';

/**
 * A site's published stories to pick from — for a front's slot or an issue — the most recently published
 * first, searched on the platform by headline as the person types. Spread it onto a Mantine Select or
 * MultiSelect, which keeps the label of what is picked when a later search no longer lists it.
 */
export function usePublishedPicker(siteId: number) {
  const api = useApi();
  const [searchValue, onSearchChange] = useState('');
  const [q] = useDebouncedValue(searchValue.trim(), 250);
  const found = useQuery({
    ...storiesQuery(api, { site: siteId, status: PUBLISHED, ordering: '-page__first_published_at', q: q || undefined }, 50),
    placeholderData: keepPreviousData,
  });
  const data = (found.data?.results ?? []).map((s) => ({ value: s.id, label: s.headline ?? '' }));
  return { data, searchable: true, searchValue, onSearchChange };
}

export function useDesks(siteId?: number) {
  const api = useApi();
  return useQuery({
    queryKey: ['newsroom', 'desks', siteId ?? null],
    queryFn: () => call(api.GET('/api/v2/newsroom/desks/', { params: { query: { site: siteId, page_size: 200 } } })),
  });
}

export type MoveBody = components['schemas']['MoveRequest'];

export function useMove() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ story, body }: { story: string; body: MoveBody }) =>
      call(api.POST('/api/v2/newsroom/stories/{public_id}/move/', { params: { path: { public_id: story } }, body })),
    onSettled: () => qc.invalidateQueries({ queryKey: ['newsroom'] }),
  });
}

export const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : '—');
