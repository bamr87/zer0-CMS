// Following what the platform does in the background: an agent run until it is
// final, and the JSON shapes research rows carry (a run's output, a source's
// entities and suggested quotes), read defensively — they are data from a
// model, checked by the platform but typed here only as `unknown`.
import { useQuery } from '@tanstack/react-query';

import { call } from '../call';
import { useApi } from '../context';

/** An agent run, read again every 1.5 s until it is final. */
export function useRun(runId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ['run', runId],
    enabled: runId !== null,
    queryFn: () => call(api.GET('/api/v2/agent-runs/{public_id}/', { params: { path: { public_id: runId ?? '' } } })),
    refetchInterval: (query) => (query.state.data?.is_final ? false : 1500),
  });
}

export function field(value: unknown, key: string): unknown {
  return typeof value === 'object' && value !== null && key in value ? (value as Record<string, unknown>)[key] : undefined;
}

export function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

export interface Entity {
  name: string;
  kind: string;
}

export function entities(value: unknown): Entity[] {
  return Array.isArray(value)
    ? value.filter((e): e is Entity => typeof field(e, 'name') === 'string').map((e) => ({ name: e.name, kind: String(e.kind ?? '') }))
    : [];
}

/** Still being fetched or answered: worth asking again. */
export const WAITING = new Set(['pending', 'fetching', 'queued', 'running']);
