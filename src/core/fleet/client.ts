/**
 * `FleetClient` → the engines' `GithubClient`.
 *
 * `@bamr87/fleet-engines` reads a repository through one transport interface,
 * and the console wants the engines: the workflow facts, the audit rulebook,
 * the run metrics, the harness scorecard and the hub reader all take a
 * `GithubClient` and ask it for what they need. This adapter is how they get
 * one — over the console's own `FleetClient`, whose every request is checked
 * against `FLEET_PLAN` before a socket opens.
 *
 * **The package's contract is wider than this console's plan, and that gap is
 * the point.** `GithubClient` can write files, delete them, open branches and
 * pull requests, encrypt and store Actions secrets, and file issues. GitFactory
 * needs all of that; it deploys the workflows it compiles. This console does
 * not deploy anything, and the sub-root allow-list and the never-merge guard in
 * `./github.ts` say so at the level of URLs. So the twelve members the plan can
 * honestly serve are implemented, and **every other member throws before any
 * fetch happens** rather than being left to fail a plan check further in:
 *
 *   * realised (12) — `getFile`, `listDir`, `getDefaultBranch`,
 *     `listFactoryRuns`, `listRepoWorkflows`, `dispatchWorkflow`, `cancelRun`,
 *     `rerunRun`, `setWorkflowEnabled`, `listVariables`, `getVariable`,
 *     `setVariable`;
 *   * refused (10) — `preflight` (it asks about the credential's permissions,
 *     which is a question about a person), `putFile`, `deleteFile`,
 *     `createBranch`, `createPullRequest` (this console writes no repository),
 *     `getActionsPublicKey`, `hasSecret`, `putSecret` (no secret is read or
 *     written, ever), `listRunJobs` (a per-run drill-down is one more call per
 *     row against a console that makes four per repository per refresh), and
 *     `createIssue` (filing is triage's job, in its own lane, under its own
 *     review).
 *
 * `login` is `''`. The package fills it from `GET /user` at connect time; this
 * console never calls that endpoint, because `/user` is a person and the plan
 * is about a repository. An empty string is the honest answer, and it is why
 * `preflight` refuses rather than guessing.
 *
 * Refusals are a `FleetGithubError` with status **405** — the method is not
 * allowed *here*, which is a different statement from 403 (you may not) or 404
 * (there is nothing there). It carries the same `name`, `status` and `url`
 * fields the package's own `GithubError` does, so a caller that branches on
 * status works unchanged; it is not the package's class because importing a
 * value from `./engines` into a barrel-exported module would drag the package
 * into `dist/mcp-server.js`, where no bare import is allowed at all (D14).
 */

import type { EngineGithubClient, RepoRef } from './engines';
import { FleetGithubError, type FleetClient } from './github';

/**
 * The conclusions the package's `RunConclusion` union names. Anything else —
 * a value GitHub adds tomorrow — becomes `null` at this boundary, which the
 * package reads as "not concluded". The console's own `FleetRunRecord` keeps
 * the string verbatim, so nothing is lost on the screen; only the engines see
 * the narrowing, and only for a value they could not have handled anyway.
 */
const RUN_CONCLUSIONS = [
  'success',
  'failure',
  'cancelled',
  'timed_out',
  'skipped',
  'action_required',
  'neutral',
  'stale',
  'startup_failure',
] as const;

type EngineConclusion = (typeof RUN_CONCLUSIONS)[number] | null;

function narrowConclusion(raw: string | null): EngineConclusion {
  if (raw === null) {
    return null;
  }
  const known = RUN_CONCLUSIONS.find((value) => value === raw);
  return known ?? null;
}

/** `.github/workflows/germinate.yml` → `germinate`; the engines group runs by this. */
function slugOfPath(path: string): string {
  const base = path.slice(path.lastIndexOf('/') + 1);
  return base.replace(/\.ya?ml$/i, '');
}

/**
 * A `GithubClient` over `client`, bound to one repository.
 *
 * `repo` is the `owner/name` the underlying `FleetClient` was built for. Every
 * member takes a `RepoRef` — the package's clients serve a whole fleet — and a
 * ref naming a different repository is refused before any fetch, because a
 * client bound to one repository silently answering for another is exactly the
 * confusion the roster exists to prevent.
 */
export function engineClientOver(client: FleetClient, repo: string): EngineGithubClient {
  const bound = repo.trim().toLowerCase();

  function refuse(member: string, why: string): FleetGithubError {
    return new FleetGithubError(
      `fleet: this console does not ${why} (GithubClient.${member} is not in FLEET_PLAN)`,
      405,
      `zer0-cms:fleet/${member}`,
    );
  }

  function check(ref: RepoRef, member: string): void {
    const asked = `${ref.owner}/${ref.repo}`.trim().toLowerCase();
    if (asked !== bound) {
      throw new FleetGithubError(
        `fleet: this client is bound to ${repo}; ${member} asked for ${ref.owner}/${ref.repo}`,
        405,
        `zer0-cms:fleet/${member}`,
      );
    }
  }

  /**
   * The console reads a repository at its default branch — the state a person
   * looking at the screen is operating. The plan declares the contents call
   * with no `?ref=`, so a request for another ref would be off-plan; refusing
   * it out loud here is better than letting it look supported and fail later.
   * Nothing in the package passes a ref (`import.ts` and `hubread.ts` both call
   * `getFile(repo, path)`), so this never fires in practice.
   */
  function checkRef(ref: string | undefined, member: string): void {
    if (ref !== undefined && ref !== '') {
      throw refuse(member, 'read a repository at a ref other than its default branch');
    }
  }

  return {
    login: '',

    async preflight(ref) {
      check(ref, 'preflight');
      throw refuse('preflight', "ask what a person's credential is allowed to do");
    },

    async getFile(ref, path, atRef) {
      check(ref, 'getFile');
      checkRef(atRef, 'getFile');
      return client.readFile(path);
    },

    async listDir(ref, path, atRef) {
      check(ref, 'listDir');
      checkRef(atRef, 'listDir');
      return client.listDir(path);
    },

    async putFile(ref) {
      check(ref, 'putFile');
      throw refuse('putFile', 'write a file into a repository');
    },

    async deleteFile(ref) {
      check(ref, 'deleteFile');
      throw refuse('deleteFile', 'delete anything');
    },

    async getDefaultBranch(ref) {
      check(ref, 'getDefaultBranch');
      return client.defaultBranch();
    },

    async createBranch(ref) {
      check(ref, 'createBranch');
      throw refuse('createBranch', 'create a branch');
    },

    async createPullRequest(ref) {
      check(ref, 'createPullRequest');
      throw refuse('createPullRequest', 'open a pull request');
    },

    async getActionsPublicKey(ref) {
      check(ref, 'getActionsPublicKey');
      throw refuse('getActionsPublicKey', 'touch Actions secrets');
    },

    async hasSecret(ref) {
      check(ref, 'hasSecret');
      throw refuse('hasSecret', 'touch Actions secrets');
    },

    async putSecret(ref) {
      check(ref, 'putSecret');
      throw refuse('putSecret', 'touch Actions secrets');
    },

    /**
     * One bounded page of the newest runs.
     *
     * `etag` is accepted and ignored — this console does no conditional
     * requests, so the answer is never `notModified` and never carries an
     * etag to poll with next time. `rateRemaining` is `null` for the same
     * reason: nothing here reads the rate-limit headers, and `null` says "not
     * measured" where a number would claim it was.
     *
     * `pathPrefix` filters when given. Absent, nothing is filtered: the
     * package's own client lists `factory--*` runs, and this console wants
     * every lane's runs, not only the ones GitFactory compiled.
     */
    async listFactoryRuns(ref, opts) {
      check(ref, 'listFactoryRuns');
      const prefix = opts?.pathPrefix;
      const perPage = opts?.perPage;
      const records = await client.recentRuns();
      const runs = records
        .filter((run) => prefix === undefined || run.path.startsWith(prefix))
        .map((run) => ({
          path: run.path,
          slug: slugOfPath(run.path),
          runId: run.runId,
          // The console reads no run numbers: nothing it renders uses one, and
          // no engine reads the field (telemetry and metrics touch status,
          // conclusion, slug and the timestamps only). Zero here is a declared
          // absence at an adapter boundary, not a measurement.
          runNumber: 0,
          status: run.status,
          conclusion: narrowConclusion(run.conclusion),
          event: run.event,
          htmlUrl: run.url,
          runStartedAt: run.runStartedAt,
          updatedAt: run.updatedAt,
          createdAt: run.createdAt,
          runAttempt: run.runAttempt,
        }));
      return {
        runs: perPage === undefined ? runs : runs.slice(0, Math.max(0, perPage)),
        etag: null,
        notModified: false,
        rateRemaining: null,
      };
    },

    async listRunJobs(ref) {
      check(ref, 'listRunJobs');
      throw refuse('listRunJobs', 'drill into a run one call at a time');
    },

    async dispatchWorkflow(ref, workflowFile, atRef) {
      check(ref, 'dispatchWorkflow');
      const branch = atRef !== undefined && atRef !== '' ? atRef : await client.defaultBranch();
      return client.dispatch(workflowFile, branch);
    },

    async cancelRun(ref, runId) {
      check(ref, 'cancelRun');
      return client.cancelRun(runId);
    },

    /**
     * `htmlUrl` is `''`: the console's own `FleetWorkflowState` does not carry
     * one, because nothing it renders links to a workflow's blob. An empty
     * string is "not read" — and no engine dereferences the field.
     */
    async listRepoWorkflows(ref) {
      check(ref, 'listRepoWorkflows');
      const workflows = await client.listWorkflows();
      return workflows.map((workflow) => ({
        id: workflow.id,
        name: workflow.name,
        path: workflow.path,
        state: workflow.state,
        htmlUrl: '',
      }));
    },

    async rerunRun(ref, runId) {
      check(ref, 'rerunRun');
      return client.rerunRun(runId);
    },

    async setWorkflowEnabled(ref, workflowId, enabled) {
      check(ref, 'setWorkflowEnabled');
      // GitHub takes either the workflow id or the file name in that path
      // segment, which is what lets one declared call serve both callers.
      return client.setWorkflowEnabled(String(workflowId), enabled);
    },

    async createIssue(ref) {
      check(ref, 'createIssue');
      throw refuse('createIssue', 'file issues — that is triage, in its own lane');
    },

    async listVariables(ref) {
      check(ref, 'listVariables');
      return client.listVariables();
    },

    async getVariable(ref, name) {
      check(ref, 'getVariable');
      const value = await client.getVariable(name);
      return value === undefined ? null : { name, value };
    },

    async setVariable(ref, name, value) {
      check(ref, 'setVariable');
      return client.setVariable(name, value);
    },
  };
}

/**
 * Which `GithubClient` members this adapter realises, and which it refuses.
 *
 * Exported as data so the test can assert the split from the outside — over
 * the keys of the object the adapter actually returns — rather than by reading
 * the same list the implementation was written from.
 */
export const ENGINE_CLIENT_REALISED: readonly string[] = [
  'getFile',
  'listDir',
  'getDefaultBranch',
  'listFactoryRuns',
  'listRepoWorkflows',
  'dispatchWorkflow',
  'cancelRun',
  'rerunRun',
  'setWorkflowEnabled',
  'listVariables',
  'getVariable',
  'setVariable',
];

export const ENGINE_CLIENT_REFUSED: readonly string[] = [
  'preflight',
  'putFile',
  'deleteFile',
  'createBranch',
  'createPullRequest',
  'getActionsPublicKey',
  'hasSecret',
  'putSecret',
  'listRunJobs',
  'createIssue',
];
