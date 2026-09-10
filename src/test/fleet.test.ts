/**
 * The Fleet console's pure half: the manifest reader, the gate, the declared
 * GitHub surface, and the client's request paths.
 *
 * No `vscode`, no network — the client tests hand it a `fetch` that records
 * every request and answers from a table — and no writes anywhere. The one
 * file read is the verbatim irony-works manifest checked in under the fixture
 * workspace.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as path from 'node:path';

import {
  FLEET_LIST_PAGE,
  FLEET_MANIFEST_FILE,
  FLEET_PLAN,
  FLEET_PULLS_PAGE,
  FLEET_READS,
  FLEET_RUNS_PAGE,
  FLEET_SUBROOTS,
  FLEET_WRITES,
  buildLaneStates,
  coerceFleetManifest,
  describeFleetPlan,
  describeGuardrails,
  describeTriggers,
  evaluateFleetGates,
  fleetBlockerSummary,
  fleetPlanHasNoMergeVerbs,
  fleetSurfaceIsRepoScopedOnly,
  githubFleetClient,
  hasFleetBlocker,
  isDispatchable,
  laneById,
  nextSwitchValue,
  parseFleetManifest,
  readFleetManifest,
  requestIsInPlan,
  switchValueOf,
  workflowFileOf,
  type FleetCall,
  type FleetClient,
  type FleetGateInput,
  type FleetManifest,
  type FleetPull,
  type FleetRosterEntry,
} from '../core';
// The five slice-2 modules are imported from their own files rather than from
// the barrel: `src/core/index.ts` is an integration file, and this suite has to
// compile before the integration work package adds their export lines.
import {
  ENGINE_CLIENT_REALISED,
  ENGINE_CLIENT_REFUSED,
  engineClientOver,
} from '../core/fleet/client';
import { costByLane, parseUsageSummary } from '../core/fleet/cost';
import { describeMergePolicy, mergePolicyOf } from '../core/fleet/policy';
import { attributePulls, coercePull, prStage } from '../core/fleet/pulls';
import {
  mergeFleetRoster,
  parseProjectsRegistry,
  parseRosterSetting,
} from '../core/fleet/roster';

const WORKSPACE = path.resolve(__dirname, '../../src/test/fixtures/workspace');
const MANIFEST_PATH = path.join(WORKSPACE, FLEET_MANIFEST_FILE);

function fixtureManifest(): FleetManifest {
  const parsed = parseFleetManifest(fs.readFileSync(MANIFEST_PATH, 'utf8'));
  assert.ok(parsed.manifest !== null, parsed.reason);
  return parsed.manifest;
}

// ---------------------------------------------------------------------------

suite('fleet: the manifest — the irony-works fixture, verbatim', () => {
  test('parses whole, wrapped summary included', () => {
    const manifest = fixtureManifest();
    assert.equal(manifest.specVersion, 'fleet/v1');
    assert.equal(manifest.repo, 'bamr87/irony-works');
    assert.equal(manifest.provenance, 'derived');
    assert.equal(
      manifest.summary,
      'A self-growing encyclopedia of irony — the germinate engine scouts candidates, ' +
        'scores them at the Alanis Gate, and drafts passes into vault/nursery/ for a human to merge.',
      'the 80-column wrap `wtd fleet adopt` writes folds to one sentence',
    );
    assert.deepEqual(
      manifest.lanes.map((lane) => lane.id),
      ['alanis-gate', 'germinate'],
    );
    assert.deepEqual(manifest.skills, ['grow-irony-works']);
    assert.deepEqual(manifest.agents, []);
    assert.deepEqual(manifest.metering, {});
  });

  test('every lane field lands where the type says', () => {
    const manifest = fixtureManifest();
    const gate = laneById(manifest, 'alanis-gate');
    const germinate = laneById(manifest, 'germinate');
    assert.ok(gate !== undefined && germinate !== undefined);

    assert.equal(gate.kind, 'other');
    assert.equal(gate.harness, 'claude-cli');
    assert.equal(gate.implementation, '.github/workflows/alanis-gate.yml');
    assert.deepEqual(gate.triggers, [{ kind: 'event', cron: null, events: ['pull_request'] }]);
    assert.equal(gate.switch, null, 'switch: null is ungated, not the string "null"');
    assert.deepEqual(gate.usesTokens, ['ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN']);
    assert.deepEqual(gate.guardrails, {
      neverMerges: true,
      opensPullRequests: false,
      writesDirectlyToDefaultBranch: null,
      writablePaths: [],
    });
    assert.equal(isDispatchable(gate), false);

    assert.equal(germinate.kind, 'content');
    assert.deepEqual(germinate.triggers, [
      { kind: 'schedule', cron: '0 6 * * 1', events: [] },
      { kind: 'dispatch', cron: null, events: [] },
    ]);
    assert.equal(germinate.switch, 'GERMINATE_ENABLED');
    assert.deepEqual(germinate.guardrails.writablePaths, [
      'vault/nursery/',
      'vault/compost/the-merely-unfortunate.md',
    ]);
    assert.equal(
      germinate.guardrails.opensPullRequests,
      null,
      'a guardrail the manifest did not mention is null, not false',
    );
    assert.equal(isDispatchable(germinate), true);
    assert.equal(workflowFileOf(germinate), 'germinate.yml');
    assert.equal(describeTriggers(germinate.triggers), 'schedule 0 6 * * 1 · dispatch');
    assert.equal(describeTriggers([]), '(none)');
    assert.equal(
      describeGuardrails(germinate.guardrails),
      'never merges; writes only under vault/nursery/, vault/compost/the-merely-unfortunate.md',
    );
  });

  test('tokens carry their quoted purpose and their users', () => {
    const manifest = fixtureManifest();
    assert.deepEqual(
      manifest.tokens.map((t) => [t.name, t.required, t.usedBy.length]),
      [
        ['ANTHROPIC_API_KEY', false, 2],
        ['CLAUDE_CODE_OAUTH_TOKEN', true, 2],
      ],
    );
    assert.equal(
      manifest.tokens[1]?.purpose,
      'Preferred Claude auth (house convention: OAuth first). Produced by `claude setup-token`.',
      'a single-quoted scalar holding a colon survives intact',
    );
  });

  test('readFleetManifest reads the file, and reports a missing one instead of throwing', async () => {
    const found = await readFleetManifest(MANIFEST_PATH);
    assert.ok(found.manifest !== null);
    assert.equal(found.manifest.repo, 'bamr87/irony-works');

    const missing = await readFleetManifest(path.join(WORKSPACE, 'no-such.manifest.yml'));
    assert.equal(missing.manifest, null);
    assert.equal(missing.reason, 'not found: no-such.manifest.yml');
  });
});

suite('fleet: a malformed manifest is well-typed, never a TypeError', () => {
  test('unknown enums coerce, missing lists are empty, junk lanes are dropped', () => {
    const parsed = coerceFleetManifest({
      spec_version: 'fleet/v1',
      repo: 42,
      provenance: 'guessed',
      lanes: [
        'not a lane',
        { kind: 'content' },
        {
          id: 'odd',
          harness: 'cron-job',
          triggers: [{ kind: 'webhook' }, { kind: 'schedule' }, 'dispatch', { kind: 'dispatch' }],
          switch: '',
          uses_tokens: 'ONE_TOKEN',
          guardrails: { never_merges: 'false', writable_paths: [{ name: 'a/' }, 7] },
        },
      ],
      tokens: [{ scope: 'fleet' }, { name: 'T', required: 'true', used_by: [{ id: 'odd' }] }],
      agents: 'solo',
      skills: [null, 'one'],
      metering: 'none',
    });
    assert.ok(parsed.manifest !== null);
    const manifest = parsed.manifest;
    assert.equal(manifest.repo, '42');
    assert.equal(manifest.provenance, 'unknown');
    assert.equal(manifest.summary, '');
    assert.equal(manifest.lanes.length, 1, 'a lane without an id is not a lane');
    const lane = manifest.lanes[0];
    assert.ok(lane !== undefined);
    assert.equal(lane.kind, 'other');
    assert.equal(lane.harness, 'none', 'an unknown harness is none');
    assert.equal(lane.description, 'odd', 'the description falls back to the id');
    assert.deepEqual(
      lane.triggers,
      [
        { kind: 'schedule', cron: null, events: [] },
        { kind: 'dispatch', cron: null, events: [] },
      ],
      'an unknown trigger kind and a bare string are dropped',
    );
    assert.equal(lane.switch, null, 'an empty switch is ungated');
    assert.deepEqual(lane.usesTokens, ['ONE_TOKEN'], 'a lone scalar reads as a one-element list');
    assert.equal(lane.guardrails.neverMerges, false, 'the string "false" is the boolean');
    assert.deepEqual(lane.guardrails.writablePaths, ['a/', '7']);
    assert.deepEqual(
      manifest.tokens.map((t) => [t.name, t.required, t.usedBy]),
      [['T', true, ['odd']]],
    );
    assert.deepEqual(manifest.agents, ['solo']);
    assert.deepEqual(manifest.skills, ['one']);
    assert.deepEqual(manifest.metering, {});
  });

  test('only the spec version is refused, with a reason', () => {
    assert.deepEqual(coerceFleetManifest(null), {
      manifest: null,
      reason: 'the manifest is not a YAML mapping',
    });
    assert.deepEqual(coerceFleetManifest({ repo: 'a/b' }), {
      manifest: null,
      reason: 'the manifest declares no spec_version',
    });
    assert.deepEqual(coerceFleetManifest({ spec_version: 'fleet/v2' }), {
      manifest: null,
      reason: 'spec_version "fleet/v2" is not fleet/v1',
    });
    const empty = parseFleetManifest('spec_version: fleet/v1\n');
    assert.ok(empty.manifest !== null);
    assert.deepEqual(empty.manifest.lanes, []);
    assert.equal(parseFleetManifest('').manifest, null, 'an empty file is not a manifest');
  });
});

suite('fleet: lane state', () => {
  test('switch values follow what a workflow would do with the variable', () => {
    assert.equal(switchValueOf(undefined), 'unset');
    assert.equal(switchValueOf(null), 'unset');
    assert.equal(switchValueOf('true'), 'true');
    assert.equal(switchValueOf(' true '), 'true');
    assert.equal(switchValueOf('false'), 'false');
    assert.equal(switchValueOf('yes'), 'false', 'vars.X == "true" is the only ON');
    assert.equal(switchValueOf(''), 'false');
  });

  test('the next value is derived from the current one, and unknown has none', () => {
    assert.equal(nextSwitchValue('true'), 'false');
    assert.equal(nextSwitchValue('false'), 'true');
    assert.equal(nextSwitchValue('unset'), 'true');
    assert.equal(nextSwitchValue('unknown'), null, 'a toggle that could not read must refuse');
  });

  test('buildLaneStates joins the manifest with what the repository said', () => {
    const manifest = fixtureManifest();
    const bare = buildLaneStates(manifest);
    assert.deepEqual(
      bare.map((s) => [s.lane.id, s.switchValue, 'lastRun' in s]),
      [
        ['alanis-gate', 'unset', false],
        ['germinate', 'unknown', false],
      ],
      'an ungated lane is unset; a gated lane nobody asked about is unknown',
    );
    const run = { status: 'completed', conclusion: 'success', url: 'https://x/1', updatedAt: '2026-09-01T00:00:00Z' };
    const full = buildLaneStates(
      manifest,
      new Map([['GERMINATE_ENABLED', 'true' as const]]),
      new Map([['germinate', run]]),
    );
    assert.equal(full[1]?.switchValue, 'true');
    assert.deepEqual(full[1]?.lastRun, run);
    assert.equal('lastRun' in (full[0] ?? {}), false, 'no run means no key, not undefined');
  });
});

suite('fleet: the gate — fixed order, master gate first', () => {
  const manifest = fixtureManifest();

  function open(overrides: Partial<FleetGateInput> = {}): FleetGateInput {
    return {
      workspaceRoot: WORKSPACE,
      enabled: true,
      dispatchAllow: true,
      hasCredential: true,
      manifest,
      laneId: 'germinate',
      ...overrides,
    };
  }

  function scaffolding(overrides: Partial<FleetGateInput> = {}): FleetGateInput {
    return {
      ...open(),
      scaffoldAllow: true,
      laneId: 'content-review',
      scaffold: {
        laneId: 'content-review',
        workflowPath: '.github/workflows/content-review.yml',
        workflowExists: false,
        switchName: 'CONTENT_REVIEW_ENABLED',
        switchTaken: false,
        notExpressibleReasons: [],
      },
      ...overrides,
    };
  }

  test('scaffolding runs its own checks, because four of the others are wrong for it', () => {
    // Writing a lane's files needs no GitHub credential, and a repository with
    // no manifest is precisely where a first lane gets written. Running the
    // dispatch list here would refuse every one of those on grounds that do not
    // apply — so scaffold has its own list rather than the same one with
    // exceptions bolted on.
    assert.deepEqual(
      evaluateFleetGates('scaffold', scaffolding({ hasCredential: false, manifest: null })),
      [],
      'no credential and no manifest are both fine when writing a first lane',
    );
  });

  test('the scaffold blockers fire in their own fixed order', () => {
    const blockers = evaluateFleetGates(
      'scaffold',
      scaffolding({
        workspaceRoot: '',
        enabled: false,
        scaffoldAllow: false,
        laneId: 'germinate',
        scaffold: {
          laneId: 'germinate', // already in the fixture manifest
          workflowPath: '.github/workflows/germinate.yml',
          workflowExists: true,
          switchName: 'GERMINATE_ENABLED',
          switchTaken: true,
          notExpressibleReasons: ['needs a dynamic matrix'],
        },
      }),
    );
    assert.deepEqual(
      blockers.map((b) => b.kind),
      [
        'noWorkspace',
        'dispatchDisabled',
        'scaffoldDisabled',
        'laneExists',
        'workflowFileExists',
        'switchNameTaken',
        'notExpressible',
      ],
    );
  });

  test('scaffoldAllow is the scaffold master gate, and dispatchAllow does not stand in for it', () => {
    // Writing a workflow into a repository and running one that is already
    // there are different powers, so one switch must not arm the other.
    const armedToDispatch = evaluateFleetGates(
      'scaffold',
      scaffolding({ scaffoldAllow: false, dispatchAllow: true }),
    );
    assert.deepEqual(armedToDispatch.map((b) => b.kind), ['scaffoldDisabled']);

    const armedToScaffold = evaluateFleetGates(
      'scaffold',
      scaffolding({ scaffoldAllow: true, dispatchAllow: false }),
    );
    assert.deepEqual(armedToScaffold, [], 'dispatchAllow is not a scaffold gate in either direction');
  });

  test('a lane that cannot be expressed says why, rather than being approximated', () => {
    const blockers = evaluateFleetGates(
      'scaffold',
      scaffolding({
        scaffold: {
          laneId: 'content-factory',
          workflowPath: '.github/workflows/content-factory.yml',
          workflowExists: false,
          switchName: 'CONTENT_FACTORY_ENABLED',
          switchTaken: false,
          notExpressibleReasons: ['needs a per-item matrix', 'checks out a second repository'],
        },
      }),
    );
    assert.deepEqual(blockers.map((b) => b.kind), ['notExpressible']);
    assert.match(blockers[0]?.message ?? '', /per-item matrix; checks out a second repository/);
  });

  test('a gated, dispatchable lane with everything in place has no blockers', () => {
    assert.deepEqual(evaluateFleetGates('toggle', open()), []);
    assert.deepEqual(evaluateFleetGates('dispatch', open()), []);
  });

  test('with no manifest, the first four fire in order', () => {
    for (const mode of ['toggle', 'dispatch'] as const) {
      const blockers = evaluateFleetGates(mode, {
        workspaceRoot: '',
        enabled: false,
        dispatchAllow: false,
        hasCredential: false,
        manifest: null,
        manifestReason: 'not found: fleet.manifest.yml',
        laneId: 'germinate',
      });
      assert.deepEqual(
        blockers.map((b) => b.kind),
        ['noWorkspace', 'dispatchDisabled', 'noCredential', 'manifestAbsent'],
        `${mode}: the order is fixed so the note reads the same way every time`,
      );
      assert.equal(
        fleetBlockerSummary(blockers.slice(0, 2)),
        'no workspace folder is open; the fleet console is disabled (set "zer0Cms.fleet.enabled" to true)',
      );
      assert.equal(blockers[3]?.message, 'no fleet manifest (not found: fleet.manifest.yml)');
    }
  });

  test('dispatchDisabled names dispatchAllow once enabled is on, and nothing overrides it', () => {
    const blockers = evaluateFleetGates('dispatch', open({ dispatchAllow: false }));
    assert.deepEqual(blockers.map((b) => b.kind), ['dispatchDisabled']);
    assert.equal(
      blockers[0]?.message,
      'fleet actions are disabled (set "zer0Cms.fleet.dispatchAllow" to true in your own settings)',
    );
    // The manifest has no say: a lane declaring every guardrail perfectly is
    // still blocked, and there is no input key that clears the master gate.
    assert.ok(hasFleetBlocker(evaluateFleetGates('toggle', open({ enabled: false })), 'dispatchDisabled'));
  });

  test('an unknown lane, then the mode-specific lane checks, then guardrails', () => {
    assert.deepEqual(
      evaluateFleetGates('toggle', open({ hasCredential: false, laneId: 'nope' })).map((b) => b.kind),
      ['noCredential', 'laneUnknown'],
    );
    assert.deepEqual(
      evaluateFleetGates('toggle', open({ laneId: 'alanis-gate' })).map((b) => b.kind),
      ['laneHasNoSwitch'],
      'toggle: an ungated lane has nothing to flip',
    );
    assert.deepEqual(
      evaluateFleetGates('dispatch', open({ laneId: 'alanis-gate' })).map((b) => b.kind),
      ['laneNotDispatchable'],
      'dispatch: an event-only lane cannot be dispatched',
    );
    assert.equal(
      evaluateFleetGates('dispatch', open({ laneId: 'alanis-gate' }))[0]?.message,
      'lane "alanis-gate" has no workflow_dispatch trigger',
    );
  });

  test('a lane whose manifest admits to merging or writing to main is refused in both modes', () => {
    const rogue: FleetManifest = {
      ...manifest,
      lanes: [
        {
          ...(laneById(manifest, 'germinate') ?? manifest.lanes[1]!),
          id: 'rogue',
          guardrails: {
            neverMerges: false,
            opensPullRequests: true,
            writesDirectlyToDefaultBranch: true,
            writablePaths: [],
          },
        },
      ],
    };
    for (const mode of ['toggle', 'dispatch'] as const) {
      const blockers = evaluateFleetGates(mode, open({ manifest: rogue, laneId: 'rogue' }));
      assert.deepEqual(blockers.map((b) => b.kind), ['guardrailViolation']);
      assert.equal(
        blockers[0]?.message,
        'lane "rogue" declares guardrails the console will not act through ' +
          '(never_merges is false, writes_directly_to_default_branch is true)',
      );
    }
    const nullish: FleetManifest = {
      ...rogue,
      lanes: [
        {
          ...rogue.lanes[0]!,
          guardrails: { neverMerges: null, opensPullRequests: null, writesDirectlyToDefaultBranch: null, writablePaths: [] },
        },
      ],
    };
    assert.deepEqual(
      evaluateFleetGates('dispatch', open({ manifest: nullish, laneId: 'rogue' })),
      [],
      'a guardrail left null is an absence, not a violation',
    );
  });

  test('every mode-applicable blocker fires together, in the fixed order', () => {
    const rogue: FleetManifest = {
      ...manifest,
      lanes: [
        {
          id: 'bad',
          kind: 'other',
          harness: 'none',
          implementation: '',
          description: 'bad',
          triggers: [],
          switch: null,
          usesTokens: [],
          guardrails: { neverMerges: false, opensPullRequests: null, writesDirectlyToDefaultBranch: true, writablePaths: [] },
        },
      ],
    };
    const base = { workspaceRoot: '', enabled: false, dispatchAllow: false, hasCredential: false, manifest: rogue, laneId: 'bad' };
    assert.deepEqual(evaluateFleetGates('toggle', base).map((b) => b.kind), [
      'noWorkspace',
      'dispatchDisabled',
      'noCredential',
      'laneHasNoSwitch',
      'guardrailViolation',
    ]);
    const dispatch = evaluateFleetGates('dispatch', base);
    assert.deepEqual(dispatch.map((b) => b.kind), [
      'noWorkspace',
      'dispatchDisabled',
      'noCredential',
      'laneNotDispatchable',
      'guardrailViolation',
    ]);
    assert.equal(dispatch[3]?.message, 'lane "bad" names no workflow file');
  });
});

suite('fleet: the GitHub surface is declared, and it is repo-scoped only', () => {
  test('the shipped plan passes the guard, and a members call fails it', () => {
    assert.ok(fleetSurfaceIsRepoScopedOnly(FLEET_PLAN));
    assert.ok(fleetSurfaceIsRepoScopedOnly(FLEET_READS));
    assert.ok(fleetSurfaceIsRepoScopedOnly(FLEET_WRITES));

    const members: FleetCall = {
      what: 'who can push',
      method: 'GET',
      path: '/repos/{owner}/{repo}/collaborators',
      scope: 'repo',
      returns: "the repository's own collaborator list",
    };
    assert.equal(fleetSurfaceIsRepoScopedOnly([...FLEET_PLAN, members]), false, 'a person-shaped path fails');
    const vague: FleetCall = {
      ...FLEET_READS[0]!,
      returns: 'a variable',
    };
    assert.equal(fleetSurfaceIsRepoScopedOnly([vague]), false, 'a sentence that cannot say "the repository\'s own" fails');
    const elsewhere: FleetCall = { ...FLEET_READS[0]!, path: '/user/repos' };
    assert.equal(fleetSurfaceIsRepoScopedOnly([elsewhere]), false);
  });

  test('describeFleetPlan names every call and the boundary', () => {
    const text = describeFleetPlan();
    for (const call of FLEET_PLAN) {
      assert.ok(text.includes(`${call.method} ${call.path}`), call.path);
    }
    assert.ok(text.includes('No users, members, collaborators'));
  });

  test('requestIsInPlan matches concrete paths against the templates', () => {
    assert.ok(requestIsInPlan('GET', '/repos/bamr87/irony-works/actions/variables/GERMINATE_ENABLED'));
    assert.ok(requestIsInPlan('get', '/repos/bamr87/irony-works/actions/workflows/germinate.yml/runs?per_page=1'));
    assert.ok(requestIsInPlan('POST', '/repos/bamr87/irony-works/actions/workflows/germinate.yml/dispatches'));
    assert.ok(requestIsInPlan('GET', '/repos/bamr87/irony-works'));
    assert.equal(requestIsInPlan('DELETE', '/repos/bamr87/irony-works/actions/variables/X'), false);
    // RETIRED 2026-09-10 (fleet slice 2). This line used to read
    //   assert.equal(requestIsInPlan('GET', '…/actions/variables'), false, 'listing is not in the plan');
    // Slice 1 read one variable per lane, so listing them was reach the plan
    // did not need. Slice 2 refreshes several repositories at once and asks
    // four repo-level questions each, so reading every variable in ONE bounded
    // call is strictly less reach than N calls — and it is what lets the merge
    // policy be reported without a request of its own. The listing is in the
    // plan now, with its page size written into the declared path; an
    // unbounded listing still is not.
    assert.ok(requestIsInPlan('GET', '/repos/bamr87/irony-works/actions/variables?per_page=100'));
    assert.equal(requestIsInPlan('GET', '/repos/bamr87/irony-works/actions/variables'), false, 'and only the bounded form');
    assert.equal(requestIsInPlan('GET', '/repos/bamr87/irony-works/actions/workflows/germinate.yml/runs'), false, 'unbounded runs are not');
    assert.equal(requestIsInPlan('GET', '/repos/bamr87/irony-works/collaborators'), false);
    assert.equal(requestIsInPlan('GET', '/repos/bamr87/irony-works/actions/variables/a/b'), false, 'a placeholder is one segment');
  });
});

suite('fleet: the client — every request is in the plan, and nothing is stored', () => {
  interface Seen {
    method: string;
    path: string;
    headers: Record<string, string>;
    body: unknown;
  }

  function fakeFetch(
    answers: Record<string, { status: number; body?: unknown }>,
    seen: Seen[],
  ): typeof fetch {
    return async (input, init) => {
      const url = new URL(String(input));
      const method = (init?.method ?? 'GET').toUpperCase();
      const path = `${url.pathname}${url.search}`;
      seen.push({
        method,
        path,
        headers: { ...((init?.headers as Record<string, string> | undefined) ?? {}) },
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
      });
      const answer = answers[`${method} ${path}`] ?? { status: 404 };
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status,
        headers: { 'Content-Type': 'application/json' },
      });
    };
  }

  const REPO = '/repos/bamr87/irony-works';

  test('reads: a set variable, an unset one, the newest run, the default branch', async () => {
    const seen: Seen[] = [];
    let tokenCalls = 0;
    const client = githubFleetClient({
      repo: 'bamr87/irony-works',
      fetchImpl: fakeFetch(
        {
          [`GET ${REPO}/actions/variables/GERMINATE_ENABLED`]: { status: 200, body: { name: 'GERMINATE_ENABLED', value: 'true' } },
          [`GET ${REPO}/actions/workflows/germinate.yml/runs?per_page=1`]: {
            status: 200,
            body: {
              workflow_runs: [
                { status: 'completed', conclusion: 'success', html_url: 'https://github.com/x/runs/1', updated_at: '2026-09-01T06:00:00Z' },
              ],
            },
          },
          [`GET ${REPO}`]: { status: 200, body: { default_branch: 'main', private: false } },
        },
        seen,
      ),
      token: async () => {
        tokenCalls++;
        return `tok-${tokenCalls}`;
      },
    });

    assert.equal(await client.getVariable('GERMINATE_ENABLED'), 'true');
    assert.equal(await client.getVariable('NOPE_ENABLED'), undefined, '404 is "unset", not an error');
    assert.deepEqual(await client.latestRun('germinate.yml'), {
      status: 'completed',
      conclusion: 'success',
      url: 'https://github.com/x/runs/1',
      updatedAt: '2026-09-01T06:00:00Z',
    });
    assert.equal(await client.latestRun('missing.yml'), undefined);
    assert.equal(await client.defaultBranch(), 'main');

    assert.equal(seen.length, 5);
    for (const request of seen) {
      assert.ok(requestIsInPlan(request.method, request.path), `${request.method} ${request.path} is off-plan`);
      assert.equal(request.headers.Accept, 'application/vnd.github+json');
      assert.equal(request.headers['X-GitHub-Api-Version'], '2022-11-28');
      assert.match(request.headers.Authorization ?? '', /^Bearer tok-\d$/);
    }
    assert.equal(tokenCalls, 5, 'the token is asked for per request and never kept');
    assert.deepEqual(
      new Set(seen.map((r) => r.headers.Authorization)).size,
      5,
      'each request carried the token it was handed, so nothing was cached',
    );
  });

  test('writes: PATCH a variable, POST it when it does not exist yet, POST a dispatch', async () => {
    const seen: Seen[] = [];
    const client = githubFleetClient({
      repo: 'bamr87/irony-works',
      fetchImpl: fakeFetch(
        {
          [`PATCH ${REPO}/actions/variables/GERMINATE_ENABLED`]: { status: 204 },
          [`POST ${REPO}/actions/variables`]: { status: 201 },
          [`POST ${REPO}/actions/workflows/germinate.yml/dispatches`]: { status: 204 },
        },
        seen,
      ),
      token: async () => 'tok',
    });

    await client.setVariable('GERMINATE_ENABLED', 'false');
    await client.setVariable('NEW_ENABLED', 'true');
    await client.dispatch('germinate.yml', 'main');

    assert.deepEqual(
      seen.map((r) => [r.method, r.path, r.body]),
      [
        ['PATCH', `${REPO}/actions/variables/GERMINATE_ENABLED`, { name: 'GERMINATE_ENABLED', value: 'false' }],
        ['PATCH', `${REPO}/actions/variables/NEW_ENABLED`, { name: 'NEW_ENABLED', value: 'true' }],
        ['POST', `${REPO}/actions/variables`, { name: 'NEW_ENABLED', value: 'true' }],
        ['POST', `${REPO}/actions/workflows/germinate.yml/dispatches`, { ref: 'main' }],
      ],
    );
    for (const request of seen) {
      assert.ok(requestIsInPlan(request.method, request.path), `${request.method} ${request.path} is off-plan`);
      assert.equal(request.headers['Content-Type'], 'application/json');
    }
  });

  test('a failure is an error naming the call, and the client refuses a bad repo', async () => {
    const client = githubFleetClient({
      repo: 'bamr87/irony-works',
      fetchImpl: fakeFetch({ [`POST ${REPO}/actions/workflows/x.yml/dispatches`]: { status: 403 } }, []),
      token: async () => 'tok',
    });
    await assert.rejects(client.dispatch('x.yml', 'main'), /GitHub POST .*dispatches answered 403/);
    await assert.rejects(client.defaultBranch(), /answered 404/);
    assert.throws(
      () => githubFleetClient({ repo: 'not a repo', fetchImpl: fakeFetch({}, []), token: async () => '' }),
      /not an owner\/name repository/,
    );
  });
});

// ---------------------------------------------------------------------------
// Fleet slice 2 — the widened plan, the two guards, and the domain modules
// ---------------------------------------------------------------------------

const FLEET_FIXTURES = path.resolve(__dirname, '../../src/test/fixtures/fleet');

/** A synthetic call, so a guard can be asserted from the refused direction too. */
function call(overrides: Partial<FleetCall>): FleetCall {
  return {
    what: 'a call somebody added',
    method: 'GET',
    path: '/repos/{owner}/{repo}',
    scope: 'repo',
    returns: "the repository's own something",
    ...overrides,
  };
}

suite('fleet slice 2: the plan is wider, and the guard is tighter', () => {
  test('the plan is eight reads, seven writes, and fifteen calls', () => {
    assert.equal(FLEET_READS.length, 8);
    assert.equal(FLEET_WRITES.length, 7);
    assert.equal(FLEET_PLAN.length, 15);
    assert.deepEqual(FLEET_PLAN, [...FLEET_READS, ...FLEET_WRITES], 'reads first, and the plan is the concatenation');
    assert.equal(
      FLEET_READS[0]?.path,
      '/repos/{owner}/{repo}/actions/variables/{name}',
      'the single-variable read stays first: other assertions index it',
    );
    // Every page size is written into the declared path, so "bounded" is a plan
    // check rather than a comment somebody could stop honouring.
    const queries = FLEET_PLAN.map((c) => c.path.split('?')[1]).filter((q): q is string => q !== undefined);
    assert.deepEqual(queries.sort(), [
      `per_page=${FLEET_LIST_PAGE}`,
      `per_page=${FLEET_LIST_PAGE}`,
      'per_page=1',
      `per_page=${FLEET_RUNS_PAGE}`,
      `state=open&per_page=${FLEET_PULLS_PAGE}`,
    ].sort());
    assert.ok(FLEET_PLAN.every((c) => /\bthe repository's own\b/.test(c.returns)));
  });

  test('the sub-root allow-list is what makes it repo-scoped, and a prefix is not', () => {
    assert.deepEqual(FLEET_SUBROOTS, [
      '',
      '/actions/variables',
      '/actions/workflows',
      '/actions/runs',
      '/pulls',
      '/contents/',
    ]);
    assert.ok(fleetSurfaceIsRepoScopedOnly(FLEET_PLAN));
    assert.ok(fleetSurfaceIsRepoScopedOnly(FLEET_READS));
    assert.ok(fleetSurfaceIsRepoScopedOnly(FLEET_WRITES));

    // Every sub-root admits a call inside it …
    for (const root of FLEET_SUBROOTS) {
      const suffix = root === '' ? '' : root.endsWith('/') ? `${root}a/b` : `${root}/x`;
      assert.ok(
        fleetSurfaceIsRepoScopedOnly([call({ path: `/repos/{owner}/{repo}${suffix}` })]),
        `${root || '(the repository itself)'} should be admitted`,
      );
    }
    // … and everything else a repository has is refused, though every one of
    // these starts with `/repos/{owner}/{repo}` and would have passed the old
    // prefix check.
    for (const path of [
      '/repos/{owner}/{repo}/issues',
      '/repos/{owner}/{repo}/releases',
      '/repos/{owner}/{repo}/hooks',
      '/repos/{owner}/{repo}/keys',
      '/repos/{owner}/{repo}/actions/secrets',
      '/repos/{owner}/{repo}/actions/caches',
      '/repos/{owner}/{repo}/collaborators',
      '/repos/{owner}/{repo}/pullsomething',
      '/repos/{owner}/{repo}/contents',
      '/user/repos',
    ]) {
      assert.equal(fleetSurfaceIsRepoScopedOnly([call({ path })]), false, `${path} must be refused`);
    }
    assert.equal(
      fleetSurfaceIsRepoScopedOnly([call({ returns: 'a variable' })]),
      false,
      'a sentence that cannot say "the repository\'s own" fails',
    );
  });

  test('no declared call is a merge verb, and every forbidden one is refused', () => {
    assert.ok(fleetPlanHasNoMergeVerbs(FLEET_PLAN));
    assert.ok(fleetPlanHasNoMergeVerbs(FLEET_READS));
    assert.ok(fleetPlanHasNoMergeVerbs(FLEET_WRITES));

    const forbidden: FleetCall[] = [
      call({ what: 'merge it', method: 'PUT', path: '/repos/{owner}/{repo}/pulls/{name}/merge' }),
      call({ what: 'merge the base in', method: 'POST', path: '/repos/{owner}/{repo}/merges' }),
      call({ what: 'approve it', method: 'POST', path: '/repos/{owner}/{repo}/pulls/{name}/reviews' }),
      call({ what: 'freshen it', method: 'PUT', path: '/repos/{owner}/{repo}/pulls/{name}/update-branch' }),
      call({ what: 'list secrets', method: 'GET', path: '/repos/{owner}/{repo}/actions/secrets' }),
      call({ what: 'who can push', method: 'GET', path: '/repos/{owner}/{repo}/collaborators' }),
      call({ what: 'drop a switch', method: 'DELETE', path: '/repos/{owner}/{repo}/actions/variables/{name}' }),
      call({ what: 'escalate it', method: 'POST', path: '/repos/{owner}/{repo}/issues/{name}/labels' }),
      call({ what: 'un-escalate it', method: 'DELETE', path: '/repos/{owner}/{repo}/issues/{name}/labels/{file}' }),
    ];
    for (const one of forbidden) {
      assert.equal(fleetPlanHasNoMergeVerbs([one]), false, `${one.method} ${one.path} must be refused`);
      assert.equal(fleetPlanHasNoMergeVerbs([...FLEET_PLAN, one]), false, 'and refused inside a plan that is otherwise fine');
    }
    // Reading the labels that arrive on a pull request is how prStage works, so
    // the merge-verb guard allows a GET; the sub-root guard is what keeps the
    // issues API out, and asserting both is how the two stay distinct.
    const readLabels = call({ path: '/repos/{owner}/{repo}/issues/{name}/labels' });
    assert.ok(fleetPlanHasNoMergeVerbs([readLabels]), 'reading a label is not a merge verb');
    assert.equal(fleetSurfaceIsRepoScopedOnly([readLabels]), false, 'but the issues API is not a sub-root');
  });

  test("slice 2's new calls are in the plan, and their dangerous neighbours are not", () => {
    const repo = '/repos/bamr87/irony-works';
    // In: the five new reads.
    assert.ok(requestIsInPlan('GET', `${repo}/actions/variables?per_page=100`));
    assert.ok(requestIsInPlan('GET', `${repo}/actions/workflows?per_page=100`));
    assert.ok(requestIsInPlan('GET', `${repo}/actions/runs?per_page=20`));
    assert.ok(requestIsInPlan('GET', `${repo}/pulls?state=open&per_page=30`));
    assert.ok(requestIsInPlan('GET', `${repo}/contents/fleet.manifest.yml`));
    // In: the four new writes.
    assert.ok(requestIsInPlan('POST', `${repo}/actions/runs/9871/rerun`));
    assert.ok(requestIsInPlan('POST', `${repo}/actions/runs/9871/cancel`));
    assert.ok(requestIsInPlan('PUT', `${repo}/actions/workflows/germinate.yml/enable`));
    assert.ok(requestIsInPlan('PUT', `${repo}/actions/workflows/germinate.yml/disable`));

    // Out: a bigger page than the plan declares, for every list.
    assert.equal(requestIsInPlan('GET', `${repo}/actions/runs?per_page=100`), false, 'bounded means the number is the contract');
    assert.equal(requestIsInPlan('GET', `${repo}/actions/runs`), false, 'unbounded runs stay out');
    assert.equal(requestIsInPlan('GET', `${repo}/actions/runs?per_page=20&page=2`), false, 'and there is no pagination');
    assert.equal(requestIsInPlan('GET', `${repo}/pulls?state=all&per_page=30`), false);
    // Out: everything the never-merge guard names, at request level.
    assert.equal(requestIsInPlan('PUT', `${repo}/pulls/12/merge`), false, 'the console never merges');
    assert.equal(requestIsInPlan('POST', `${repo}/pulls/12/reviews`), false, 'and never approves');
    assert.equal(requestIsInPlan('PUT', `${repo}/pulls/12/update-branch`), false);
    assert.equal(requestIsInPlan('PUT', `${repo}/contents/README.md`), false, 'contents are read, never written');
    assert.equal(requestIsInPlan('DELETE', `${repo}/contents/README.md`), false);
    assert.equal(requestIsInPlan('GET', `${repo}/actions/secrets`), false, 'no secret is ever read');
    assert.equal(requestIsInPlan('DELETE', `${repo}/actions/runs/9871`), false, 'nothing is deleted');
  });

  test('{+path} spans segments, every other placeholder is one, and dot segments never match', () => {
    const repo = '/repos/bamr87/irony-works';
    assert.ok(requestIsInPlan('GET', `${repo}/contents/_data/ai_usage/summary.yml`), '{+path} is multi-segment');
    assert.ok(requestIsInPlan('GET', `${repo}/contents/.github/workflows`));
    assert.ok(requestIsInPlan('GET', `${repo}/contents/a/b/c/d/e/f.yml`));
    assert.equal(requestIsInPlan('GET', `${repo}/actions/variables/A/B`), false, 'a bare placeholder is one segment');
    assert.equal(requestIsInPlan('POST', `${repo}/actions/runs/9871/attempts/2/rerun`), false);
    // `{+path}` spans separators, so without a dot-segment refusal a contents
    // read could be normalized by fetch into an endpoint the plan never named.
    assert.equal(requestIsInPlan('GET', `${repo}/contents/../../../user`), false, 'a climb out is refused');
    assert.equal(requestIsInPlan('GET', `${repo}/contents/a/../../b`), false);
    assert.equal(requestIsInPlan('GET', `${repo}/contents/./x`), false);
    assert.ok(requestIsInPlan('GET', `${repo}/contents/.github/..hidden`), 'a dot inside a segment is not a dot segment');
    // A query may not be swallowed by a placeholder, which is what pins a page size.
    assert.equal(requestIsInPlan('GET', `${repo}/actions/variables/X?per_page=100`), false);
  });

  test('describeFleetPlan names pull requests and contents, and the boundary', () => {
    const text = describeFleetPlan();
    for (const one of FLEET_PLAN) {
      assert.ok(text.includes(`${one.method} ${one.path}`), one.path);
    }
    assert.ok(text.includes('No users, members, collaborators'));
    assert.match(text, /pull requests are listed and never/i);
    assert.match(text, /merged, approved, closed or relabelled/i);
    assert.match(text, /contents are read and\s+never written/i);
    assert.match(text, /nothing is ever deleted/i);
  });
});

// ---------------------------------------------------------------------------

interface Call {
  method: string;
  path: string;
  body: unknown;
}

/** A `fetch` that records every request and answers from a table. */
function recordingFetch(answers: Record<string, { status: number; body?: unknown }>, seen: Call[]): typeof fetch {
  return async (input, init) => {
    const url = new URL(String(input));
    const method = (init?.method ?? 'GET').toUpperCase();
    const at = `${url.pathname}${url.search}`;
    seen.push({ method, path: at, body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined });
    const answer = answers[`${method} ${at}`] ?? { status: 404 };
    return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
      status: answer.status,
      headers: { 'Content-Type': 'application/json' },
    });
  };
}

const R = '/repos/bamr87/irony-works';

const RUN_JSON = {
  id: 9871,
  name: 'germinate',
  path: '.github/workflows/germinate.yml',
  event: 'schedule',
  status: 'completed',
  conclusion: 'failure',
  html_url: 'https://github.com/bamr87/irony-works/actions/runs/9871',
  created_at: '2026-09-08T06:00:00Z',
  run_started_at: '2026-09-08T06:00:11Z',
  updated_at: '2026-09-08T06:04:00Z',
  run_attempt: 1,
};

const PULL_JSON = {
  number: 41,
  title: 'content(hack): the switch that never fired',
  draft: false,
  html_url: 'https://github.com/bamr87/irony-works/pull/41',
  updated_at: '2026-09-09T09:00:00Z',
  user: { login: 'github-actions[bot]' },
  labels: [{ name: 'auto:content' }, { name: 'source/germinate' }],
  head: { ref: 'germinate/20260909-0641', repo: { full_name: 'bamr87/irony-works' } },
  base: { ref: 'main', repo: { full_name: 'bamr87/irony-works' } },
};

const READ_ANSWERS: Record<string, { status: number; body?: unknown }> = {
  [`GET ${R}/actions/variables?per_page=100`]: {
    status: 200,
    body: { total_count: 2, variables: [{ name: 'GERMINATE_ENABLED', value: 'true' }, { name: 'AUTO_MERGE_ENABLED', value: 'false' }] },
  },
  [`GET ${R}/actions/workflows?per_page=100`]: {
    status: 200,
    body: { total_count: 1, workflows: [{ id: 12, name: 'germinate', path: '.github/workflows/germinate.yml', state: 'active' }] },
  },
  [`GET ${R}/actions/runs?per_page=20`]: { status: 200, body: { workflow_runs: [RUN_JSON, { name: 'no id' }] } },
  [`GET ${R}/pulls?state=open&per_page=30`]: { status: 200, body: [PULL_JSON, { title: 'no number' }] },
  [`GET ${R}/contents/_data/ai_usage/summary.yml`]: {
    status: 200,
    body: {
      type: 'file',
      path: '_data/ai_usage/summary.yml',
      sha: 'abc123',
      encoding: 'base64',
      content: Buffer.from('all_time:\n  cost_usd: 0.6397\n', 'utf8').toString('base64'),
    },
  },
  [`GET ${R}/contents/.github/workflows`]: {
    status: 200,
    body: [
      { type: 'file', name: 'germinate.yml', path: '.github/workflows/germinate.yml', sha: 'f1' },
      { type: 'dir', name: 'nested', path: '.github/workflows/nested', sha: 'd1' },
      { type: 'submodule', name: 'odd', path: '.github/workflows/odd', sha: 's1' },
    ],
  },
  [`GET ${R}`]: { status: 200, body: { default_branch: 'main' } },
};

suite('fleet slice 2: the client speaks the whole plan, and nothing else', () => {
  function clientOver(answers: Record<string, { status: number; body?: unknown }>, seen: Call[]): FleetClient {
    return githubFleetClient({
      repo: 'bamr87/irony-works',
      fetchImpl: recordingFetch(answers, seen),
      token: async () => 'tok',
    });
  }

  test('the new reads: variables, workflows, runs, pulls, a file and a directory', async () => {
    const seen: Call[] = [];
    const client = clientOver(READ_ANSWERS, seen);

    assert.deepEqual(await client.listVariables(), [
      { name: 'GERMINATE_ENABLED', value: 'true' },
      { name: 'AUTO_MERGE_ENABLED', value: 'false' },
    ]);
    assert.deepEqual(await client.listWorkflows(), [
      { id: 12, path: '.github/workflows/germinate.yml', name: 'germinate', state: 'active' },
    ]);
    assert.deepEqual(await client.recentRuns(), [
      {
        status: 'completed',
        conclusion: 'failure',
        url: 'https://github.com/bamr87/irony-works/actions/runs/9871',
        updatedAt: '2026-09-08T06:04:00Z',
        runId: 9871,
        name: 'germinate',
        path: '.github/workflows/germinate.yml',
        event: 'schedule',
        createdAt: '2026-09-08T06:00:00Z',
        runStartedAt: '2026-09-08T06:00:11Z',
        runAttempt: 1,
      },
    ], 'a run with no id is dropped rather than given a zero to cancel');
    const pulls = await client.openPulls();
    assert.equal(pulls.length, 1);
    assert.equal(pulls[0]?.number, 41);
    const file = await client.readFile('_data/ai_usage/summary.yml');
    assert.equal(file?.content, 'all_time:\n  cost_usd: 0.6397\n', 'base64 comes back decoded');
    assert.equal(file?.sha, 'abc123');
    assert.deepEqual((await client.listDir('.github/workflows')).map((e) => e.name), ['germinate.yml', 'nested']);
    assert.equal(await client.readFile('no/such.yml'), null, '404 is "not there", not an error');

    for (const request of seen) {
      assert.ok(requestIsInPlan(request.method, request.path), `${request.method} ${request.path} is off-plan`);
    }
    // "Nobody could ask" is not "there are none": a 403 on the variable list
    // must come back as null so the console draws unknown, never off.
    const denied: Call[] = [];
    const blind = clientOver({ [`GET ${R}/actions/variables?per_page=100`]: { status: 403 } }, denied);
    assert.equal(await blind.listVariables(), null);
    assert.deepEqual(await blind.listWorkflows(), [], 'a repository without Actions has no workflows, which is a real []');
    // A contents path that could climb out is refused before a socket opens.
    const climbed: Call[] = [];
    const climber = clientOver({}, climbed);
    await assert.rejects(climber.readFile('../../etc/passwd'), /not repository-relative/);
    assert.deepEqual(climbed, [], 'and nothing was sent');
  });

  test('the new writes: rerun, cancel, enable, disable', async () => {
    const seen: Call[] = [];
    const client = clientOver(
      {
        [`POST ${R}/actions/runs/9871/rerun`]: { status: 201 },
        [`POST ${R}/actions/runs/9871/cancel`]: { status: 202 },
        [`PUT ${R}/actions/workflows/12/enable`]: { status: 204 },
        [`PUT ${R}/actions/workflows/germinate.yml/disable`]: { status: 204 },
      },
      seen,
    );
    await client.rerunRun(9871);
    await client.cancelRun(9871);
    await client.setWorkflowEnabled('12', true);
    await client.setWorkflowEnabled('germinate.yml', false);
    assert.deepEqual(
      seen.map((r) => [r.method, r.path, r.body]),
      [
        ['POST', `${R}/actions/runs/9871/rerun`, undefined],
        ['POST', `${R}/actions/runs/9871/cancel`, undefined],
        ['PUT', `${R}/actions/workflows/12/enable`, undefined],
        ['PUT', `${R}/actions/workflows/germinate.yml/disable`, undefined],
      ],
      'each write is one request with no body, and enable/disable are two verbs not a flag',
    );
    for (const request of seen) {
      assert.ok(requestIsInPlan(request.method, request.path), `${request.method} ${request.path} is off-plan`);
    }
    const failing: Call[] = [];
    const sad = clientOver({ [`POST ${R}/actions/runs/1/cancel`]: { status: 409 } }, failing);
    await assert.rejects(sad.cancelRun(1), /GitHub POST .*cancel answered 409/);
  });
});

// ---------------------------------------------------------------------------

suite('fleet slice 2: the engines see a client that can only do what the plan allows', () => {
  const ENGINE_ANSWERS: Record<string, { status: number; body?: unknown }> = {
    ...READ_ANSWERS,
    [`GET ${R}/contents/README.md`]: {
      status: 200,
      body: { type: 'file', path: 'README.md', sha: 'r1', encoding: 'base64', content: Buffer.from('hi', 'utf8').toString('base64') },
    },
    [`GET ${R}/actions/variables/GERMINATE_ENABLED`]: { status: 200, body: { name: 'GERMINATE_ENABLED', value: 'true' } },
    [`PATCH ${R}/actions/variables/GERMINATE_ENABLED`]: { status: 204 },
    [`POST ${R}/actions/workflows/germinate.yml/dispatches`]: { status: 204 },
    [`POST ${R}/actions/runs/9871/rerun`]: { status: 201 },
    [`POST ${R}/actions/runs/9871/cancel`]: { status: 202 },
    [`PUT ${R}/actions/workflows/12/enable`]: { status: 204 },
  };
  const REF = { owner: 'bamr87', repo: 'irony-works' };

  test('twelve members are realised, and every request they make is in the plan', async () => {
    const seen: Call[] = [];
    const engines = engineClientOver(
      githubFleetClient({ repo: 'bamr87/irony-works', fetchImpl: recordingFetch(ENGINE_ANSWERS, seen), token: async () => 'tok' }),
      'bamr87/irony-works',
    );

    assert.equal((await engines.getFile(REF, 'README.md'))?.content, 'hi');
    assert.deepEqual((await engines.listDir(REF, '.github/workflows')).map((e) => e.type), ['file', 'dir']);
    assert.equal(await engines.getDefaultBranch(REF), 'main');
    const poll = await engines.listFactoryRuns(REF);
    assert.deepEqual(poll.runs.map((r) => [r.slug, r.runId, r.conclusion, r.htmlUrl.endsWith('/9871')]), [
      ['germinate', 9871, 'failure', true],
    ]);
    assert.deepEqual(
      [poll.etag, poll.notModified, poll.rateRemaining],
      [null, false, null],
      'no ETag and no rate header were read, and null says so rather than a number claiming otherwise',
    );
    assert.deepEqual((await engines.listFactoryRuns(REF, { pathPrefix: 'factory--' })).runs, [], 'pathPrefix filters');
    assert.deepEqual(await engines.listRepoWorkflows(REF), [
      { id: 12, name: 'germinate', path: '.github/workflows/germinate.yml', state: 'active', htmlUrl: '' },
    ]);
    await engines.dispatchWorkflow(REF, 'germinate.yml');
    await engines.cancelRun(REF, 9871);
    await engines.rerunRun(REF, 9871);
    await engines.setWorkflowEnabled(REF, 12, true);
    assert.deepEqual(await engines.listVariables(REF), [
      { name: 'GERMINATE_ENABLED', value: 'true' },
      { name: 'AUTO_MERGE_ENABLED', value: 'false' },
    ]);
    assert.deepEqual(await engines.getVariable(REF, 'GERMINATE_ENABLED'), { name: 'GERMINATE_ENABLED', value: 'true' });
    await engines.setVariable(REF, 'GERMINATE_ENABLED', 'true');

    assert.ok(seen.length >= ENGINE_CLIENT_REALISED.length, 'every realised member reached the network at least once');
    for (const request of seen) {
      assert.ok(requestIsInPlan(request.method, request.path), `${request.method} ${request.path} is off-plan`);
    }
    // A dispatch with no ref resolves the default branch first — one extra
    // declared read, never a guess at "main".
    assert.ok(seen.some((r) => r.method === 'POST' && r.path.endsWith('/dispatches') && JSON.stringify(r.body) === '{"ref":"main"}'));
  });

  test('the other ten refuse with 405 before a socket opens, and login is empty', async () => {
    const seen: Call[] = [];
    const engines = engineClientOver(
      githubFleetClient({ repo: 'bamr87/irony-works', fetchImpl: recordingFetch({}, seen), token: async () => 'tok' }),
      'bamr87/irony-works',
    );

    assert.equal(engines.login, '', 'GET /user is a person, and the plan is about a repository');
    assert.equal(ENGINE_CLIENT_REALISED.length, 12);
    assert.equal(ENGINE_CLIENT_REFUSED.length, 10);
    const members = Object.keys(engines).filter((key) => key !== 'login');
    assert.deepEqual(
      [...members].sort(),
      [...ENGINE_CLIENT_REALISED, ...ENGINE_CLIENT_REFUSED].sort(),
      'the adapter implements every member of the package contract — refusing is implementing',
    );

    // Proved from outside as well as inside: `seen` shows the injected fetch
    // was never called, and this shows no other fetch was either.
    const realFetch = globalThis.fetch;
    let outside = 0;
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      writable: true,
      value: () => {
        outside += 1;
        throw new Error('a refused member must not reach the network');
      },
    });

    const refusals: Array<[string, Promise<unknown>]> = [
      ['preflight', engines.preflight(REF)],
      ['putFile', engines.putFile(REF, 'a.md', 'x', 'msg')],
      ['deleteFile', engines.deleteFile(REF, 'a.md', 'sha', 'msg')],
      ['createBranch', engines.createBranch(REF, 'topic', 'main')],
      ['createPullRequest', engines.createPullRequest(REF, { title: 't', head: 'h', base: 'main' })],
      ['getActionsPublicKey', engines.getActionsPublicKey(REF)],
      ['hasSecret', engines.hasSecret(REF, 'ANTHROPIC_API_KEY')],
      ['putSecret', engines.putSecret(REF, 'ANTHROPIC_API_KEY', 'sealed', 'k1')],
      ['listRunJobs', engines.listRunJobs(REF, 9871)],
      ['createIssue', engines.createIssue(REF, { title: 't', body: 'b' })],
    ];
    try {
      for (const [member, promise] of refusals) {
        await assert.rejects(promise, (error: unknown) => {
          assert.ok(error instanceof Error);
          assert.equal(error.name, 'GithubError');
          assert.equal((error as Error & { status: number }).status, 405);
          assert.match(error.message, new RegExp(`GithubClient\\.${member} is not in FLEET_PLAN`));
          return true;
        }, member);
      }
    } finally {
      Object.defineProperty(globalThis, 'fetch', { configurable: true, writable: true, value: realFetch });
    }
    assert.deepEqual(seen, [], 'not one socket was opened');
    assert.equal(outside, 0, 'and none was opened around the injected fetch either');

    // A client bound to one repository never answers for another.
    await assert.rejects(
      engines.getFile({ owner: 'bamr87', repo: 'it-journey' }, 'README.md'),
      /bound to bamr87\/irony-works/,
    );
    // And it reads the default branch only, because that is the call the plan declares.
    await assert.rejects(engines.getFile(REF, 'README.md', 'some-branch'), /other than its default branch/);
    assert.deepEqual(seen, [], 'still not one socket');
  });
});

// ---------------------------------------------------------------------------

suite('fleet slice 2: the roster', () => {
  const registry = fs.readFileSync(path.join(FLEET_FIXTURES, 'projects.yml'), 'utf8');

  test("parseProjectsRegistry reads the hub's registry and drops what is archived", () => {
    const entries = parseProjectsRegistry(registry);
    const slugs = entries.map((e) => e.slug);
    assert.equal(entries.length, 38, '42 projects, less the four archived ones');
    assert.ok(slugs.includes('bamr87/lifehacker.dev'));
    assert.ok(slugs.includes('bamr87/it-journey'));
    assert.ok(slugs.includes('microsoft/skills'), 'an external repository is still a repository');
    for (const archived of ['bamr87/ai-seed', 'bamr87/wtd', 'bamr87/csv-vscoode', 'bamr87/zer0-pages-remote']) {
      assert.equal(slugs.includes(archived), false, `${archived} is archived and has no automation to operate`);
    }
    assert.equal(new Set(slugs.map((s) => s.toLowerCase())).size, slugs.length, 'deduped');
    assert.deepEqual(entries.find((e) => e.slug === 'bamr87/it-journey'), {
      slug: 'bamr87/it-journey',
      source: 'hub',
      localRoot: null,
      manifestPath: FLEET_MANIFEST_FILE,
      branch: 'main',
    });
    assert.ok(entries.every((e) => e.source === 'hub' && e.localRoot === null));
    assert.deepEqual(parseProjectsRegistry('not: a sequence\n'), [], 'a file that is not the registry yields nothing, not a throw');
    assert.deepEqual(parseProjectsRegistry(''), []);
  });

  test('parseRosterSetting keeps owner/name, tolerates a URL, and reports what it rejected', () => {
    const parsed = parseRosterSetting([
      'bamr87/it-journey',
      'https://github.com/bamr87/gitorio.git',
      'git@github.com:bamr87/zer0-mistakes.git',
      'bamr87/IT-Journey',
      'not a repo',
      '',
      'https://gitlab.com/bamr87/elsewhere',
    ]);
    assert.deepEqual(parsed.entries.map((e) => e.slug), [
      'bamr87/it-journey',
      'bamr87/gitorio',
      'bamr87/zer0-mistakes',
    ], 'a second casing of the same slug is one repository');
    assert.ok(parsed.entries.every((e) => e.source === 'settings' && e.branch === null && e.localRoot === null));
    assert.deepEqual(parsed.rejected, ['not a repo', '', 'https://gitlab.com/bamr87/elsewhere'],
      'a typo in a settings array is reported, because a silently missing row is a worse bug report');
  });

  test('mergeFleetRoster: workspace beats settings beats hub, whatever order they arrive in', () => {
    const workspace: FleetRosterEntry[] = [
      { slug: 'bamr87/lifehacker.dev', source: 'workspace', localRoot: '/w/lifehacker.dev', manifestPath: FLEET_MANIFEST_FILE, branch: null },
    ];
    const settings: FleetRosterEntry[] = [
      { slug: 'bamr87/LIFEHACKER.dev', source: 'settings', localRoot: null, manifestPath: FLEET_MANIFEST_FILE, branch: null },
      { slug: 'bamr87/gitorio', source: 'settings', localRoot: null, manifestPath: FLEET_MANIFEST_FILE, branch: null },
    ];
    const hub: FleetRosterEntry[] = [
      { slug: 'bamr87/lifehacker.dev', source: 'hub', localRoot: null, manifestPath: FLEET_MANIFEST_FILE, branch: 'main' },
      { slug: 'bamr87/gitorio', source: 'hub', localRoot: null, manifestPath: FLEET_MANIFEST_FILE, branch: 'main' },
      { slug: 'bamr87/it-journey', source: 'hub', localRoot: null, manifestPath: FLEET_MANIFEST_FILE, branch: 'main' },
    ];

    const merged = mergeFleetRoster(workspace, settings, hub);
    assert.deepEqual(merged.map((e) => [e.slug, e.source, e.localRoot, e.branch]), [
      ['bamr87/lifehacker.dev', 'workspace', '/w/lifehacker.dev', 'main'],
      ['bamr87/gitorio', 'settings', null, 'main'],
      ['bamr87/it-journey', 'hub', null, 'main'],
    ], 'first-appearance order, the highest-ranked record, and the branch upgraded from a loser that knew it');

    // Precedence is a property of the source, not of the argument order, so a
    // caller cannot demote its own checkout by passing it last.
    const reversed = mergeFleetRoster(hub, settings, workspace);
    assert.deepEqual(reversed.map((e) => [e.slug, e.source, e.localRoot]), [
      ['bamr87/lifehacker.dev', 'workspace', '/w/lifehacker.dev'],
      ['bamr87/gitorio', 'settings', null],
      ['bamr87/it-journey', 'hub', null],
    ]);
    assert.equal(merged.length, 3, 'bamr87/LIFEHACKER.dev is the same repository');
    assert.deepEqual(workspace[0]?.branch, null, 'the inputs are never mutated');
    assert.deepEqual(mergeFleetRoster(), []);
  });
});

// ---------------------------------------------------------------------------

suite('fleet slice 2: open pull requests', () => {
  test('coercePull takes what the list endpoint gives, and no merge state', () => {
    const pull = coercePull(PULL_JSON);
    assert.deepEqual(pull, {
      number: 41,
      title: 'content(hack): the switch that never fired',
      headRef: 'germinate/20260909-0641',
      labels: ['auto:content', 'source/germinate'],
      draft: false,
      authorLogin: 'github-actions[bot]',
      url: 'https://github.com/bamr87/irony-works/pull/41',
      updatedAt: '2026-09-09T09:00:00Z',
      sameRepoHead: true,
    });
    assert.equal(
      Object.keys(pull ?? {}).some((key) => /merge/i.test(key)),
      false,
      'the list endpoint omits mergeable, and asking per pull request is N calls — the console reports unknown instead',
    );
    const fork = coercePull({ ...PULL_JSON, head: { ref: 'patch-1', repo: { full_name: 'someone/irony-works' } } });
    assert.equal(fork?.sameRepoHead, false, "a fork's head is a different blast radius");
    const unreadable = coercePull({ ...PULL_JSON, head: { ref: 'patch-1' } });
    assert.equal(unreadable?.sameRepoHead, false, 'an unreadable base is not a licence to call a fork a branch');
    assert.equal(coercePull({ title: 'no number' }), undefined, 'a row that cannot be named cannot be acted on');
    assert.equal(coercePull(null), undefined);
    assert.deepEqual(
      coercePull({ number: 2, labels: ['bare', { name: 'shaped' }, 7, { colour: 'red' }] })?.labels,
      ['bare', 'shaped'],
      'a label is a string or a { name }; a number and a nameless object are neither, and a stage must not be derived from junk',
    );
  });

  test('prStage — transcribed from auto-merge.yml:77-82 and content-auto-merge.yml:135-148', () => {
    const cases: Array<[string[], boolean, string]> = [
      // content-auto-merge.yml:138 — draft first, and the API's own flag wins.
      [['auto:content'], true, 'draft'],
      // auto-merge.yml:80 / content-auto-merge.yml:140 — the escalation.
      [['needs-human'], false, 'needs-human'],
      [['auto:content', 'needs-human'], false, 'needs-human'],
      [['source/triage-bot', 'needs-human'], false, 'needs-human'],
      // auto-merge.yml:81-82 — the two data flavours, held to a tighter bar.
      [['source/triage-bot'], false, 'data-refresh'],
      [['source/ai-usage-bot'], false, 'data-refresh'],
      // auto-merge.yml:81 and content-auto-merge.yml:144-147 — the policies.
      [['auto:content'], false, 'auto-mergeable'],
      [['auto:issue'], false, 'auto-mergeable'],
      [['auto:content', 'source/content-scout'], false, 'auto-mergeable'],
      // content-auto-merge.yml:142 — the quest pair, and only the pair.
      [['quest-walkthrough', 'automated'], false, 'auto-mergeable'],
      [['quest-walkthrough'], false, 'unknown'],
      [['automated'], false, 'in-review'],
      // A lane opened it and no policy will merge it.
      [['source/site-explorer'], false, 'in-review'],
      [['source/ci-test'], false, 'in-review'],
      // Nobody said anything — usually a human's pull request.
      [[], false, 'unknown'],
      [['documentation'], false, 'unknown'],
    ];
    for (const [labels, draft, expected] of cases) {
      assert.equal(prStage(labels, draft), expected, `${JSON.stringify(labels)} draft=${draft}`);
    }

    // A repository may name its own stages, consulted before the shared
    // vocabulary — but never over draft or over an escalation. A file that could
    // paint a held pull request green would be the fleet's version of a
    // zer0.json arming a write.
    const local = { 'collection/hack': 'in-review', 'needs-human': 'auto-mergeable', 'auto:content': 'needs-human' } as const;
    assert.equal(prStage(['collection/hack', 'auto:content'], false, local), 'in-review', 'the local map wins over the shared one');
    assert.equal(prStage(['auto:content'], false, local), 'needs-human', 'and it may make a stage stricter');
    assert.equal(prStage(['needs-human', 'auto:content'], false, local), 'needs-human', 'but it cannot repaint an escalation');
    assert.equal(prStage(['auto:content'], true, local), 'draft', 'and it cannot repaint a draft');
    assert.equal(prStage(['toString'], false, {}), 'unknown', 'an inherited property is not a mapping');
  });

  test('attributePulls joins by source label, then branch prefix, and keeps the rest visible', () => {
    const lanes = fixtureManifest().lanes;
    const pull = (number: number, labels: string[], headRef: string): FleetPull => ({
      number,
      title: `#${number}`,
      headRef,
      labels,
      draft: false,
      authorLogin: 'github-actions[bot]',
      url: `https://github.com/bamr87/irony-works/pull/${number}`,
      updatedAt: '2026-09-09T09:00:00Z',
      sameRepoHead: true,
    });
    const pulls = [
      pull(1, ['source/germinate'], 'anything/at-all'),
      pull(2, [], 'germinate/20260909-0641'),
      pull(3, ['source/germinate-bot'], 'x/y'),
      pull(4, ['source/alanis-gate', 'auto:content'], 'gate/1'),
      pull(5, ['source/site-explorer'], 'explorer/20260909'),
      pull(6, [], 'dependabot-npm-and-yarn'),
      pull(7, ['auto:content'], 'germinate/20260910-0641'),
    ];

    const { byLane, unattributed } = attributePulls(pulls, lanes);
    assert.deepEqual([...byLane.keys()].sort(), ['alanis-gate', 'germinate']);
    assert.deepEqual(byLane.get('germinate')?.map((p) => p.number), [1, 2, 3, 7], 'label first, then the branch prefix');
    assert.deepEqual(byLane.get('alanis-gate')?.map((p) => p.number), [4]);
    assert.deepEqual(
      unattributed.map((p) => p.number),
      [5, 6],
      'lifehacker labels the explore lane source/site-explorer and branches it explorer/ — neither is the lane id, ' +
        'so it stays visible as unattributed rather than being guessed onto a plausible lane',
    );
    const seen = [...byLane.values()].flat().length + unattributed.length;
    assert.equal(seen, pulls.length, 'every pull request appears exactly once');
    assert.deepEqual(attributePulls(pulls, []).unattributed.length, pulls.length, 'with no lanes, nothing is dropped');
    assert.deepEqual(attributePulls([], lanes), { byLane: new Map(), unattributed: [] });
  });
});

// ---------------------------------------------------------------------------

suite('fleet slice 2: cost and the merge policy', () => {
  // Transcribed from bamr87/lifehacker.dev `_data/ai_usage/summary.yml`, which
  // `scripts/ai/usage_ledger.rb` generates: all dollars are API-equivalent, and
  // the per-workflow rollup carries no window but "since the beginning".
  const SUMMARY = [
    "generated_at: '2026-07-15T02:55:35Z'",
    'records: 1',
    'all_time:',
    '  calls: 1',
    '  cost_usd: 0.6397',
    'last_30d:',
    '  calls: 1',
    '  cost_usd: 0.6397',
    'last_7d:',
    '  calls: 1',
    '  cost_usd: 0.6397',
    'by_workflow:',
    '- workflow: pipeline',
    '  calls: 1',
    '  cost_usd: 0.6397',
    '- workflow: germinate',
    '  calls: 4',
    '  cost_usd: 2.5',
    'by_role:',
    '- role: content-reviewer',
    '  calls: 1',
    '  cost_usd: 0.6397',
    '',
  ].join('\n');

  test('parseUsageSummary reads the rollup, and absent stays null', () => {
    const summary = parseUsageSummary(SUMMARY);
    assert.ok(summary !== null);
    assert.deepEqual(summary.byWorkflow, [
      { workflow: 'pipeline', runs: 1, costUsd: 0.6397 },
      { workflow: 'germinate', runs: 4, costUsd: 2.5 },
    ]);
    assert.deepEqual(summary.byRole, [{ role: 'content-reviewer', runs: 1, costUsd: 0.6397 }]);
    assert.deepEqual(
      [summary.allTimeUsd, summary.last30dUsd, summary.last7dUsd],
      [0.6397, 0.6397, 0.6397],
    );

    // A repository that has never run the ledger has no usage file, and a file
    // that says nothing about cost is the same answer as no file at all.
    assert.equal(parseUsageSummary("generated_at: '2026-07-15T02:55:35Z'\n"), null);
    assert.equal(parseUsageSummary(''), null);
    const windowless = parseUsageSummary('by_workflow:\n- workflow: pipeline\n  calls: 2\n');
    assert.ok(windowless !== null);
    assert.deepEqual(
      [windowless.allTimeUsd, windowless.last30dUsd, windowless.last7dUsd],
      [null, null, null],
      '"nobody measured" is null — a zero in a cost column reads as "this was free"',
    );
    assert.deepEqual(windowless.byWorkflow, [{ workflow: 'pipeline', runs: 2, costUsd: 0 }]);
  });

  test('costByLane joins by workflow name and reports the all_time window', () => {
    const manifest = fixtureManifest();
    const summary = parseUsageSummary(SUMMARY);
    assert.ok(summary !== null);

    // The ledger is keyed by the workflow's NAME; a lane names a PATH. The
    // repository's own workflow list is the bridge.
    const names = new Map([['.github/workflows/germinate.yml', 'germinate']]);
    const costs = costByLane(summary, manifest, names);
    assert.deepEqual([...costs.keys()], ['germinate']);
    assert.deepEqual(costs.get('germinate'), {
      laneId: 'germinate',
      workflowName: 'germinate',
      runs: 4,
      costUsd: 2.5,
      window: 'all_time',
      note: 'API-equivalent',
    });
    assert.equal(
      costs.has('alanis-gate'),
      false,
      'a lane nobody could join is absent, not a LaneCost full of zeroes — the caller renders absent as unknown',
    );
    assert.deepEqual(
      [...costByLane(summary, manifest, new Map([['germinate.yml', 'germinate']])).keys()],
      ['germinate'],
      'a filename-keyed map works too',
    );
    assert.deepEqual(
      [...costByLane(summary, manifest, new Map([['.github/workflows/alanis-gate.yml', 'alanis-gate']])).keys()],
      [],
      'a workflow with a name but no ledger row is still "nobody measured"',
    );
    assert.deepEqual([...costByLane(summary, manifest, new Map()).keys()], []);
  });

  test('mergePolicyOf reports the three switches, and unknown where nobody asked', () => {
    const blind = mergePolicyOf(new Map());
    assert.deepEqual(blind.switches, {
      AUTO_MERGE_ENABLED: 'unknown',
      AUTO_UPDATE_ENABLED: 'unknown',
      AUTO_FIX_ENABLED: 'unknown',
    }, 'the console cannot toggle these, so the least it can do is not guess them');
    assert.equal(describeMergePolicy(blind), 'merge policy unknown — nobody has read these variables');

    const read = mergePolicyOf(
      new Map([
        ['AUTO_MERGE_ENABLED', 'true' as const],
        ['AUTO_FIX_ENABLED', 'false' as const],
        ['GERMINATE_ENABLED', 'true' as const],
      ]),
    );
    assert.deepEqual(read.switches, {
      AUTO_MERGE_ENABLED: 'true',
      AUTO_UPDATE_ENABLED: 'unknown',
      AUTO_FIX_ENABLED: 'false',
    });
    assert.equal(describeMergePolicy(read), 'armed: AUTO_MERGE_ENABLED; unknown: AUTO_UPDATE_ENABLED');

    const off = mergePolicyOf(
      new Map([
        ['AUTO_MERGE_ENABLED', 'unset' as const],
        ['AUTO_UPDATE_ENABLED', 'false' as const],
        ['AUTO_FIX_ENABLED', 'false' as const],
      ]),
    );
    assert.equal(describeMergePolicy(off), 'nothing merges without a human', 'unset is a real answer: the workflow gate holds it off');
  });
});

// ---------------------------------------------------------------------------

suite('fleet slice 2: the blocker order slice 2 must append to', () => {
  test('the pinned order is unchanged, and a new kind belongs after it', () => {
    // Slice 2 adds three modes (`rerun`, `cancel`, `toggleWorkflow`) and three
    // kinds (`noRetryableRun`, `noRunInProgress`, `workflowUnknown`) to
    // `src/core/fleet/fleet.ts` — a foundation hunk, made by the integration
    // work package rather than here. This test pins what that hunk must not
    // disturb: the eight-blocker order the toggle and dispatch modes report,
    // and the fact that `guardrailViolation` is last, so an appended kind is
    // appended and never inserted among the eight.
    const manifest = fixtureManifest();
    const rogue: FleetManifest = {
      ...manifest,
      lanes: [
        {
          id: 'bad',
          kind: 'other',
          harness: 'none',
          implementation: '',
          description: 'bad',
          triggers: [],
          switch: null,
          usesTokens: [],
          guardrails: { neverMerges: false, opensPullRequests: null, writesDirectlyToDefaultBranch: true, writablePaths: [] },
        },
      ],
    };
    const base: FleetGateInput = {
      workspaceRoot: '',
      enabled: false,
      dispatchAllow: false,
      hasCredential: false,
      manifest: rogue,
      laneId: 'bad',
    };
    assert.deepEqual(evaluateFleetGates('toggle', base).map((b) => b.kind), [
      'noWorkspace',
      'dispatchDisabled',
      'noCredential',
      'laneHasNoSwitch',
      'guardrailViolation',
    ]);
    assert.deepEqual(evaluateFleetGates('dispatch', base).map((b) => b.kind), [
      'noWorkspace',
      'dispatchDisabled',
      'noCredential',
      'laneNotDispatchable',
      'guardrailViolation',
    ]);
    for (const mode of ['toggle', 'dispatch'] as const) {
      const blockers = evaluateFleetGates(mode, base);
      assert.equal(blockers[blockers.length - 1]?.kind, 'guardrailViolation', `${mode}: append after this one`);
    }
    // Scaffold keeps its own list, and its five kinds already sit after the
    // eight in `FleetBlockerKind` — the same place slice 2's three go.
    const scaffoldOrder = evaluateFleetGates('scaffold', {
      ...base,
      enabled: false,
      scaffoldAllow: false,
      scaffold: {
        laneId: 'germinate',
        workflowPath: '.github/workflows/germinate.yml',
        workflowExists: true,
        switchName: 'GERMINATE_ENABLED',
        switchTaken: true,
        notExpressibleReasons: ['needs a dynamic matrix'],
      },
      manifest,
    }).map((b) => b.kind);
    assert.deepEqual(scaffoldOrder, [
      'noWorkspace',
      'dispatchDisabled',
      'scaffoldDisabled',
      'laneExists',
      'workflowFileExists',
      'switchNameTaken',
      'notExpressible',
    ]);
  });
});
