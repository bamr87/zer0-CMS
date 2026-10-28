// Fixtures for the AI workspaces' tests: rows as /api/v2/ai/ sends them, an
// agent run as /api/v2/agent-runs/<id>/ sends it, the person signed in (with or
// without the permission to configure providers), and a host stream the test
// drives — the run's events arrive when the test sends them, as the platform's
// server-sent events would. Nothing reaches a network or a model. A run is
// named by its public id, a UUID (`RUN`, and `OTHER_RUN` for a second one).
import { act } from '@testing-library/react';
import type { OpenStream } from '@zer0/ui';
import { vi } from 'vitest';

export const EMPTY = { count: 0, next: null, previous: null, results: [] };
export const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

const OWNED = { owner: 'editor', site: null, visibility: 'private', can_edit: true, created_at: '2026-10-22T09:00:00Z', updated_at: '2026-10-22T09:00:00Z' };

export const me = (permissions: string[] = [], staff = false) => ({
  authenticated: true,
  user: { id: 1, username: 'editor', name: 'Demo Editor', email: 'editor@example.com', is_staff: staff, is_superuser: false },
  permissions,
  csrf_token: 'x',
});

export const assistant = (overrides: Record<string, unknown> = {}) => ({
  ...OWNED,
  id: 'a1',
  name: 'Headliner',
  description: '',
  instructions: 'Write headlines.',
  prompt_template: '',
  provider: null,
  model: null,
  params: {},
  output_schema: null,
  tools: [],
  effect: 'propose',
  ...overrides,
});

export const schema = (overrides: Record<string, unknown> = {}) => ({
  ...OWNED,
  id: 's1',
  name: 'Story',
  description: '',
  schema: { type: 'object', properties: { headline: { type: 'string' } } },
  version: 1,
  render_template: '## {{ headline }}',
  bundled: false,
  ...overrides,
});

export const RUN = '9b2f6c4e-1d3a-4f5b-8c7d-0e1f2a3b4c5d';
export const OTHER_RUN = '4c7a9e21-8b3d-4e6f-9a1b-2c3d4e5f6a7b';

export const runRef = (id = RUN) => ({ id, status: 'queued', links: { self: `/api/v2/agent-runs/${id}/`, stream: `/api/v2/agent-runs/${id}/stream/` } });

/** An agent run as the runs API sends it. */
export const agentRun = (status: string, output: unknown = {}, id = RUN) => ({
  id,
  agent: 'assistant',
  status,
  is_final: ['succeeded', 'failed', 'refused', 'cancelled'].includes(status),
  trigger: 'rest',
  target: { type: null, id: null },
  input: {},
  output,
  error: status === 'failed' ? 'the provider is down' : '',
  cost_usd: '0.001000',
  tokens: 12,
  trace_id: '',
  schema_version: '1',
  created_at: '2026-10-22T09:00:00Z',
  finished_at: null,
  links: { self: `/api/v2/agent-runs/${id}/`, stream: `/api/v2/agent-runs/${id}/stream/` },
  steps: [],
});

/** A host stream that records what it opened and lets the test send the newest one events. */
export function liveStream() {
  const opened: { path: string; send: (event: string, data: unknown) => void }[] = [];
  const stream = vi.fn<OpenStream>((path, _events, onEvent) => {
    opened.push({ path, send: onEvent });
    return () => undefined;
  });
  /** The run finished: its final status, then the end of the stream. */
  const finish = (status = 'succeeded') =>
    act(() => {
      const last = opened.at(-1);
      last?.send('status', { id: RUN, status, is_final: true, error: '' });
      last?.send('end', {});
    });
  return { stream, opened, finish };
}
