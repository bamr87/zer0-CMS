/**
 * The GitHub surface of the Fleet console — declared as data first, and
 * implemented second.
 *
 * `FLEET_READS` and `FLEET_WRITES` list every call the console will ever make,
 * the way `analytics/analytics.ts` lists `MEMBER_READS`: what it is for, the
 * endpoint, the scope it needs, and a sentence saying what comes back. The
 * sentence is the boundary. Two guards read the list and refuse it:
 *
 *   * `fleetSurfaceIsRepoScopedOnly` — every path sits under one of the
 *     `FLEET_SUBROOTS` of the repository's own resources, and every `returns`
 *     says "the repository's own". It is an **allow-list**, not a prefix check:
 *     `/repos/{owner}/{repo}` is the prefix of the issues API, the releases
 *     API, the collaborators API and everything else a repository has, so a
 *     `startsWith` would have admitted far more than the prose claimed.
 *   * `fleetPlanHasNoMergeVerbs` — no declared call merges, approves, updates a
 *     branch, reads a secret, names a collaborator, deletes anything, or writes
 *     a label. That is the "what this console will never do" section of
 *     `docs/ARCHITECTURE.md`, expressed as a function so it is a test rather
 *     than a promise.
 *
 * Slice 2 widened the plan from six calls to fifteen — several repositories,
 * their lanes' switches and newest runs, what is in flight as pull requests,
 * what it costs, and whether each repository passes the shared audit. Widening
 * the plan without tightening the guard would have been the erosion decision
 * D11 exists to prevent, so both happened in the same change.
 *
 * `githubFleetClient` is the implementation, and it is deliberately thin: a
 * `fetch` the caller injects, a token the caller supplies **on demand**, and a
 * hard refusal to send a request whose method and path are not in the plan
 * above. The client holds no credential — `token()` is called per request and
 * its result goes straight into one header. Decision D11 (`src/commands/fleet.ts`)
 * is what makes this acceptable inside an extension that promises no network
 * on activation: network happens only from an explicit user action, through
 * this injected `fetch`, and never at activation.
 *
 * There is no retry, no pagination, no caching and no ETag handling. Every list
 * asks for exactly one page whose size is written into the declared path, so
 * "bounded" is enforced by the plan check rather than by a comment: a request
 * for a bigger page does not match a template and never opens a socket.
 */

import type {
  FleetPull,
  FleetRunRecord,
  FleetWorkflowState,
} from '../shared/types';
import type { FleetRun } from './fleet';
import { coercePull } from './pulls';

// ---------------------------------------------------------------------------
// The surface, as data
// ---------------------------------------------------------------------------

/**
 * The methods a `FleetCall` may name.
 *
 * `DELETE` is in the union and in none of the fifteen calls, on purpose:
 * `fleetPlanHasNoMergeVerbs` refuses it outright, and a union that cannot
 * express the method being refused is a guard nobody can write a test for.
 */
export type FleetMethod = 'GET' | 'PATCH' | 'POST' | 'PUT' | 'DELETE';

/** One call the console would make, described rather than made. */
export interface FleetCall {
  what: string;
  method: FleetMethod;
  /**
   * The path template. `{owner}`, `{repo}`, `{name}`, `{file}`, `{run}` each
   * stand for exactly ONE path segment; `{+path}` is RFC 6570 reserved
   * expansion and spans separators, because a repository file lives at
   * `_data/ai_usage/summary.yml` and not at a single segment. Any query string
   * is literal — that is what makes a page size part of the contract.
   */
  path: string;
  scope: string;
  /** What comes back — always the repository's own automation. */
  returns: string;
}

const REPO = '/repos/{owner}/{repo}';
const REPO_ACTIONS = `${REPO}/actions`;

/**
 * One page, and the size is in the declared path.
 *
 * The console shows a person a screen, so it asks for a screenful. Writing the
 * number into the template rather than into a parameter means `requestIsInPlan`
 * refuses a request for a bigger page before a socket opens, instead of a
 * comment asking politely for restraint.
 */
export const FLEET_LIST_PAGE = 100;
export const FLEET_RUNS_PAGE = 20;
export const FLEET_PULLS_PAGE = 30;

export const FLEET_READS: readonly FleetCall[] = [
  {
    what: "read a lane's switch",
    method: 'GET',
    path: `${REPO_ACTIONS}/variables/{name}`,
    scope: 'repo (Actions variables: read)',
    returns: "the repository's own *_ENABLED variable, as it is set right now",
  },
  {
    what: "every lane's switch in one call",
    method: 'GET',
    path: `${REPO_ACTIONS}/variables?per_page=${FLEET_LIST_PAGE}`,
    scope: 'repo (Actions variables: read)',
    returns:
      "the repository's own Actions variables — names and plaintext values, one page; " +
      'never a secret, which has no readable value at all',
  },
  {
    what: "the newest run of a lane's workflow",
    method: 'GET',
    path: `${REPO_ACTIONS}/workflows/{file}/runs?per_page=1`,
    scope: 'repo (Actions: read)',
    returns: "the repository's own latest workflow run: status, conclusion, url, updated_at",
  },
  {
    what: 'which workflows exist, and whether each one is enabled',
    method: 'GET',
    path: `${REPO_ACTIONS}/workflows?per_page=${FLEET_LIST_PAGE}`,
    scope: 'repo (Actions: read)',
    returns:
      "the repository's own registered workflows: id, path, name and state " +
      '(active, disabled_manually, disabled_inactivity)',
  },
  {
    what: 'what has run lately, across every lane',
    method: 'GET',
    path: `${REPO_ACTIONS}/runs?per_page=${FLEET_RUNS_PAGE}`,
    scope: 'repo (Actions: read)',
    returns:
      "the repository's own most recent workflow runs, newest first, one bounded page — " +
      'run id, workflow name and path, event, status, conclusion, timestamps and attempt',
  },
  {
    what: 'what is in flight as pull requests',
    method: 'GET',
    path: `${REPO}/pulls?state=open&per_page=${FLEET_PULLS_PAGE}`,
    scope: 'repo (pull requests: read)',
    returns:
      "the repository's own open pull requests, one bounded page — number, title, head ref, " +
      'labels, draft flag and whether the head is a branch here; never a merge state, which ' +
      'this endpoint does not carry and the console does not ask a second time for',
  },
  {
    what: 'read a file the console would otherwise have to clone the repository for',
    method: 'GET',
    path: `${REPO}/contents/{+path}`,
    scope: 'repo (contents: read)',
    returns:
      "the repository's own file or directory at that path on its default branch — a manifest, " +
      'a harness health file, an AI-usage ledger; read only, never written',
  },
  {
    what: 'the branch a dispatch runs on',
    method: 'GET',
    path: REPO,
    scope: 'repo (metadata: read)',
    returns: "the repository's own default branch name, and nothing else is read from the reply",
  },
];

export const FLEET_WRITES: readonly FleetCall[] = [
  {
    what: "flip a lane's switch",
    method: 'PATCH',
    path: `${REPO_ACTIONS}/variables/{name}`,
    scope: 'repo (Actions variables: write)',
    returns: "nothing — the repository's own variable now holds the value a person confirmed",
  },
  {
    what: "create a lane's switch the first time it is flipped",
    method: 'POST',
    path: `${REPO_ACTIONS}/variables`,
    scope: 'repo (Actions variables: write)',
    returns: "nothing — the repository's own variable exists, holding the value a person confirmed",
  },
  {
    what: 'dispatch a lane once',
    method: 'POST',
    path: `${REPO_ACTIONS}/workflows/{file}/dispatches`,
    scope: 'workflow',
    returns: "nothing — the repository's own workflow is queued once, on its default branch",
  },
  {
    what: 'run a failed lane again',
    method: 'POST',
    path: `${REPO_ACTIONS}/runs/{run}/rerun`,
    scope: 'repo (Actions: write)',
    returns:
      "nothing — the repository's own failed run is queued again as a new attempt; " +
      'the original attempt stays on the record',
  },
  {
    what: 'stop a lane that is still running',
    method: 'POST',
    path: `${REPO_ACTIONS}/runs/{run}/cancel`,
    scope: 'repo (Actions: write)',
    returns: "nothing — the repository's own in-progress run is asked to stop",
  },
  {
    what: 'turn a workflow file back on',
    method: 'PUT',
    path: `${REPO_ACTIONS}/workflows/{file}/enable`,
    scope: 'repo (Actions: write)',
    returns: "nothing — the repository's own workflow is registered active again",
  },
  {
    what: 'turn a workflow file off without deleting it',
    method: 'PUT',
    path: `${REPO_ACTIONS}/workflows/{file}/disable`,
    scope: 'repo (Actions: write)',
    returns:
      "nothing — the repository's own workflow is registered disabled_manually; " +
      'the file is untouched, which is why this is not an edit',
  },
];

/** Every call, reads first. This is the whole surface. */
export const FLEET_PLAN: readonly FleetCall[] = [...FLEET_READS, ...FLEET_WRITES];

// ---------------------------------------------------------------------------
// The two guards
// ---------------------------------------------------------------------------

/** Endpoints that are about people, not automation. None may appear in the plan. */
const PERSON_PATHS = /\/(user|users|members|collaborators|orgs|teams|emails)\b/;

/**
 * The only sub-resources of a repository this console reaches.
 *
 * `''` is the bare repository itself (one field is read from it). Every other
 * entry is matched as a whole path segment, except `'/contents/'` which ends in
 * a separator because it is always followed by a file path.
 *
 * This list exists because `path.startsWith('/repos/{owner}/{repo}')` — what the
 * guard used to do — is also true of `/issues`, `/releases`, `/collaborators`,
 * `/hooks`, `/keys` and `/actions/secrets`. A prefix check reads like a boundary
 * and is not one.
 */
export const FLEET_SUBROOTS: readonly string[] = [
  '',
  '/actions/variables',
  '/actions/workflows',
  '/actions/runs',
  '/pulls',
  '/contents/',
];

/**
 * Verbs this console refuses whatever the method, as path fragments.
 *
 * `/merge` catches `/pulls/{n}/merge`, `/merges` and `/merge-upstream` in one
 * fragment, which is the safe direction to be generous in.
 */
export const FLEET_FORBIDDEN_FRAGMENTS: readonly string[] = [
  '/merge',
  '/reviews',
  '/update-branch',
  '/actions/secrets',
  '/collaborators',
];

/** The path part of a template or a real path — everything before the query. */
function pathPartOf(pathWithQuery: string): string {
  return pathWithQuery.split('?', 2)[0] ?? '';
}

/**
 * Which sub-root a path belongs to, or `undefined` when it belongs to none.
 * `''` (the bare repository) is a real answer, so callers must test against
 * `undefined` rather than for truthiness.
 */
function subRootOf(pathWithQuery: string): string | undefined {
  const pathPart = pathPartOf(pathWithQuery);
  if (!pathPart.startsWith(REPO)) {
    return undefined;
  }
  const rest = pathPart.slice(REPO.length);
  return FLEET_SUBROOTS.find((root) => {
    if (root === '') {
      return rest === '';
    }
    return root.endsWith('/')
      ? rest.startsWith(root)
      : rest === root || rest.startsWith(`${root}/`);
  });
}

/**
 * Whether every call in a plan reaches only the repository's own automation.
 *
 * Two checks. The path must sit under one of `FLEET_SUBROOTS` of
 * `/repos/{owner}/{repo}` and never name a person-shaped resource; and
 * `returns` must say "the repository's own" — the same sentence-as-boundary
 * device `readSurfaceIsOwnContentOnly` uses. Somebody adding a collaborator or
 * member call has to write a sentence, and a sentence that cannot honestly say
 * "the repository's own" fails here.
 */
export function fleetSurfaceIsRepoScopedOnly(plan: readonly FleetCall[]): boolean {
  return plan.every(
    (call) =>
      subRootOf(call.path) !== undefined &&
      !PERSON_PATHS.test(call.path) &&
      /\bthe repository's own\b/.test(call.returns),
  );
}

/**
 * Whether a plan is free of the verbs this console will never perform.
 *
 * It never merges a pull request, approves or requests changes on one, updates
 * its branch, reads or writes an Actions secret, or names a collaborator. It
 * deletes nothing at all. And it never *writes* a label — reading the labels
 * that come back on a pull request is how `prStage` works, but adding or
 * removing one is how a review decision gets made, and that belongs to a
 * person and to the workflows they armed.
 *
 * Those are not omissions waiting to be filled in later. They are the boundary,
 * and this function is how it stays one.
 */
export function fleetPlanHasNoMergeVerbs(plan: readonly FleetCall[]): boolean {
  return plan.every((call) => {
    const pathPart = pathPartOf(call.path);
    if (FLEET_FORBIDDEN_FRAGMENTS.some((fragment) => pathPart.includes(fragment))) {
      return false;
    }
    if (call.method === 'DELETE') {
      return false;
    }
    return !(call.method !== 'GET' && pathPart.includes('/labels'));
  });
}

/** The surface as text, for a log, a modal detail, or a reviewer. */
export function describeFleetPlan(): string {
  const lines = ['Calls the Fleet console makes, and nothing else:', ''];
  for (const call of FLEET_PLAN) {
    lines.push(`  ${call.method} ${call.path}`);
    lines.push(`    to        ${call.what}`);
    lines.push(`    scope     ${call.scope}`);
    lines.push(`    returns   ${call.returns}`);
    lines.push('');
  }
  lines.push('No users, members, collaborators, organizations or teams. No');
  lines.push('secrets are read or written. Pull requests are listed and never');
  lines.push('merged, approved, closed or relabelled; contents are read and');
  lines.push('never written; nothing is ever deleted. Actions variables,');
  lines.push('workflows, runs, open pull requests and file contents — one');
  lines.push('bounded page each, on demand, from a person looking at a screen.');
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Matching a real request against the plan
// ---------------------------------------------------------------------------

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** `{name}`, `{run}`, `{+path}` — one segment each, except the `+` form. */
const PLACEHOLDER = /\{\+?[A-Za-z_]+\}/g;

/**
 * A path template → a regexp over one path segment per placeholder.
 *
 * `{+path}` is the exception and spans separators (RFC 6570 reserved
 * expansion), because the contents endpoint addresses a file by its whole
 * repository-relative path. No placeholder may swallow a `?`: a query string is
 * literal in a template, which is what pins a page size to the plan.
 */
function templateToRegExp(template: string): RegExp {
  const [pathPart = '', query] = template.split('?', 2);
  let body = '';
  let last = 0;
  for (const match of pathPart.matchAll(PLACEHOLDER)) {
    const at = match.index ?? 0;
    body += escapeRegExp(pathPart.slice(last, at));
    body += match[0].startsWith('{+') ? '[^?]+' : '[^/?]+';
    last = at + match[0].length;
  }
  body += escapeRegExp(pathPart.slice(last));
  const suffix = query === undefined ? '' : `\\?${escapeRegExp(query)}`;
  return new RegExp(`^${body}${suffix}$`);
}

/**
 * A `.` or `..` path segment. `{+path}` spans separators, so without this a
 * contents read of `../../../user` would match the template and then be
 * normalized by `fetch` into a call the plan never declared.
 */
const DOT_SEGMENT = /(^|\/)\.\.?(\/|$)/;

/**
 * `true` when `method` + `pathWithQuery` (the part after the API origin) is an
 * instance of a call in `plan`. The client refuses anything else, and the test
 * suite asserts the same thing from the outside by intercepting `fetch`.
 */
export function requestIsInPlan(
  method: string,
  pathWithQuery: string,
  plan: readonly FleetCall[] = FLEET_PLAN,
): boolean {
  if (DOT_SEGMENT.test(pathPartOf(pathWithQuery))) {
    return false;
  }
  return plan.some(
    (call) => call.method === method.toUpperCase() && templateToRegExp(call.path).test(pathWithQuery),
  );
}

// ---------------------------------------------------------------------------
// The client
// ---------------------------------------------------------------------------

/** One Actions variable. Plaintext by design — a secret has no readable value. */
export interface FleetVariable {
  name: string;
  value: string;
}

/** A file read through the contents endpoint, decoded. */
export interface FleetFile {
  path: string;
  /** Decoded UTF-8 text. */
  content: string;
  /** The blob sha. Carried because the engines' contract has it; never used to write. */
  sha: string;
}

/** One entry of a directory listing from the contents endpoint. */
export interface FleetDirEntry {
  path: string;
  name: string;
  sha: string;
  type: 'file' | 'dir';
}

/** What the shell needs from GitHub. Small, and every method is in the plan. */
export interface FleetClient {
  /** The variable's value, or `undefined` when it is not set (404). */
  getVariable(name: string): Promise<string | undefined>;
  /**
   * Every variable in one call, or `null` when they could not be read.
   *
   * `null` is not `[]`. An empty list means the repository really has no
   * variables, so every switch is genuinely unset; `null` means nobody could
   * ask, and a console must not draw a running lane as stopped.
   */
  listVariables(): Promise<FleetVariable[] | null>;
  /** Set the variable, creating it when it does not exist yet. */
  setVariable(name: string, value: string): Promise<void>;
  /** The newest run of a workflow file, or `undefined` when there is none. */
  latestRun(file: string): Promise<FleetRun | undefined>;
  /** Every registered workflow with its state. `[]` for a repository without Actions. */
  listWorkflows(): Promise<FleetWorkflowState[]>;
  /** One bounded page of the newest runs across every workflow, newest first. */
  recentRuns(): Promise<FleetRunRecord[]>;
  /** One bounded page of the open pull requests. */
  openPulls(): Promise<FleetPull[]>;
  /** A file on the default branch, or `null` when it is not there (404). */
  readFile(path: string): Promise<FleetFile | null>;
  /** A directory on the default branch; `[]` when it is not there. */
  listDir(path: string): Promise<FleetDirEntry[]>;
  /** The repository's default branch — the ref a dispatch runs on. */
  defaultBranch(): Promise<string>;
  /** Queue one `workflow_dispatch` on `ref`. */
  dispatch(file: string, ref: string): Promise<void>;
  /** Queue a completed run again, as a new attempt. */
  rerunRun(runId: number): Promise<void>;
  /** Ask an in-progress run to stop. */
  cancelRun(runId: number): Promise<void>;
  /**
   * Register a workflow active or disabled_manually. `workflow` is the file
   * name — GitHub also accepts the numeric workflow id in that position, which
   * is how the engines' `setWorkflowEnabled(repo, id, …)` reaches this.
   */
  setWorkflowEnabled(workflow: string, enabled: boolean): Promise<void>;
}

export interface FleetClientDeps {
  /** `owner/name`, from the manifest. */
  repo: string;
  /** The network. Injected so a test can intercept it and so activation never touches it. */
  fetchImpl: typeof fetch;
  /** Called per request. The client keeps nothing between calls. */
  token: () => Promise<string>;
  /** Defaults to `https://api.github.com`. */
  apiBase?: string;
}

export const GITHUB_API_BASE = 'https://api.github.com';

/** The API version every request pins, so a future breaking change is opt-in. */
export const GITHUB_API_VERSION = '2022-11-28';

/** `owner/name` → `{ owner, name }`, or `undefined` when it is not that shape. */
export function splitRepo(repo: string): { owner: string; name: string } | undefined {
  const match = /^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)$/.exec(repo.trim());
  return match === null ? undefined : { owner: match[1] ?? '', name: match[2] ?? '' };
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asText(value: unknown): string {
  return value === undefined || value === null ? '' : String(value);
}

function asNumber(value: unknown): number {
  const n = typeof value === 'number' ? value : Number(asText(value));
  return Number.isFinite(n) ? n : 0;
}

function asTextOrNull(value: unknown): string | null {
  return value === undefined || value === null ? null : String(value);
}

/** One run object from the API, coerced field by field. */
export function coerceRun(raw: unknown): FleetRun | undefined {
  const run = asRecord(raw);
  if (run === undefined) {
    return undefined;
  }
  const conclusion = run.conclusion;
  return {
    status: asText(run.status),
    conclusion: conclusion === null || conclusion === undefined ? null : asText(conclusion),
    url: asText(run.html_url),
    updatedAt: asText(run.updated_at),
  };
}

/**
 * A run with the identity a rerun or a cancel needs to name it. A record with
 * no `id` is dropped rather than given a zero: a button that would post to
 * `/actions/runs/0/cancel` is worse than a missing row.
 */
export function coerceRunRecord(raw: unknown): FleetRunRecord | undefined {
  const run = asRecord(raw);
  const base = coerceRun(raw);
  if (run === undefined || base === undefined) {
    return undefined;
  }
  const runId = asNumber(run.id);
  if (runId <= 0) {
    return undefined;
  }
  return {
    ...base,
    runId,
    name: asText(run.name),
    path: asText(run.path),
    event: asText(run.event),
    createdAt: asText(run.created_at),
    runStartedAt: asTextOrNull(run.run_started_at),
    runAttempt: asNumber(run.run_attempt),
  };
}

/** One registered workflow. A workflow with no id cannot be enabled or disabled, so it is dropped. */
export function coerceWorkflow(raw: unknown): FleetWorkflowState | undefined {
  const workflow = asRecord(raw);
  if (workflow === undefined) {
    return undefined;
  }
  const id = asNumber(workflow.id);
  if (id <= 0) {
    return undefined;
  }
  return {
    id,
    path: asText(workflow.path),
    name: asText(workflow.name),
    state: asText(workflow.state),
  };
}

/** One Actions variable. A nameless one is not a variable. */
export function coerceVariable(raw: unknown): FleetVariable | undefined {
  const variable = asRecord(raw);
  const name = asText(variable?.name);
  return variable === undefined || name === '' ? undefined : { name, value: asText(variable.value) };
}

/** One contents-endpoint entry, as a directory listing sees it. */
function coerceDirEntry(raw: unknown): FleetDirEntry | undefined {
  const entry = asRecord(raw);
  if (entry === undefined) {
    return undefined;
  }
  const type = asText(entry.type);
  if (type !== 'file' && type !== 'dir') {
    return undefined;
  }
  return { path: asText(entry.path), name: asText(entry.name), sha: asText(entry.sha), type };
}

/**
 * An HTTP failure, carrying the status so a caller can branch on 401/403/404.
 *
 * Structurally the engines package's `GithubError` — same `name`, same
 * `(message, status, url)` constructor, same two readonly fields — and
 * deliberately NOT that class. Importing a *value* from `./engines` into a
 * module the core barrel exports would drag `@bamr87/fleet-engines` into
 * `dist/mcp-server.js`, where the bare-import gate allows nothing at all.
 */
export class FleetGithubError extends Error {
  readonly status: number;
  readonly url: string;

  constructor(message: string, status: number, url: string) {
    super(message);
    this.name = 'GithubError';
    this.status = status;
    this.url = url;
  }
}

/**
 * A `FleetClient` over `fetch`. Every request: pinned API version, JSON
 * accept header, a bearer token fetched for that request, and a plan check
 * before the socket opens. Anything off-plan throws before it is sent.
 */
export function githubFleetClient(deps: FleetClientDeps): FleetClient {
  const parts = splitRepo(deps.repo);
  if (parts === undefined) {
    throw new Error(`fleet: "${deps.repo}" is not an owner/name repository`);
  }
  const base = (deps.apiBase ?? GITHUB_API_BASE).replace(/\/+$/, '');
  const repoPath = `/repos/${encodeURIComponent(parts.owner)}/${encodeURIComponent(parts.name)}`;

  function fail(method: FleetMethod, path: string, status: number): FleetGithubError {
    return new FleetGithubError(`GitHub ${method} ${path} answered ${status}`, status, `${base}${path}`);
  }

  async function send(
    method: FleetMethod,
    pathWithQuery: string,
    body?: Record<string, unknown>,
  ): Promise<Response> {
    if (!requestIsInPlan(method, pathWithQuery)) {
      throw new Error(`fleet: refused an off-plan request ${method} ${pathWithQuery}`);
    }
    const token = await deps.token();
    const headers: Record<string, string> = {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': GITHUB_API_VERSION,
    };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    return deps.fetchImpl(`${base}${pathWithQuery}`, {
      method,
      headers,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  }

  /** A GET whose 404 is "there is none", not a failure. */
  async function getJson(path: string): Promise<unknown> {
    const response = await send('GET', path);
    if (response.status === 404) {
      return undefined;
    }
    if (!response.ok) {
      throw fail('GET', path, response.status);
    }
    return response.json();
  }

  function listOf(raw: unknown, key?: string): unknown[] {
    if (Array.isArray(raw)) {
      return raw;
    }
    const nested = key === undefined ? undefined : asRecord(raw)?.[key];
    return Array.isArray(nested) ? nested : [];
  }

  /**
   * A repository-relative path → the `{+path}` segment of a contents URL.
   *
   * Each segment is encoded separately so a slash stays a separator, and a `.`
   * or `..` segment is refused here rather than being handed to `fetch`, which
   * would normalize it into a different endpoint entirely.
   */
  function contentsPath(rel: string): string {
    const clean = rel.replace(/^\/+/, '');
    if (DOT_SEGMENT.test(clean) || clean === '') {
      throw new Error(`fleet: refused a contents path that is not repository-relative: "${rel}"`);
    }
    return `${repoPath}/contents/${clean.split('/').map(encodeURIComponent).join('/')}`;
  }

  return {
    async getVariable(name) {
      const path = `${repoPath}/actions/variables/${encodeURIComponent(name)}`;
      const value = asRecord(await getJson(path))?.value;
      return value === undefined || value === null ? undefined : asText(value);
    },

    async listVariables() {
      const path = `${repoPath}/actions/variables?per_page=${FLEET_LIST_PAGE}`;
      const response = await send('GET', path);
      if (response.status === 403 || response.status === 404) {
        // Not "no variables" — "nobody could ask". The difference is the whole
        // point of the tristate the console renders.
        return null;
      }
      if (!response.ok) {
        throw fail('GET', path, response.status);
      }
      return listOf(await response.json(), 'variables')
        .map(coerceVariable)
        .filter((v): v is FleetVariable => v !== undefined);
    },

    async setVariable(name, value) {
      const path = `${repoPath}/actions/variables/${encodeURIComponent(name)}`;
      const patched = await send('PATCH', path, { name, value });
      if (patched.ok) {
        return;
      }
      if (patched.status !== 404) {
        throw fail('PATCH', path, patched.status);
      }
      // First flip: the variable does not exist yet.
      const createPath = `${repoPath}/actions/variables`;
      const created = await send('POST', createPath, { name, value });
      if (!created.ok) {
        throw fail('POST', createPath, created.status);
      }
    },

    async latestRun(file) {
      const path = `${repoPath}/actions/workflows/${encodeURIComponent(file)}/runs?per_page=1`;
      const runs = listOf(await getJson(path), 'workflow_runs');
      return coerceRun(runs[0]);
    },

    async listWorkflows() {
      const path = `${repoPath}/actions/workflows?per_page=${FLEET_LIST_PAGE}`;
      const response = await send('GET', path);
      if (response.status === 403 || response.status === 404) {
        return [];
      }
      if (!response.ok) {
        throw fail('GET', path, response.status);
      }
      return listOf(await response.json(), 'workflows')
        .map(coerceWorkflow)
        .filter((w): w is FleetWorkflowState => w !== undefined);
    },

    async recentRuns() {
      const path = `${repoPath}/actions/runs?per_page=${FLEET_RUNS_PAGE}`;
      const response = await send('GET', path);
      if (response.status === 403 || response.status === 404) {
        return [];
      }
      if (!response.ok) {
        throw fail('GET', path, response.status);
      }
      return listOf(await response.json(), 'workflow_runs')
        .map(coerceRunRecord)
        .filter((r): r is FleetRunRecord => r !== undefined);
    },

    async openPulls() {
      const path = `${repoPath}/pulls?state=open&per_page=${FLEET_PULLS_PAGE}`;
      const response = await send('GET', path);
      if (response.status === 403 || response.status === 404) {
        return [];
      }
      if (!response.ok) {
        throw fail('GET', path, response.status);
      }
      return listOf(await response.json())
        .map(coercePull)
        .filter((p): p is FleetPull => p !== undefined);
    },

    async readFile(rel) {
      const path = contentsPath(rel);
      const raw = await getJson(path);
      const file = asRecord(raw);
      if (file === undefined || asText(file.type) !== 'file') {
        return null;
      }
      const encoding = asText(file.encoding);
      const content = asText(file.content);
      return {
        path: asText(file.path),
        content:
          encoding === 'base64' ? Buffer.from(content, 'base64').toString('utf8') : content,
        sha: asText(file.sha),
      };
    },

    async listDir(rel) {
      const raw = await getJson(contentsPath(rel));
      return listOf(raw)
        .map(coerceDirEntry)
        .filter((e): e is FleetDirEntry => e !== undefined);
    },

    async defaultBranch() {
      const response = await send('GET', repoPath);
      if (!response.ok) {
        throw fail('GET', repoPath, response.status);
      }
      const branch = asText(asRecord(await response.json())?.default_branch);
      if (branch === '') {
        throw new Error(`fleet: ${deps.repo} reported no default branch`);
      }
      return branch;
    },

    async dispatch(file, ref) {
      const path = `${repoPath}/actions/workflows/${encodeURIComponent(file)}/dispatches`;
      const response = await send('POST', path, { ref });
      if (!response.ok) {
        throw fail('POST', path, response.status);
      }
    },

    async rerunRun(runId) {
      const path = `${repoPath}/actions/runs/${encodeURIComponent(String(runId))}/rerun`;
      const response = await send('POST', path);
      if (!response.ok) {
        throw fail('POST', path, response.status);
      }
    },

    async cancelRun(runId) {
      const path = `${repoPath}/actions/runs/${encodeURIComponent(String(runId))}/cancel`;
      const response = await send('POST', path);
      if (!response.ok) {
        throw fail('POST', path, response.status);
      }
    },

    async setWorkflowEnabled(workflow, enabled) {
      const verb = enabled ? 'enable' : 'disable';
      const path = `${repoPath}/actions/workflows/${encodeURIComponent(workflow)}/${verb}`;
      const response = await send('PUT', path);
      if (!response.ok) {
        throw fail('PUT', path, response.status);
      }
    },
  };
}
