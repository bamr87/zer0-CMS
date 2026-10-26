// The Books workspace's names for the shapes /api/v2/books/ returns, from the
// generated client (schemas/openapi/openapi.json), and one way to follow a run
// to its end: its detail, read again every second until it is final.
import { useQuery } from '@tanstack/react-query';
import type { components } from '@zer0/api';

import { call } from '../call';
import { useApi } from '../context';

type Schemas = components['schemas'];
export type BookSummary = Schemas['BookSummary'];
export type BookDetail = Schemas['BookDetail'];
export type BookChapter = Schemas['BookChapter'];
export type BookIssue = Schemas['BookIssue'];
export type BookTask = Schemas['BookTask'];
export type BookTaskKey = Schemas['BookTaskEnum'];

export interface Finding {
  severity: string;
  kind: string;
  quote: string;
  problem: string;
  suggestion: string;
}

/** What a book task's run leaves in its output (books/handlers.py). */
export interface TaskOutput {
  task?: BookTaskKey;
  markdown?: string;
  json?: { findings?: Finding[]; summary?: string } & Record<string, unknown>;
  suggestions?: number[];
}

export function useFollowRun(runId: number | null) {
  const api = useApi();
  return useQuery({
    queryKey: ['run', runId],
    enabled: runId !== null,
    queryFn: () => call(api.GET('/api/v2/agent-runs/{id}/', { params: { path: { id: runId ?? 0 } } })),
    refetchInterval: (query) => (query.state.data?.is_final ? false : 1000),
  });
}
