// The host contract of @zer0/ui. Everything a workspace needs from the page
// it runs in — the API client, a way to follow a server-sent event stream,
// navigation, (where there is a browser session) signing in, and (where the
// page cannot save a file itself) saving one — comes through <StudioProvider>. The studio supplies a
// session client, EventSource and React Router; the extension's webviews
// (PLAN G10) supply a postMessage client and their own panels. Nothing in
// this package reads a URL, a cookie, storage or a global (eslint.config.js).
import type { ApiClient } from '@zer0/api';
import { createContext, use, type ReactNode } from 'react';

import type { AuthHost } from './account/allauth';

/** A section of the AI area (G8; automations, G16). */
export type AiSection = 'runs' | 'assistants' | 'pipelines' | 'schemas' | 'conversations' | 'providers' | 'models' | 'automations';
/** A tab of the Distribution area (G5). */
export type DistributionTab = 'queue' | 'channels' | 'ledger' | 'statistics';

/** A tab of the Outbox desk (ADR 0007): the belt, arena trials, the claim desk. */
export type OutboxTab = 'belt' | 'trials' | 'claims';

/** A section of the AIEO workspace (G7). */
export type AieoSection = 'audit' | 'optimize' | 'patterns' | 'agents' | 'citations' | 'connectors' | 'priorities' | 'reports' | 'context';

/** Where a workspace asks to go; the host maps it to a route or a panel. */
export type Destination =
  | { to: 'page'; id: number; tab?: 'suggestions' }
  | { to: 'pages' }
  | { to: 'create' }
  | { to: 'run'; id: string }
  | { to: 'review'; runId?: string }
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
  | { to: 'automation'; id?: string }
  // The AIEO workspace (G7), under Sites.
  | { to: 'aieo'; section?: AieoSection }
  // The person's account (G3): security, sessions, API tokens.
  | { to: 'account'; section?: AccountSection };

/** A section of the account menu (G3). */
export type AccountSection = 'security' | 'sessions' | 'tokens';

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

/**
 * A file a workspace offers to save, as a host that saves files itself is
 * asked for it: the GET path under `/api/v2/` that answers it, the JSON field
 * of that answer holding its text (none: the whole answer, indented two
 * spaces) and the name to offer. An intent and a target, never the text: the
 * host fetches the path again through its own gates.
 */
export interface SaveIntent {
  path: string;
  filename: string;
  field?: string;
}

export interface Host {
  api: ApiClient;
  stream: OpenStream;
  go: (to: Destination) => void;
  /**
   * Signing in and the account's security, through django-allauth's headless
   * API (G3) — a host that holds a browser session supplies it (the studio);
   * a host without one (the extension's webviews, which carry a token) leaves
   * it out, and the account workspace offers what the token can do.
   */
  auth?: AuthHost;
  /**
   * Saving a file the page cannot save itself — the extension's webviews,
   * whose host writes it where the person chooses. A host that leaves it out
   * (the studio) saves in the page (`DownloadButton`).
   */
  save?: (file: SaveIntent) => void;
}

const HostContext = createContext<Host | null>(null);

export function StudioProvider({ api, stream, go, auth, save, children }: Host & { children: ReactNode }) {
  return <HostContext value={{ api, stream, go, auth, save }}>{children}</HostContext>;
}

function useHost(): Host {
  const host = use(HostContext);
  if (!host) throw new Error('@zer0/ui components render inside a <StudioProvider>');
  return host;
}

export const useApi = () => useHost().api;
export const useStream = () => useHost().stream;
export const useGo = () => useHost().go;
/** allauth's headless API from the host, or undefined where the host has no browser session. */
export const useAuthHost = () => useHost().auth;
/** The host's way to save a file, or undefined where the page saves it itself. */
export const useSave = () => useHost().save;
