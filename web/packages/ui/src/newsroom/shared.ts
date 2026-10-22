// What the newsroom's parts share: the workflow's statuses in board order with
// their labels and colours, what a move asks of a person before it is sent,
// the priorities, and the queries and the move every view uses — one cache key
// (['newsroom', …]) so a move anywhere refreshes the board, the calendar, the
// assignments and the story's panel together.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components, StoryStatus } from '@zer0/api';

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

/** What a move needs from a person before it is sent, if anything. */
export type Need = 'assignee' | 'comment' | 'when' | 'reason' | 'note';

export function needOf(from: StoryStatus, to: StoryStatus): Need | null {
  if (to === 'assigned') return 'assignee';
  if (to === 'drafting' && (from === 'editing' || from === 'copy')) return 'comment';
  if (to === 'scheduled') return 'when';
  if (to === 'published' && from === 'editing') return 'reason';
  if (to === 'updated' || to === 'corrected') return 'note';
  return null;
}

export const moveLabel = (from: StoryStatus, to: StoryStatus) =>
  to === 'drafting' && (from === 'editing' || from === 'copy')
    ? 'Send back'
    : to === 'published' && from === 'editing'
      ? 'Breaking: publish now'
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
}

export function useStories(query: StoriesQuery, enabled = true) {
  const api = useApi();
  const params = { ...query, page_size: 200 };
  return useQuery({
    queryKey: ['newsroom', 'stories', params],
    queryFn: () => call(api.GET('/api/v2/newsroom/stories/', { params: { query: params } })),
    enabled,
  });
}

export function useDesks(siteId?: number) {
  const api = useApi();
  return useQuery({
    queryKey: ['newsroom', 'desks', siteId ?? null],
    queryFn: () => call(api.GET('/api/v2/newsroom/desks/', { params: { query: { site: siteId, page_size: 200 } } })),
  });
}

export type MoveBody = components['schemas']['Move'];

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
