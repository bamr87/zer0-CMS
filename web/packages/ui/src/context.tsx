// The host contract of @zer0/ui. Everything a workspace needs from the page
// it runs in — the API client, a way to follow a server-sent event stream,
// and navigation — comes through <StudioProvider>. The studio supplies a
// session client, EventSource and React Router; the extension's webviews
// (PLAN G10) supply a postMessage client and their own panels. Nothing in
// this package reads a URL, a cookie, storage or a global (eslint.config.js).
import type { ApiClient } from '@zer0/api';
import { createContext, use, type ReactNode } from 'react';

/** A section of the AI area (G8; automations, G16). */
export type AiSection = 'runs' | 'assistants' | 'pipelines' | 'schemas' | 'conversations' | 'providers' | 'models' | 'automations';
/** A tab of the Distribution area (G5). */
export type DistributionTab = 'queue' | 'channels' | 'ledger' | 'statistics';

/** A tab of the Outbox desk (ADR 0007): the belt, arena trials, the claim desk. */
export type OutboxTab = 'belt' | 'trials' | 'claims';

/** Where a workspace asks to go; the host maps it to a route or a panel. */
export type Destination =
  | { to: 'page'; id: number; tab?: 'suggestions' }
  | { to: 'pages' }
  | { to: 'create' }
  | { to: 'run'; id: number }
  | { to: 'review'; runId?: number }
  // The AI content layer (G8); a row without an id is a new one.
  | { to: 'ai'; section?: AiSection }
  | { to: 'assistant' | 'pipeline' | 'schema' | 'brief'; id?: string }
  | { to: 'briefs' }
  | { to: 'conversation'; id: string }
  | { to: 'ideas' }
  | { to: 'research' }
  | { to: 'source'; id: string }
  | { to: 'newsroom' }
  | { to: 'story'; id: string }
  | { to: 'books' }
  | { to: 'book'; id: number }
  | { to: 'chapter'; book: number; id: number }
  // The outbox desk; a trial and a claim check each have an address.
  | { to: 'outbox'; tab?: OutboxTab }
  | { to: 'trial'; id: string }
  | { to: 'claim-check'; id: string }
  // Sites and their jobs (G4).
  | { to: 'sites' }
  | { to: 'site'; id: number }
  | { to: 'job'; id: string }
  // Distribution (G5): the area, a post of the queue, a channel.
  | { to: 'distribution'; tab?: DistributionTab }
  | { to: 'distribution-post'; id: string }
  | { to: 'channel'; id: string }
  // Automations (G16), under the AI area; one without an id is a new one.
  | { to: 'automation'; id?: string };

/**
 * Follow a server-sent event stream's named events; returns what closes it.
 * A host relays a stream it can no longer follow (refused, or not a stream)
 * as the event `error`, so the component decides when to try again.
 */
export type OpenStream = (
  path: string,
  events: readonly string[],
  onEvent: (event: string, data: unknown) => void,
) => () => void;

export interface Host {
  api: ApiClient;
  stream: OpenStream;
  go: (to: Destination) => void;
}

const HostContext = createContext<Host | null>(null);

export function StudioProvider({ api, stream, go, children }: Host & { children: ReactNode }) {
  return <HostContext value={{ api, stream, go }}>{children}</HostContext>;
}

function useHost(): Host {
  const host = use(HostContext);
  if (!host) throw new Error('@zer0/ui components render inside a <StudioProvider>');
  return host;
}

export const useApi = () => useHost().api;
export const useStream = () => useHost().stream;
export const useGo = () => useHost().go;
