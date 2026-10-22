// The run timeline grows live: a running run's steps arrive over the host's
// event stream (here a fake, as the extension's webviews will supply their
// own), and a finished run opens no stream at all. A stream that ends on a
// final status is not opened again; one that timed out on a live run is,
// after a pause; one the host could not follow is, after a pause that grows.
import { act, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { RunTimeline, type OpenStream } from '../src';
import { fakePlatform, renderUi } from '../../../test/harness';

const FINAL = ['succeeded', 'failed', 'refused', 'cancelled'];

const run = (status: string, steps: unknown[] = []) => ({
  id: 9,
  agent: 'seo',
  status,
  is_final: FINAL.includes(status),
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

describe('<RunTimeline> following a run', () => {
  afterEach(() => vi.useRealTimers());

  /** A host stream that records each opening and lets the test send events on the newest. */
  function recordingStream() {
    const sends: ((event: string, data: unknown) => void)[] = [];
    const stream = vi.fn<OpenStream>((_path, _events, onEvent) => {
      sends.push(onEvent);
      return () => undefined;
    });
    const send = (event: string, data: unknown = {}) => act(() => sends.at(-1)?.(event, data));
    return { stream, send };
  }

  it('stops at a final status: the run is read again and no stream is opened after it', async () => {
    let status = 'running';
    const { api, calls } = fakePlatform({ 'GET /api/v2/agent-runs/9/': () => run(status) });
    const { stream, send } = recordingStream();
    renderUi(<RunTimeline runId={9} />, { api, stream });
    await waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
    status = 'succeeded';
    send('status', { id: 9, status: 'succeeded', is_final: true, error: '' });
    send('end');
    expect(await screen.findByText('succeeded')).toBeInTheDocument();
    expect(calls.filter((c) => c.path === '/api/v2/agent-runs/9/')).toHaveLength(2);
    await new Promise((resolve) => setTimeout(resolve, 1200));
    expect(stream).toHaveBeenCalledTimes(1);
  });

  it('follows a live run again after its stream timed out, and backs off from a stream that broke', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { api } = fakePlatform({ 'GET /api/v2/agent-runs/9/': () => run('running') });
    const { stream, send } = recordingStream();
    renderUi(<RunTimeline runId={9} />, { api, stream });
    await vi.waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
    send('status', { id: 9, status: 'running', is_final: false, error: '' });
    send('end'); // the server's time limit, on a run that is still working
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(stream).toHaveBeenCalledTimes(1); // not at once: after a pause
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(stream).toHaveBeenCalledTimes(2);
    send('error'); // the host could not follow it: wait 1 s, then 2 s, then 4 s …
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(stream).toHaveBeenCalledTimes(3);
    send('error');
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(stream).toHaveBeenCalledTimes(3);
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(stream).toHaveBeenCalledTimes(4);
  });
});
