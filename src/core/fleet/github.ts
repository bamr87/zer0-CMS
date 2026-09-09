/**
 * The GitHub surface of the Fleet console — declared as data first, and
 * implemented second.
 *
 * `FLEET_READS` and `FLEET_WRITES` list every call the console will ever make,
 * the way `analytics/analytics.ts` lists `MEMBER_READS`: what it is for, the
 * endpoint, the scope it needs, and a sentence saying what comes back. The
 * sentence is the boundary. `fleetSurfaceIsRepoScopedOnly` asserts that every
 * `returns` names *the repository's own* automation and that every path sits
 * under the repository's `/actions/` — so a call that reached a person (a
 * user, a member, a collaborator) fails a test rather than shipping.
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
 * There is no retry, no pagination, no caching and no ETag handling. The
 * console asks for one variable and one run per lane, on demand, for a person
 * who is looking at the screen.
 */

import type { FleetRun } from './fleet';

// ---------------------------------------------------------------------------
// The surface, as data
// ---------------------------------------------------------------------------

export type FleetMethod = 'GET' | 'PATCH' | 'POST';

/** One call the console would make, described rather than made. */
export interface FleetCall {
  what: string;
  method: FleetMethod;
  /** The path template, with `{owner}`, `{repo}`, `{name}`, `{file}` placeholders. */
  path: string;
  scope: string;
  /** What comes back — always the repository's own automation. */
  returns: string;
}

const REPO_ACTIONS = '/repos/{owner}/{repo}/actions';

export const FLEET_READS: readonly FleetCall[] = [
  {
    what: "read a lane's switch",
    method: 'GET',
    path: `${REPO_ACTIONS}/variables/{name}`,
    scope: 'repo (Actions variables: read)',
    returns: "the repository's own *_ENABLED variable, as it is set right now",
  },
  {
    what: "the newest run of a lane's workflow",
    method: 'GET',
    path: `${REPO_ACTIONS}/workflows/{file}/runs?per_page=1`,
    scope: 'repo (Actions: read)',
    returns: "the repository's own latest workflow run: status, conclusion, url, updated_at",
  },
  {
    what: 'the branch a dispatch runs on',
    method: 'GET',
    path: '/repos/{owner}/{repo}',
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
];

/** Every call, reads first. This is the whole surface. */
export const FLEET_PLAN: readonly FleetCall[] = [...FLEET_READS, ...FLEET_WRITES];

/** Endpoints that are about people, not automation. None may appear in the plan. */
const PERSON_PATHS = /\/(user|users|members|collaborators|orgs|teams|emails)\b/;

/**
 * Whether every call in a plan reaches only the repository's own automation.
 *
 * Two checks. The path must sit under `/repos/{owner}/{repo}` and never name
 * a person-shaped resource; and `returns` must say "the repository's own" —
 * the same sentence-as-boundary device `readSurfaceIsOwnContentOnly` uses.
 * Somebody adding a collaborator or member call has to write a sentence, and
 * a sentence that cannot honestly say "the repository's own" fails here.
 */
export function fleetSurfaceIsRepoScopedOnly(plan: readonly FleetCall[]): boolean {
  return plan.every(
    (call) =>
      call.path.startsWith('/repos/{owner}/{repo}') &&
      !PERSON_PATHS.test(call.path) &&
      /\bthe repository's own\b/.test(call.returns),
  );
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
  lines.push('secrets are read or written — only Actions variables, workflow runs,');
  lines.push('and one dispatch per confirmed click.');
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Matching a real request against the plan
// ---------------------------------------------------------------------------

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** `/repos/{owner}/{repo}/actions/variables/{name}` → a regexp over one path segment per placeholder. */
function templateToRegExp(template: string): RegExp {
  const [pathPart = '', query] = template.split('?', 2);
  const body = pathPart
    .split(/\{[a-z]+\}/)
    .map(escapeRegExp)
    .join('[^/]+');
  const suffix = query === undefined ? '' : `\\?${escapeRegExp(query)}`;
  return new RegExp(`^${body}${suffix}$`);
}

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
  return plan.some(
    (call) => call.method === method.toUpperCase() && templateToRegExp(call.path).test(pathWithQuery),
  );
}

// ---------------------------------------------------------------------------
// The client
// ---------------------------------------------------------------------------

/** What the shell needs from GitHub. Small, and every method is in the plan. */
export interface FleetClient {
  /** The variable's value, or `undefined` when it is not set (404). */
  getVariable(name: string): Promise<string | undefined>;
  /** Set the variable, creating it when it does not exist yet. */
  setVariable(name: string, value: string): Promise<void>;
  /** The newest run of a workflow file, or `undefined` when there is none. */
  latestRun(file: string): Promise<FleetRun | undefined>;
  /** The repository's default branch — the ref a dispatch runs on. */
  defaultBranch(): Promise<string>;
  /** Queue one `workflow_dispatch` on `ref`. */
  dispatch(file: string, ref: string): Promise<void>;
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

class GitHubError extends Error {
  constructor(
    readonly method: FleetMethod,
    readonly path: string,
    readonly status: number,
  ) {
    super(`GitHub ${method} ${path} answered ${status}`);
    this.name = 'GitHubError';
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

  return {
    async getVariable(name) {
      const path = `${repoPath}/actions/variables/${encodeURIComponent(name)}`;
      const response = await send('GET', path);
      if (response.status === 404) {
        return undefined;
      }
      if (!response.ok) {
        throw new GitHubError('GET', path, response.status);
      }
      const value = asRecord(await response.json())?.value;
      return value === undefined || value === null ? undefined : asText(value);
    },

    async setVariable(name, value) {
      const path = `${repoPath}/actions/variables/${encodeURIComponent(name)}`;
      const patched = await send('PATCH', path, { name, value });
      if (patched.ok) {
        return;
      }
      if (patched.status !== 404) {
        throw new GitHubError('PATCH', path, patched.status);
      }
      // First flip: the variable does not exist yet.
      const createPath = `${repoPath}/actions/variables`;
      const created = await send('POST', createPath, { name, value });
      if (!created.ok) {
        throw new GitHubError('POST', createPath, created.status);
      }
    },

    async latestRun(file) {
      const path = `${repoPath}/actions/workflows/${encodeURIComponent(file)}/runs?per_page=1`;
      const response = await send('GET', path);
      if (response.status === 404) {
        return undefined;
      }
      if (!response.ok) {
        throw new GitHubError('GET', path, response.status);
      }
      const runs = asRecord(await response.json())?.workflow_runs;
      return Array.isArray(runs) ? coerceRun(runs[0]) : undefined;
    },

    async defaultBranch() {
      const response = await send('GET', repoPath);
      if (!response.ok) {
        throw new GitHubError('GET', repoPath, response.status);
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
        throw new GitHubError('POST', path, response.status);
      }
    },
  };
}
