// The studio's half of the host contract (@zer0/ui's StudioProvider): the
// same-origin session client, and EventSource for a run's server-sent events.
// The extension's webviews supply their own two (PLAN G10).
import { createSessionClient } from '@zer0/api';
import type { OpenStream } from '@zer0/ui';

export const api = createSessionClient();

function parse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text; // a stream may send plain text; pass it on as it came
  }
}

export const openStream: OpenStream = (path, events, onEvent) => {
  const source = new EventSource(path, { withCredentials: true });
  const relay = (event: MessageEvent<string>) => {
    onEvent(event.type, parse(event.data));
    if (event.type === 'end') source.close();
  };
  for (const name of events) source.addEventListener(name, relay);
  // The browser reconnects by itself after a dropped connection; a response it
  // cannot use (an error status, a page instead of a stream) closes the source
  // for good, which the component hears as `error`.
  source.addEventListener('error', () => {
    if (source.readyState === EventSource.CLOSED) onEvent('error', null);
  });
  return () => source.close();
};
