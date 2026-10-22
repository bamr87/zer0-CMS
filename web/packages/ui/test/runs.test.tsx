// The run timeline grows live: a running run's steps arrive over the host's
// event stream (here a fake, as the extension's webviews will supply their
// own), and a finished run opens no stream at all.
import { act, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { RunTimeline, type OpenStream } from '../src';
import { fakePlatform, renderUi } from '../../../test/harness';

const run = (status: string, steps: unknown[] = []) => ({
  id: 9,
  agent: 'seo',
  status,
  trigger: 'rest',
  target: { type: 'articlepage', id: 5 },
  input: {},
  output: status === 'succeeded' ? { note: 'Two suggestions.' } : {},
  error: '',
  cost_usd: '0.000000',
  tokens: 120,
  trace_id: '',
  schema_version: '1',
  created_at: '2026-10-21T09:00:00Z',
  finished_at: null,
  links: { self: '/api/v2/agent-runs/9/', stream: '/api/v2/agent-runs/9/stream/' },
  steps,
});

const step = (idx: number, name: string) => ({ idx, kind: 'tool', name, args: {}, result: {}, error: '', latency_ms: 12, tokens: 0 });

describe('<RunTimeline>', () => {
  it('adds steps as the stream delivers them', async () => {
    let send: (event: string, data: unknown) => void = () => undefined;
    const stream = vi.fn<OpenStream>((_path, _events, onEvent) => {
      send = onEvent;
      return () => undefined;
    });
    const { api } = fakePlatform({ 'GET /api/v2/agent-runs/9/': () => run('running', [step(0, 'content.get_page')]) });
    renderUi(<RunTimeline runId={9} />, { api, stream });
    expect(await screen.findByText('tool · content.get_page')).toBeInTheDocument();
    expect(stream).toHaveBeenCalledWith('/api/v2/agent-runs/9/stream/', ['step', 'status', 'end'], expect.any(Function));
    act(() => send('step', step(1, 'content.propose_edit')));
    expect(await screen.findByText('tool · content.propose_edit')).toBeInTheDocument();
  });

  it('opens no stream for a finished run, and links to its suggestions', async () => {
    const stream = vi.fn<OpenStream>(() => () => undefined);
    const { go } = renderUi(<RunTimeline runId={9} />, {
      api: fakePlatform({ 'GET /api/v2/agent-runs/9/': () => run('succeeded', [step(0, 'content.propose_edit')]) }).api,
      stream,
    });
    expect(await screen.findByText('Two suggestions.')).toBeInTheDocument();
    expect(stream).not.toHaveBeenCalled();
    act(() => screen.getByRole('button', { name: 'Review its suggestions' }).click());
    expect(go).toHaveBeenCalledWith({ to: 'review', runId: 9 });
  });
});
