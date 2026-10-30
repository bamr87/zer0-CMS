// The studio's event-stream transport: named events reach the component with
// their JSON data, `end` closes the source, and a source the browser gave up
// on (a refused or broken response) reaches it as `error` — while a dropped
// connection the browser is already re-opening does not.
import { afterEach, describe, expect, it, vi } from 'vitest';

import { openStream } from '../src/transport';

class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static last: FakeEventSource | undefined;
  readyState = FakeEventSource.OPEN;
  private listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();

  constructor(readonly url: string) {
    FakeEventSource.last = this;
  }

  addEventListener(name: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }

  emit(name: string, data = '') {
    for (const listener of this.listeners.get(name) ?? []) listener(new MessageEvent(name, { data }));
  }
}

describe('openStream', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('relays named events, closes at the end, and reports a stream it can no longer follow', () => {
    vi.stubGlobal('EventSource', FakeEventSource);
    const onEvent = vi.fn();
    openStream('/api/v2/agent-runs/9b2f6c4e-1d3a-4f5b-8c7d-0e1f2a3b4c5d/stream/', ['step', 'end'], onEvent);
    const source = FakeEventSource.last as FakeEventSource;
    source.emit('step', '{"idx": 0}');
    expect(onEvent).toHaveBeenLastCalledWith('step', { idx: 0 });

    source.readyState = FakeEventSource.CONNECTING; // the browser is reconnecting by itself
    source.emit('error');
    expect(onEvent).toHaveBeenCalledTimes(1);
    source.readyState = FakeEventSource.CLOSED; // it gave up: a refused response, or not a stream
    source.emit('error');
    expect(onEvent).toHaveBeenLastCalledWith('error', null);

    openStream('/api/v2/agent-runs/9b2f6c4e-1d3a-4f5b-8c7d-0e1f2a3b4c5d/stream/', ['end'], onEvent);
    (FakeEventSource.last as FakeEventSource).emit('end', '{}');
    expect(FakeEventSource.last?.readyState).toBe(FakeEventSource.CLOSED);
  });
});
