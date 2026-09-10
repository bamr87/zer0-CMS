/**
 * The engines seam, the adapters over it, and the three readers beside them.
 *
 * Two kinds of test live here and it is worth knowing which is which.
 *
 * **Layering tests** prove the rule rather than describe it: that exactly one
 * file imports `@bamr87/fleet-engines` (found by grepping `src/` from inside the
 * test, so a second importer fails here rather than in a build log), that the
 * core barrel never re-exports a package name, and that `dist/mcp-server.js`
 * contains neither the package nor the `yaml` it drags in. The bundle test reads
 * esbuild's metafile and SKIPS with a note when `out/meta.json` is absent, so the
 * plain-Mocha fast loop stays green without a build.
 *
 * **Reality tests** run over verbatim copies of other repositories' committed
 * files (`src/test/fixtures/fleet/`, provenance in its `FIXTURE-SOURCES.md`).
 * Every drift row asserted below was found in real bytes, not invented: a lane
 * that promises it opens no pull requests and opens pull requests, a manifest
 * that names a kill switch its workflow does not read, a schedule the workflow
 * commented out months ago. And the parity suite records something nobody wanted
 * to find — four of the seven committed manifests in this fleet are not valid
 * YAML, and the package's parser answers them with an empty manifest whose
 * `skipped` count is zero.
 *
 * No network, no writes, and the only files read are fixtures and build output.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as path from 'node:path';

import {
  ENGINES_VERSION,
  ENGINE_LANE_KINDS,
  AUDIT_RULES,
  attachLanes,
  auditRepo,
  buildFleet,
  engineParseFleetManifest,
  engineYamlDump,
  extractFacts,
  parseRepo,
  parseRosterText,
  parseWorkflow,
  toFleetManifestYaml,
  type WorkflowFacts,
} from '../core/fleet/engines';
import {
  HARNESS_REGISTRY_SCHEMA,
  fromEngineLane,
  gitFactoryLink,
  inspectWorkspaceFleet,
  manifestDrift,
  parseFleetManifest,
  readHarnessRegistry,
  registryRepoFor,
  registryWasRefused,
  runnerShapeOf,
  runsToFactoryRuns,
  toEngineLane,
  toEngineManifest,
  type FleetLane,
  type FleetManifest,
  type FleetRunRecord,
  type WorkspaceFleetIo,
} from '../core';
import * as core from '../core';

const SRC = path.resolve(__dirname, '../../src');
const FLEET_FIXTURES = path.join(SRC, 'test/fixtures/fleet');
const MANIFESTS = path.join(FLEET_FIXTURES, 'manifests');
const WORKFLOWS = path.join(FLEET_FIXTURES, 'workflows');
const GOLDEN = path.join(SRC, 'test/fixtures/golden/engines');
const META = path.resolve(__dirname, '../../out/meta.json');

/**
 * An `import … from` / `export … from` / `import()` of the package. Matching the
 * statement rather than the bare string is deliberate: several files name the
 * package in prose, and this file names it in this very regex.
 */
const PACKAGE_IMPORT = /(?:from|import\()\s*['"]@bamr87\/fleet-engines['"]/;

function read(file: string): string {
  return fs.readFileSync(file, 'utf8');
}

function manifestText(name: string): string {
  return read(path.join(MANIFESTS, `${name}.fleet.manifest.yml`));
}

function ourManifest(name: string): FleetManifest {
  const parsed = parseFleetManifest(manifestText(name));
  assert.ok(parsed.manifest !== null, `${name}: ${parsed.reason ?? ''}`);
  return parsed.manifest;
}

/** Every `.ts` under `src/`, so a layering test can read the tree itself. */
function everyTsFile(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      everyTsFile(full, out);
    } else if (entry.isFile() && entry.name.endsWith('.ts')) {
      out.push(full);
    }
  }
  return out;
}

/** The workflow fixtures of one repository, as `.github/workflows/<file>`. */
function workflowsOf(repo: string): Array<{ rel: string; text: string }> {
  const dir = path.join(WORKFLOWS, repo);
  return fs
    .readdirSync(dir)
    .filter((file) => file.endsWith('.yml'))
    .sort()
    .map((file) => ({ rel: `.github/workflows/${file}`, text: read(path.join(dir, file)) }));
}

function factsOf(repo: string, file: string): WorkflowFacts {
  const rel = `.github/workflows/${file}`;
  return extractFacts(rel, read(path.join(WORKFLOWS, repo, file)));
}

/** An `io` for `inspectWorkspaceFleet` over one repository's fixture folder. */
function fixtureIo(repo: string): WorkspaceFleetIo {
  const dir = path.join(WORKFLOWS, repo);
  return {
    listWorkflows: () =>
      Promise.resolve(
        fs
          .readdirSync(dir)
          .filter((file) => file.endsWith('.yml'))
          .map((file) => `.github/workflows/${file}`),
      ),
    readFile: (rel) => Promise.resolve(read(path.join(dir, path.basename(rel)))),
    engines: { parseWorkflow, extractFacts, buildFleet, attachLanes, auditRepo },
  };
}

/** `true` when the goldens on disk were produced by the installed engines. */
function goldensAreCurrent(): boolean {
  const stamp = path.join(GOLDEN, 'ENGINES_VERSION');
  return fs.existsSync(stamp) && read(stamp).trim() === ENGINES_VERSION;
}

// ---------------------------------------------------------------------------

suite('engines: the seam holds', () => {
  test('exactly one file in src/ imports the package', () => {
    const importers = everyTsFile(SRC)
      .filter((file) => PACKAGE_IMPORT.test(read(file)))
      .map((file) => path.relative(SRC, file).split(path.sep).join('/'));

    assert.deepEqual(
      importers.sort(),
      ['core/fleet/engines.ts'],
      'Only src/core/fleet/engines.ts may import @bamr87/fleet-engines (CLAUDE.md, decision D14). ' +
        'Everything else takes the engine result as a parameter or converts through core/fleet/adapters.ts.',
    );
  });

  test('the core barrel re-exports no package name, and not the seam', () => {
    const barrelSource = read(path.join(SRC, 'core/index.ts'));
    const active = barrelSource
      .split('\n')
      .filter((line) => line.trimStart().startsWith('export'))
      .join('\n');
    assert.ok(
      !active.includes('./fleet/engines'),
      'core/index.ts must never export ./fleet/engines — the barrel is what src/mcp imports through.',
    );

    // The four modules this work package added ARE on the barrel: they import
    // the package's *types* only, and `import type` is erased before esbuild
    // resolves anything.
    for (const module of ['./fleet/adapters', './fleet/registry', './fleet/handoff', './fleet/inspect']) {
      assert.ok(active.includes(`'${module}'`), `core/index.ts should export ${module}`);
    }

    // Spread rather than indexed directly, because `core['extractFacts']` would
    // not even compile — which is the first half of the guarantee. This is the
    // second half: the name is absent at runtime too.
    const barrel: Record<string, unknown> = { ...core };
    // Names the package exports that this repository also declares, or that
    // would be ambiguous on a star export. None may reach the barrel.
    for (const name of [
      'extractFacts',
      'parseWorkflow',
      'buildFleet',
      'attachLanes',
      'AUDIT_RULES',
      'auditRepo',
      'gradeFor',
      'LANE_KINDS',
      'laneForPath',
      'parseRosterText',
      'mergeRoster',
      'toFleetManifestYaml',
      'yamlDump',
      'parseRepo',
      'GithubError',
      'harnessHealth',
      'readHub',
    ]) {
      assert.equal(barrel[name], undefined, `core barrel must not re-export ${name}`);
    }

    // And the name they DO share resolves to this repository's reader, which
    // answers `{manifest, reason}` rather than the package's bare manifest.
    const parsed = (barrel.parseFleetManifest as typeof parseFleetManifest)('spec_version: nope\n');
    assert.equal(parsed.manifest, null);
    assert.match(parsed.reason ?? '', /is not fleet\/v1/);
  });

  test('dist/mcp-server.js contains neither the package nor yaml', function () {
    if (!fs.existsSync(META)) {
      // The fast loop (`tsc -p . --outDir out` + mocha) never runs esbuild, and
      // a bundle assertion that fails for want of a bundle teaches nobody
      // anything. Run `node esbuild.js` to arm this test.
      this.skip();
      return;
    }
    const meta = JSON.parse(read(META)) as {
      outputs: Record<string, { inputs: Record<string, unknown> }>;
    };
    const mcp = Object.keys(meta.outputs).find(
      (out) => out.endsWith('mcp-server.js') && !out.endsWith('.map'),
    );
    assert.ok(mcp !== undefined, 'out/meta.json has no dist/mcp-server.js output');
    const inputs = Object.keys(meta.outputs[mcp]?.inputs ?? {});

    const leaked = inputs.filter((input) => /fleet-engines|node_modules\/yaml/.test(input));
    assert.deepEqual(
      leaked,
      [],
      'dist/mcp-server.js must bundle no third-party package (decision D14). ' +
        'Something under src/mcp reached core/fleet/engines.ts, directly or through the barrel.',
    );

    // And prove the assertion is not vacuous: the barrel really does pull the
    // type-only adapters into the MCP graph, so "no package files" is a result
    // rather than an absence.
    assert.ok(
      inputs.some((input) => input.endsWith('src/core/fleet/adapters.ts')),
      'expected the MCP bundle to include core/fleet/adapters.ts through the barrel',
    );
  });

  test('ENGINES_VERSION resolves without an esbuild define', () => {
    // The fast loop compiles with tsc, which has no `define`, so this value came
    // from the installed package.json — the fallback path in engines.ts.
    const installed = JSON.parse(
      read(path.resolve(__dirname, '../../node_modules/@bamr87/fleet-engines/package.json')),
    ) as { version: string };
    assert.equal(ENGINES_VERSION, installed.version);
    assert.match(ENGINES_VERSION, /^\d+\.\d+\.\d+/);
    assert.notEqual(ENGINES_VERSION, '0.0.0-dev', 'the last-resort fallback should not be in play');
  });

  test('the rulebook has 15 rules — GitFactory vendors 16', () => {
    // The package README claims GitFactory and this console run "the same code".
    // They do not: GitFactory's vendored copy added a sixteenth rule,
    // `vendored-runner` (ADR-037), which the published package has never
    // carried. Pinning 15 here is what turns that divergence into a visible
    // event the next time either side moves.
    assert.equal(AUDIT_RULES.length, 15);
    const ids = AUDIT_RULES.map((rule) => rule.id);
    assert.equal(new Set(ids).size, 15, 'audit rule ids must be unique');
    assert.ok(!ids.includes('vendored-runner'), "the package must not have grown GitFactory's rule");
    for (const rule of AUDIT_RULES) {
      assert.ok(['fail', 'warn', 'info'].includes(rule.severity), `${rule.id} severity`);
      assert.notEqual(rule.standard.trim(), '', `${rule.id} must state its standard`);
    }
    assert.deepEqual([...ENGINE_LANE_KINDS].sort(), [
      'analysis',
      'content',
      'fanout',
      'maintenance',
      'mention',
      'orchestrator',
      'other',
      'review',
      'triage',
    ]);
  });
});

// ---------------------------------------------------------------------------

suite('engines: our parser against the package parser, over seven committed manifests', () => {
  /** The three the `yaml` package can read. Everything must agree, field by field. */
  const READABLE = ['lifehacker', 'irony-works'] as const;
  const WORKSPACE_FIXTURE = path.join(SRC, 'test/fixtures/workspace/fleet.manifest.yml');

  test('parity on every manifest the package can parse', () => {
    const texts: Array<[string, string]> = [
      ...READABLE.map((name): [string, string] => [name, manifestText(name)]),
      // The seventh: an older irony-works manifest, committed here as the
      // fixture workspace's fleet since the Fleet console landed.
      ['workspace-fixture', read(WORKSPACE_FIXTURE)],
    ];

    for (const [name, text] of texts) {
      const ours = parseFleetManifest(text);
      const theirs = engineParseFleetManifest(text);
      assert.ok(ours.manifest !== null, `${name}: our parser refused — ${ours.reason ?? ''}`);

      assert.equal(ours.manifest.specVersion, theirs.spec_version, `${name}: spec_version`);
      assert.equal(ours.manifest.repo, theirs.repo, `${name}: repo`);
      assert.equal(ours.manifest.provenance, theirs.provenance, `${name}: provenance`);
      assert.equal(ours.manifest.summary, theirs.summary, `${name}: summary`);
      assert.equal(ours.manifest.lanes.length, theirs.lanes.length, `${name}: lane count`);

      const byId = new Map(theirs.lanes.map((lane) => [lane.id, lane]));
      for (const lane of ours.manifest.lanes) {
        const other = byId.get(lane.id);
        assert.ok(other !== undefined, `${name}: the package lost lane ${lane.id}`);
        assert.equal(lane.harness, other.harness, `${name}/${lane.id}: harness`);
        assert.equal(lane.implementation, other.implementation, `${name}/${lane.id}: implementation`);
        assert.equal(lane.switch, other.switch, `${name}/${lane.id}: switch`);
        assert.deepEqual(lane.usesTokens, other.uses_tokens, `${name}/${lane.id}: uses_tokens`);
        assert.equal(lane.kind, other.kind, `${name}/${lane.id}: kind`);
        assert.deepEqual(
          lane.triggers.map((t) => t.kind),
          other.triggers.map((t) => t.kind),
          `${name}/${lane.id}: trigger kinds`,
        );
        // Guardrails agree WHERE OURS SAID. Ours keeps `null` for "the manifest
        // did not say"; the package has already defaulted that to `true`, which
        // is the whole reason `toEngineLane` records a loss.
        if (lane.guardrails.neverMerges !== null) {
          assert.equal(
            lane.guardrails.neverMerges,
            other.guardrails.never_merges,
            `${name}/${lane.id}: never_merges`,
          );
        }
        if (lane.guardrails.opensPullRequests !== null) {
          assert.equal(
            lane.guardrails.opensPullRequests,
            other.guardrails.opens_pull_requests,
            `${name}/${lane.id}: opens_pull_requests`,
          );
        }
      }
    }

    // The manifest-level token contract is ours alone: the package's manifest
    // shape has no field for it, which is why `toEngineManifest` reports it.
    const lifehacker = ourManifest('lifehacker');
    assert.equal(lifehacker.lanes.length, 17);
    assert.equal(lifehacker.tokens.length, 7);
    assert.ok(!('tokens' in engineParseFleetManifest(manifestText('lifehacker'))));
  });

  test('FINDING: four committed manifests are invalid YAML, and the package fails silently', () => {
    // `wtd fleet adopt` wraps a single-quoted scalar at column 80 and writes the
    // continuation at column 0 — outside the block's indentation:
    //
    //     purpose: 'Preferred Claude auth (house convention: OAuth first). Produced by
    //   `claude setup-token`.'
    //
    // The `yaml` package throws on it, and the engines' parser answers a throw
    // with an EMPTY manifest whose `skipped` is 0 — so a consumer cannot even
    // tell it failed. This repository's tolerant reader parses all four. That is
    // the case for keeping our own parser (decision D-A), stated as a test
    // rather than as a paragraph.
    const broken: Array<[string, number]> = [
      ['it-journey', 15],
      ['zer0-mistakes', 6],
      ['ai-world-view', 5],
      ['zer0-cms', 1],
    ];

    for (const [name, ourLaneCount] of broken) {
      const text = manifestText(name);
      assert.ok(
        /\n`claude setup-token`\.'/.test(text),
        `${name}: expected the unindented continuation line that breaks the YAML`,
      );

      const theirs = engineParseFleetManifest(text);
      assert.deepEqual(theirs.lanes, [], `${name}: the package should read no lanes`);
      assert.equal(theirs.spec_version, '', `${name}: the package should read no spec_version`);
      assert.equal(theirs.skipped, 0, `${name}: and it reports nothing skipped — the silent part`);

      const ours = parseFleetManifest(text);
      assert.ok(ours.manifest !== null, `${name}: our parser should read it anyway`);
      assert.equal(ours.manifest.specVersion, 'fleet/v1', `${name}: spec_version`);
      assert.equal(ours.manifest.lanes.length, ourLaneCount, `${name}: lane count`);
    }
  });
});

// ---------------------------------------------------------------------------

suite('engines: the adapters, and what does not survive the trip', () => {
  /** A lane that says everything the engine lane shape is able to hold. */
  function fullyStatedLane(): FleetLane {
    return {
      id: 'content-factory',
      kind: 'content',
      harness: 'claude-cli',
      implementation: '.github/workflows/content-factory.yml',
      description: 'content-factory',
      triggers: [
        { kind: 'schedule', cron: '0 9 * * *', events: [] },
        { kind: 'dispatch', cron: null, events: [] },
        { kind: 'event', cron: null, events: ['pull_request'] },
      ],
      switch: 'CONTENT_FACTORY_ENABLED',
      usesTokens: ['ANTHROPIC_API_KEY', 'FLEET_TOKEN'],
      guardrails: {
        neverMerges: true,
        opensPullRequests: true,
        writesDirectlyToDefaultBranch: null,
        writablePaths: ['pages/_posts/'],
      },
    };
  }

  test('a guardrail the manifest did not state crosses as a LOSS, never as false', () => {
    const silent: FleetLane = {
      ...fullyStatedLane(),
      kind: 'wire-desk', // free vocabulary in fleet/v1, closed in the package
      guardrails: {
        neverMerges: null,
        opensPullRequests: null,
        writesDirectlyToDefaultBranch: false,
        writablePaths: [],
      },
      triggers: [{ kind: 'schedule', cron: null, events: [] }],
    };

    const { lane, losses } = toEngineLane(silent);

    // The load-bearing assertion: silence became the package's optimistic
    // default, and the default was WRITTEN DOWN.
    assert.equal(lane.guardrails.never_merges, true);
    const neverMerges = losses.find((loss) => loss.field === 'guardrails.never_merges');
    assert.ok(neverMerges !== undefined, 'an unstated never_merges must be recorded as a loss');
    assert.match(neverMerges.note, /did not say/);
    assert.equal(neverMerges.laneId, silent.id);

    // It is never reported as `false`. "We did not check" and "it merges" are
    // different sentences and the console shows different ones.
    assert.notEqual(lane.guardrails.never_merges, false);

    // The three other things the shape cannot hold, each recorded the same way.
    assert.deepEqual(
      losses.map((loss) => loss.field).sort(),
      [
        'guardrails.never_merges',
        'guardrails.writes_directly_to_default_branch',
        'kind',
        'triggers[].cron',
      ],
    );
    assert.equal(lane.kind, 'other');
    assert.equal(lane.triggers[0]?.kind, 'schedule');
    assert.equal(lane.guardrails.opens_pull_requests, undefined, 'an unstated claim is omitted');
    assert.equal(lane.guardrails.writable_paths, undefined);
  });

  test('a lane that said everything round-trips unchanged, and loses nothing', () => {
    const lane = fullyStatedLane();
    const { lane: crossed, losses } = toEngineLane(lane);
    assert.deepEqual(losses, [], 'a fully-stated, engine-expressible lane should lose nothing');
    assert.deepEqual(fromEngineLane(crossed), lane);

    // Stability under a second trip: the conversion is idempotent, not merely
    // lossless once.
    assert.deepEqual(fromEngineLane(toEngineLane(fromEngineLane(crossed)).lane), lane);

    // And the one field that genuinely cannot round-trip says so out loud.
    const claiming: FleetLane = {
      ...lane,
      guardrails: { ...lane.guardrails, writesDirectlyToDefaultBranch: false },
    };
    const dropped = toEngineLane(claiming).losses;
    assert.deepEqual(dropped.map((loss) => loss.field), [
      'guardrails.writes_directly_to_default_branch',
    ]);
    assert.equal(fromEngineLane(toEngineLane(claiming).lane).guardrails.writesDirectlyToDefaultBranch, null);
  });

  test('a whole real manifest crosses, and reports what the package cannot hold', () => {
    const manifest = ourManifest('lifehacker');
    const { manifest: crossed, losses } = toEngineManifest(manifest);

    assert.equal(crossed.spec_version, 'fleet/v1');
    assert.equal(crossed.repo, 'bamr87/lifehacker.dev');
    assert.equal(crossed.lanes.length, 17);
    assert.equal(crossed.skipped, 0);

    // lifehacker's 17 lanes all state `never_merges`, so no lane-level loss —
    // the losses are the three whole sections the package's manifest shape has
    // no field for.
    assert.deepEqual(
      losses.map((loss) => `${loss.laneId}:${loss.field}`).sort(),
      [':agents/skills', ':tokens'],
    );
    assert.match(losses.find((loss) => loss.field === 'tokens')?.note ?? '', /7 entries/);

    // A metering block would be reported the same way. None of the seven
    // committed manifests has one at the document root — irony-works writes its
    // prices and ledger paths INSIDE a lane instead, so the spec's top-level
    // `metering:` is, across this whole fleet, unused. The branch is still
    // covered, because the day somebody writes one the console must say the
    // package cannot carry it.
    for (const manifestName of ['lifehacker', 'it-journey', 'zer0-mistakes', 'irony-works', 'ai-world-view', 'zer0-cms']) {
      assert.deepEqual(ourManifest(manifestName).metering, {}, `${manifestName}: no top-level metering`);
    }
    const metered = toEngineManifest({
      ...manifest,
      metering: { ledger: '_data/ai_usage/', rollup: 'AI_USAGE.md' },
    }).losses;
    assert.ok(metered.some((loss) => loss.field === 'metering'));

    // The engine manifest is exactly what `engineParseFleetManifest` would have
    // produced for a manifest it could read — which is the point of the
    // conversion, and is checkable because lifehacker's is one of those.
    const theirs = engineParseFleetManifest(manifestText('lifehacker'));
    assert.deepEqual(crossed.lanes, theirs.lanes);
  });

  test('an ai-lane caller is a runner shape the engines have no name for', () => {
    // The hub's `templates/ai-runner/ai-lane.template.yml`, verbatim. It calls
    // the reusable `ai-lane.yml`, so the model call is in the CALLEE: the
    // engines report no AI at all, and `wtd`'s adopt.py — which decides a
    // harness by matching a model-call pattern in the file — would drop the lane
    // outright. The `uses:` line is the only evidence, so that is what is read.
    const facts = extractFacts(
      '.github/workflows/ai-lane.template.yml',
      read(path.join(WORKFLOWS, 'hub/ai-lane.template.yml')),
    );
    assert.equal(facts.ai.present, false, 'the caller itself calls no model');
    assert.deepEqual(facts.ai.runners, []);
    assert.deepEqual(facts.reusableCalls, ['bamr87/bamr87/.github/workflows/ai-lane.yml@main']);
    assert.equal(runnerShapeOf(facts), 'ai-lane-caller');

    // Its switch is a reusable-workflow INPUT, not a `vars.X` read, so the
    // engines' kill-switch scan cannot see it either. A lane like this is
    // invisible from three directions at once.
    assert.deepEqual(facts.killSwitches, []);

    // The shapes the engines do name still map through.
    assert.equal(runnerShapeOf(factsOf('lifehacker', 'content-factory.yml')), 'claude-run');
    assert.equal(
      runnerShapeOf(factsOf('lifehacker', 'factory--issue-factory-1.yml')),
      'claude-code-action',
    );
    // And a workflow whose model call lives inside a Node engine reports `none`
    // — "no evidence in this file", which is why drift refuses to judge it.
    assert.equal(runnerShapeOf(factsOf('irony-works', 'germinate.yml')), 'none');
  });

  test('runs cross into the shape the metrics engine folds', () => {
    const runs: FleetRunRecord[] = [
      {
        runId: 42,
        name: 'Content Factory',
        path: '.github/workflows/content-factory.yml',
        event: 'schedule',
        createdAt: '2026-09-08T09:00:00Z',
        runStartedAt: '2026-09-08T09:00:07Z',
        runAttempt: 2,
        status: 'completed',
        conclusion: 'success',
        url: 'https://github.com/bamr87/lifehacker.dev/actions/runs/42',
        updatedAt: '2026-09-08T09:04:00Z',
      },
      {
        runId: 43,
        name: 'Factory: Issue Factory 1',
        path: '.github/workflows/factory--issue-factory-1.yml',
        event: 'workflow_dispatch',
        createdAt: '2026-09-08T10:00:00Z',
        runStartedAt: null,
        runAttempt: 1,
        status: 'in_progress',
        conclusion: null,
        url: 'https://github.com/bamr87/lifehacker.dev/actions/runs/43',
        updatedAt: '2026-09-08T10:00:30Z',
      },
      {
        runId: 44,
        name: 'Pipeline',
        path: '.github/workflows/pipeline.yml',
        event: 'push',
        createdAt: '2026-09-08T11:00:00Z',
        runStartedAt: '2026-09-08T11:00:02Z',
        runAttempt: 1,
        status: 'completed',
        // A conclusion the engines' union does not contain must land as null
        // rather than be smuggled through as a string.
        conclusion: 'exploded',
        url: 'https://github.com/bamr87/lifehacker.dev/actions/runs/44',
        updatedAt: '2026-09-08T11:03:00Z',
      },
    ];

    const factory = runsToFactoryRuns(runs);
    assert.equal(factory.length, 3);
    assert.equal(factory[0]?.slug, 'content-factory');
    assert.equal(factory[0]?.conclusion, 'success');
    assert.equal(factory[0]?.htmlUrl, runs[0]?.url);
    assert.equal(factory[0]?.updatedAt, '2026-09-08T09:04:00Z');
    assert.equal(factory[0]?.runAttempt, 2);
    // A GitFactory-compiled path loses its `factory--` prefix, exactly as the
    // package's own path parser does.
    assert.equal(factory[1]?.slug, 'issue-factory-1');
    assert.equal(factory[1]?.conclusion, null);
    assert.equal(factory[1]?.runStartedAt, null);
    assert.equal(factory[2]?.conclusion, null, 'an unknown conclusion is null, never the raw string');
  });
});

// ---------------------------------------------------------------------------

suite('engines: drift the real files actually contain', () => {
  test("lifehacker's content-factory says it opens no pull requests, and opens pull requests", () => {
    const manifest = ourManifest('lifehacker');
    const lane = manifest.lanes.find((entry) => entry.id === 'content-factory');
    assert.ok(lane !== undefined);
    assert.equal(lane.guardrails.opensPullRequests, false, 'the manifest fixture should still claim it');

    const facts = factsOf('lifehacker', 'content-factory.yml');
    assert.ok(facts.sinks.includes('pr'), 'the workflow fixture should still open pull requests');

    const rows = manifestDrift(lane, facts);
    const claim = rows.find((row) => row.manifestSays.includes('opens_pull_requests'));
    assert.ok(claim !== undefined, 'the false guardrail must produce a drift row');
    assert.equal(claim.laneId, 'content-factory');
    assert.equal(claim.kind, 'implementation');
    assert.match(claim.workflowSays, /opens pull requests/);

    // Nothing else about this lane drifts, so the row cannot be an artefact of a
    // noisy comparison.
    assert.deepEqual(rows.map((row) => row.kind), ['implementation']);

    // The same lane with the claim removed drifts on nothing at all.
    const honest: FleetLane = {
      ...lane,
      guardrails: { ...lane.guardrails, opensPullRequests: null },
    };
    assert.deepEqual(manifestDrift(honest, facts), []);
  });

  test('a switch no workflow reads, and a schedule the workflow commented out', () => {
    // ai-world-view's `grow-lineage` lane names ORCHESTRATE_ENABLED; the
    // workflow file reads no repository variable at all. The gate the manifest
    // promises does not exist in the file that would enforce it.
    const worldView = ourManifest('ai-world-view');
    const growLineage = worldView.lanes.find((lane) => lane.id === 'grow-lineage');
    assert.ok(growLineage !== undefined);
    assert.equal(growLineage.switch, 'ORCHESTRATE_ENABLED');

    const growFacts = factsOf('ai-world-view', 'grow-lineage.yml');
    assert.deepEqual(growFacts.killSwitches, []);

    const switchRows = manifestDrift(growLineage, growFacts).filter((row) => row.kind === 'switch');
    assert.equal(switchRows.length, 1);
    assert.equal(switchRows[0]?.manifestSays, 'ORCHESTRATE_ENABLED');
    assert.match(switchRows[0]?.workflowSays ?? '', /reads no repository variable/);

    // The mirror image, from it-journey: a lane the manifest calls ungated whose
    // workflow reads two switches.
    const journey = ourManifest('it-journey');
    const daily = journey.lanes.find((lane) => lane.id === 'cms-daily-loop');
    assert.ok(daily !== undefined);
    assert.equal(daily.switch, null);
    const dailyRows = manifestDrift(daily, factsOf('it-journey', 'cms-daily-loop.yml'));
    const ungated = dailyRows.find((row) => row.kind === 'switch');
    assert.ok(ungated !== undefined);
    assert.equal(ungated.manifestSays, 'ungated (switch: null)');
    assert.match(ungated.workflowSays, /CMS_LOOP_SUBSTANTIVE, CMS_MECHANICAL_AUTOMERGE/);

    // And lifehacker's `explore` lane, whose daily cron the workflow has
    // commented out — reported as dormant rather than as "no schedule", because
    // the difference is the whole story.
    const lifehacker = ourManifest('lifehacker');
    const explore = lifehacker.lanes.find((lane) => lane.id === 'explore');
    assert.ok(explore !== undefined);
    const exploreFacts = factsOf('lifehacker', 'explore.yml');
    assert.deepEqual(exploreFacts.crons, []);
    assert.deepEqual(exploreFacts.dormantCrons, ['23 6 * * *']);
    const triggerRow = manifestDrift(explore, exploreFacts).find((row) => row.kind === 'triggers');
    assert.ok(triggerRow !== undefined);
    assert.equal(triggerRow.manifestSays, 'schedule 23 6 * * *');
    assert.match(triggerRow.workflowSays, /commented out: 23 6 \* \* \*/);
  });
});

// ---------------------------------------------------------------------------

suite('engines: goldens at ENGINES_VERSION', () => {
  test('extractFacts and auditRepo reproduce the committed goldens', function () {
    if (!goldensAreCurrent()) {
      // Regenerate with `node src/test/fixtures/golden/engines/generate.mjs` and
      // read the diff — that is the point of the version sidecar.
      this.skip();
      return;
    }
    const goldenFacts = JSON.parse(read(path.join(GOLDEN, 'facts.json'))) as Record<string, unknown>;
    const goldenAudit = JSON.parse(read(path.join(GOLDEN, 'audit.json'))) as Record<string, unknown>;
    const goldenRules = JSON.parse(read(path.join(GOLDEN, 'rulebook.json'))) as unknown;

    const repos = fs
      .readdirSync(WORKFLOWS, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
    assert.deepEqual(repos, [
      'ai-world-view',
      'bash-365',
      'hub',
      'irony-works',
      'it-journey',
      'lifehacker',
      'zer0-mistakes',
    ]);

    const facts: Record<string, WorkflowFacts> = {};
    const audit: Record<string, unknown> = {};
    for (const repo of repos) {
      const perRepo: WorkflowFacts[] = [];
      for (const { rel, text } of workflowsOf(repo)) {
        const key = `${repo}/${path.basename(rel)}`;
        facts[key] = extractFacts(rel, text);
        perRepo.push(facts[key]);
      }
      audit[repo] = auditRepo(perRepo);
    }

    assert.equal(Object.keys(facts).length, 25);
    assert.deepEqual(JSON.parse(JSON.stringify(facts)), goldenFacts);
    assert.deepEqual(JSON.parse(JSON.stringify(audit)), goldenAudit);
    assert.deepEqual(
      AUDIT_RULES.map((rule) => ({ id: rule.id, severity: rule.severity, title: rule.title })),
      goldenRules,
    );

    // A grade nobody has to look up: lifehacker's 8 fixture workflows certify at
    // C. If a bump moves that, the diff says which rule moved it.
    const lifehacker = goldenAudit.lifehacker as { grade: string; score: number };
    assert.equal(lifehacker.grade, 'C');
    assert.equal(lifehacker.score, 57);
  });

  test('the manifest emitter reproduces its goldens byte for byte', function () {
    if (!goldensAreCurrent()) {
      this.skip();
      return;
    }
    const lanes = [
      {
        id: 'content-factory',
        kind: 'content' as const,
        harness: 'claude-cli' as const,
        implementation: '.github/workflows/content-factory.yml',
        description: 'content-factory',
        triggers: [
          { kind: 'schedule' as const, cron: '0 9 * * *' },
          { kind: 'dispatch' as const },
        ],
        switch: 'CONTENT_FACTORY_ENABLED',
        uses_tokens: ['ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'FLEET_TOKEN'],
        guardrails: { never_merges: true, opens_pull_requests: true },
      },
      {
        id: 'claude',
        kind: 'mention' as const,
        harness: 'claude-code-action' as const,
        implementation: '.github/workflows/claude.yml',
        description: 'Claude',
        triggers: [{ kind: 'event' as const, events: ['issue_comment', 'issues'] }],
        switch: null,
        uses_tokens: ['CLAUDE_CODE_OAUTH_TOKEN'],
        guardrails: { never_merges: true, writable_paths: ['pages/', '_data/'] },
      },
    ];
    assert.equal(
      toFleetManifestYaml(lanes, {
        repo: 'bamr87/zer0-CMS',
        summary: 'A frozen two-lane manifest — the emitter golden, not a real fleet.',
        provenance: 'declared',
        header: ['GENERATED for src/test/fixtures/golden/engines. Not a real manifest.'],
      }),
      read(path.join(GOLDEN, 'manifest.yml')),
    );
    assert.equal(
      engineYamlDump({
        scalar: 'plain',
        needsQuotes: 'yes: really',
        empty: '',
        nested: { list: ['a', 'b'], flag: true, count: 3, nothing: null },
      }),
      read(path.join(GOLDEN, 'yamldump.yml')),
    );
  });
});

// ---------------------------------------------------------------------------

suite('engines: the readers beside the seam', () => {
  test('the harness registry reads only stable fields, carries its blind spot, refuses a foreign marker', () => {
    const result = readHarnessRegistry(read(path.join(FLEET_FIXTURES, 'harness_registry.yml')));
    assert.ok(!registryWasRefused(result), 'the hub fixture should parse');
    assert.equal(result.schema, HARNESS_REGISTRY_SCHEMA);
    assert.equal(result.generatedAt, '2026-09-09 06:51 UTC');
    assert.equal(result.repos.length, 43);

    const lifehacker = registryRepoFor(result, 'bamr87/lifehacker.dev');
    assert.ok(lifehacker !== undefined);
    assert.deepEqual(Object.keys(lifehacker).sort(), [
      'agentContext',
      'aiUsage',
      'archived',
      'category',
      'coverageMissing',
      'coverageOk',
      'factory',
      'harnesses',
      'manifest',
      'nwo',
      'oauthSecret',
      'repo',
      'scanned',
      'status',
      'workflowsTotal',
    ]);
    assert.equal(lifehacker.workflowsTotal, 26);
    assert.equal(lifehacker.manifest, true);
    assert.equal(lifehacker.oauthSecret, 'ok');
    assert.equal(lifehacker.coverageOk, true);
    assert.deepEqual(lifehacker.harnesses.map((h) => h.path).sort(), [
      '.github/workflows/claude.yml',
      '.github/workflows/factory--issue-factory-1.yml',
      '.github/workflows/factory--issue-factory-2.yml',
    ]);

    // THE BLIND SPOT, as data. The hub's generator counts a workflow as AI only
    // when it contains `anthropics/claude-code-action`, so this census sees 3
    // harnesses where the repository's own manifest declares 17 lanes. The
    // console renders the note beside the number, because a number without its
    // blind spot is worse than no number.
    assert.equal(lifehacker.harnesses.length, 3);
    assert.equal(ourManifest('lifehacker').lanes.length, 17);
    assert.match(result.blindSpotNote, /anthropics\/claude-code-action/);
    assert.match(result.blindSpotNote, /3 harnesses/);

    // A foreign marker is refused as a value, never thrown — same posture as a
    // foreign `spec_version` in manifest.ts.
    const foreign = readHarnessRegistry('schema: harness-registry/v2\nrepos: []\n');
    assert.ok(registryWasRefused(foreign));
    assert.match(foreign.refused, /harness-registry\/v2.*is not harness-registry\/v1/);
    assert.ok(registryWasRefused(readHarnessRegistry('repos: []\n')));
    assert.ok(registryWasRefused(readHarnessRegistry('')));
    assert.ok(registryWasRefused(readHarnessRegistry('- a\n- b\n')));
  });

  test("gitFactoryLink's output is parseable by gitorio's own parseDeepLink", () => {
    // Transcribed from gitorio `app/src/state/deeplink.ts:20-34`. The reader is
    // the contract; `rosterLink` (its writer) emits only `tab` and `roster`, so
    // byte-equality with it would force this console to drop the hub it is
    // handing over. `parseRosterText` is the package's — the same function that
    // app calls, reached through the seam.
    const parseDeepLink = (search: string): { tab: string | null; hub: string | null; roster: string[] } => {
      const params = new URLSearchParams(search);
      const rawRoster = params.getAll('roster').join(' ');
      return {
        tab: params.get('tab'),
        hub: params.get('hub'),
        roster: parseRosterText(rawRoster).map((entry) => entry.slug),
      };
    };

    const base = 'https://bamr87.github.io/gitorio';
    const slugs = ['bamr87/lifehacker.dev', 'bamr87/irony-works', 'bamr87/zer0-CMS'];
    const link = gitFactoryLink(base, 'bamr87/bamr87', slugs);

    assert.ok(link.startsWith(`${base}/?`), 'the missing trailing slash is added, as rosterLink does');
    const parsed = parseDeepLink(new URL(link).search);
    assert.deepEqual(parsed, { tab: 'fleet', hub: 'bamr87/bamr87', roster: slugs });

    // The harness tab, and no hub to hand over.
    const harness = gitFactoryLink(`${base}/`, null, ['bamr87/it-journey'], 'harness');
    assert.deepEqual(parseDeepLink(new URL(harness).search), {
      tab: 'harness',
      hub: null,
      roster: ['bamr87/it-journey'],
    });

    // Junk never reaches the far end, because it is dropped by the same rule the
    // far end would drop it with — and an empty roster is still a valid link.
    const messy = gitFactoryLink(base, '   ', ['not a slug', 'bamr87/aieo', 'BAMR87/AIEO', 'a/b/c']);
    const messyParsed = parseDeepLink(new URL(messy).search);
    assert.equal(messyParsed.hub, null, 'a blank hub is omitted, never sent as an override');
    assert.deepEqual(messyParsed.roster, ['bamr87/aieo']);
    assert.deepEqual(parseDeepLink(new URL(gitFactoryLink(base, null, [])).search).roster, []);

    // Sanity: the slug rule really is the package's.
    assert.deepEqual(parseRepo('bamr87/lifehacker.dev'), { owner: 'bamr87', repo: 'lifehacker.dev' });
  });

  test('inspectWorkspaceFleet reads the whole lifehacker fixture set offline', async () => {
    const manifest = ourManifest('lifehacker');
    const inspection = await inspectWorkspaceFleet('/workspace/lifehacker.dev', manifest, fixtureIo('lifehacker'));

    assert.equal(inspection.root, '/workspace/lifehacker.dev');
    assert.equal(Object.keys(inspection.facts).length, 8);
    assert.deepEqual(inspection.unreadable, []);

    // Two real workflows no lane in the committed manifest claims — automation
    // that runs and that the manifest does not describe.
    assert.deepEqual(inspection.unmatchedWorkflows, [
      '.github/workflows/ai-usage.yml',
      '.github/workflows/triage.yml',
    ]);

    // Eleven declared lanes whose workflow files are not in this fixture set
    // (the real repository has 26 workflows; eight are checked in here).
    assert.equal(inspection.unmatchedLanes.length, 11);
    assert.ok(inspection.unmatchedLanes.includes('weekly-epic'));
    assert.ok(!inspection.unmatchedLanes.includes('content-factory'));

    // An audit and a grade with no network, no credential and no API call — the
    // whole point of the module (decision D11).
    assert.ok(['S', 'A', 'B', 'C', 'D'].includes(inspection.audit.grade));
    assert.equal(Object.keys(inspection.audit.byWorkflow).length, 8);
    assert.ok(inspection.audit.findings.length > 0);

    // Drift, from the same read.
    assert.deepEqual(
      inspection.drift.map((row) => `${row.laneId}:${row.kind}`).sort(),
      ['content-factory:implementation', 'explore:triggers', 'factory--issue-factory-1:triggers'],
    );

    // A repository with four AI workflows and no manifest at all is a normal
    // state, not an error: everything is unmatched, nothing drifts, the audit
    // still runs. bash-365.com is really in it.
    const orphan = await inspectWorkspaceFleet('/workspace/bash-365.com', null, fixtureIo('bash-365'));
    assert.equal(Object.keys(orphan.facts).length, 4);
    assert.equal(orphan.unmatchedWorkflows.length, 4);
    assert.deepEqual(orphan.unmatchedLanes, []);
    assert.deepEqual(orphan.drift, []);
    assert.ok(orphan.audit.score > 0);

    // A file that will not read is named, not silently dropped.
    const io = fixtureIo('irony-works');
    const broken: WorkspaceFleetIo = {
      ...io,
      listWorkflows: () => Promise.resolve(['.github/workflows/germinate.yml', '.github/workflows/gone.yml']),
      readFile: (rel) =>
        rel.endsWith('gone.yml') ? Promise.reject(new Error('ENOENT')) : io.readFile(rel),
    };
    const partial = await inspectWorkspaceFleet('/workspace/irony-works', ourManifest('irony-works'), broken);
    assert.deepEqual(partial.unreadable, ['.github/workflows/gone.yml']);
    assert.equal(Object.keys(partial.facts).length, 1);
  });
});
