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
  FLEET_MANIFEST_FILE,
  FLEET_PLAN,
  FLEET_READS,
  FLEET_WRITES,
  buildLaneStates,
  coerceFleetManifest,
  describeFleetPlan,
  describeGuardrails,
  describeTriggers,
  evaluateFleetGates,
  fleetBlockerSummary,
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
  type FleetGateInput,
  type FleetManifest,
} from '../core';

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
    assert.equal(FLEET_READS.length, 3);
    assert.equal(FLEET_WRITES.length, 3);
    assert.equal(FLEET_PLAN.length, 6);
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
    assert.equal(requestIsInPlan('GET', '/repos/bamr87/irony-works/actions/variables'), false, 'listing is not in the plan');
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
