/**
 * One harness vocabulary (decision D-F) — the suite that keeps the editor and
 * the fleet's CI describing the same run.
 *
 * Everything here runs over **verbatim copies** of files that exist in four
 * sibling repositories (`fixtures/harness/`, provenance in its
 * `FIXTURE-SOURCES.md`). That is the point: the four houses write their agent
 * files four different ways — a folded `>-` description here, a quoted string
 * with `<example>` blocks there, a `model:` pin in one, no `tools:` key at all
 * in another — and a reader that only handles the shape somebody typed into a
 * test is a reader that breaks the first time it meets a real repository.
 *
 * The two claims this file exists to defend:
 *
 *  1. **The model precedence is the runner's own.** settings > `zer0.json` >
 *     `_data/ai.yml` > the built-in default, which is `run.sh`'s `--model` >
 *     `AI_MODEL` > the file > its default with the layers renamed. A repository
 *     that ships an `_data/ai.yml` must resolve to *its* model, or the console
 *     is quietly disagreeing with the CI it is a console for.
 *  2. **Decision D10 survives every projection.** `toSdkOptions` never emits
 *     `allowedTools`, always emits `strictMcpConfig: true`, and always strips
 *     the publish flag out of the inherited environment. The permission-mode
 *     clamp is here too, because it is the one configuration that was measured
 *     to skip `canUseTool` entirely.
 *
 * No network, no `vscode`, and the only write is one `mkdtemp` ledger append.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import {
  agentStem,
  classifyDialect,
  parseAgentFile,
  readAgents,
  splitToolList,
  type HarnessIo,
} from '../core/harness/agents';
import { parseAiConfig } from '../core/harness/aiConfig';
import {
  appendUsageRecord,
  serializeUsageRecord,
  usageRecordFrom,
} from '../core/harness/metering';
import {
  BASE_READ_ONLY_TOOLS,
  DEFAULT_HARNESS_MODEL,
  MCP_READ_ONLY_TOOLS,
  ciSystemFor,
  permissionModeSkipsCard,
  profileWarnings,
  resolveHarnessProfile,
  toAiLaneWith,
  toRunnerInvocation,
  toSdkOptions,
  type HarnessProfileInput,
} from '../core/harness/profile';
import {
  compareLanes,
  agentNameFindings,
  joinHarness,
  laneForWorkflow,
  manifestDriftFindings,
  type HarnessJoinInput,
} from '../core/harness/joins';
import {
  detectHarness,
  detectKind,
  deriveLaneFromWorkflow,
  pickSwitch,
  upstreamWouldDropLane,
} from '../core/harness/derive';
import { describeHarnessInventory, readHarnessInventory } from '../core/harness/inventory';
import { parseLedger, readLedger } from '../core/harness/ledger';
import { parseSkillFile, readSkills, skillCountsFor } from '../core/harness/skills';
import {
  classifyRunnerShape,
  readAgentRefs,
  readSwitchHost,
  readSwitchPolarity,
  readWorkflowSkillRefs,
  scanWorkflow,
} from '../core/harness/workflows';
import { parseFleetManifest } from '../core/fleet/manifest';
import { resolveConfig } from '../core/shared/config';
import type {
  AiConfig,
  FleetLane,
  FleetManifest,
  HarnessFinding,
  McpStdioSpec,
  RunnerShape,
  Zer0Config,
} from '../core/shared/types';

const FIXTURES = path.resolve(__dirname, '../../src/test/fixtures');
const HARNESS = path.join(FIXTURES, 'harness');

/** The injected I/O, over a fixture repository. Reads only; never writes. */
function fixtureIo(repo: string): HarnessIo {
  const root = path.join(HARNESS, repo);
  return {
    async list(rel: string): Promise<string[]> {
      try {
        return await fs.promises.readdir(path.join(root, rel));
      } catch {
        return [];
      }
    },
    async read(rel: string): Promise<string | undefined> {
      try {
        return await fs.promises.readFile(path.join(root, rel), 'utf8');
      } catch {
        return undefined;
      }
    },
  };
}

function fixture(rel: string): string {
  return fs.readFileSync(path.join(HARNESS, rel), 'utf8');
}

const CFG: Zer0Config = resolveConfig('/tmp/site', {}, {});

const MCP: McpStdioSpec = {
  command: '/usr/local/bin/node',
  args: ['/ext/dist/mcp-server.js'],
  env: { ZER0_CMS_CONFIG: 'zer0.json' },
};

/** A profile input with everything at its quietest, overridable per test. */
function input(overrides: Partial<HarnessProfileInput> = {}): HarnessProfileInput {
  return {
    cfg: CFG,
    inventory: null,
    agents: [],
    skills: [],
    aiConfig: null,
    settingsModel: undefined,
    agentName: null,
    mcpServer: null,
    trusted: false,
    loadProjectSettings: false,
    extensionVersion: '9.9.9',
    ...overrides,
  };
}

function aiConfig(model: string | null, fallback: string | null = null): AiConfig {
  return {
    path: '_data/ai.yml',
    provider: 'anthropic',
    model,
    fallbackModel: fallback,
    maxTokens: 8000,
    extra: {},
  };
}

suite('harness — agent files', () => {
  test('the four house dialects all parse to one AgentRecord', () => {
    const cases: Array<{
      rel: string;
      name: string;
      dialect: string;
      tools: number;
      model: string | null;
    }> = [
      {
        rel: 'lifehacker/.claude/agents/grow-lifehacker.md',
        name: 'grow-lifehacker',
        dialect: 'lifehacker',
        tools: 6,
        model: null,
      },
      {
        rel: 'it-journey/.claude/agents/agent-auditor.md',
        name: 'agent-auditor',
        dialect: 'it-journey',
        tools: 6,
        model: null,
      },
      {
        rel: 'zer0-mistakes/.claude/agents/a11y-fixer.md',
        name: 'a11y-fixer',
        dialect: 'zer0-mistakes',
        tools: 5,
        model: 'sonnet',
      },
      // bash-365 writes the description as a quoted string carrying `<example>`
      // blocks, pins a model and a colour, and declares **no `tools:` key at
      // all** — an empty list is the honest reading, not a defaulted one.
      {
        rel: 'bash-365/.claude/agents/loop-writer.md',
        name: 'loop-writer',
        dialect: 'bash-365',
        tools: 0,
        model: 'opus',
      },
    ];

    for (const expected of cases) {
      const record = parseAgentFile(expected.rel, fixture(expected.rel));
      assert.equal(record.name, expected.name, expected.rel);
      assert.equal(record.dialect, expected.dialect, expected.rel);
      assert.equal(record.tools.length, expected.tools, expected.rel);
      assert.equal(record.model, expected.model, expected.rel);
      assert.equal(record.nameMatchesFile, true, expected.rel);
      assert.ok(record.description.length > 0, `${expected.rel} has a description`);
      assert.equal(record.path, expected.rel);
    }
  });

  test('a comma-separated `tools` string becomes a list, parentheses intact', () => {
    // Every repository in the fleet writes the string form today.
    const record = parseAgentFile(
      'lifehacker/.claude/agents/grow-lifehacker.md',
      fixture('lifehacker/.claude/agents/grow-lifehacker.md'),
    );
    assert.deepEqual(record.tools, ['Bash', 'Read', 'Write', 'Edit', 'Grep', 'Glob']);

    // A scoped tool's own scope may contain a comma, so the split is depth-aware.
    assert.deepEqual(splitToolList('Bash(git:*),Bash(gh pr create:*),Write(pages/**)'), [
      'Bash(git:*)',
      'Bash(gh pr create:*)',
      'Write(pages/**)',
    ]);
    assert.deepEqual(splitToolList('Read, Grep ,, Write '), ['Read', 'Grep', 'Write']);
  });

  test('a YAML-list `tools` becomes the same list', () => {
    const text = ['---', 'name: role', 'description: x', 'tools:', '  - Read', '  - Grep', '---', 'body'].join('\n');
    const record = parseAgentFile('.claude/agents/role.md', text);
    assert.deepEqual(record.tools, ['Read', 'Grep']);
  });

  test('`name` must equal the filename stem — a mismatch is recorded, never repaired', () => {
    // lifehacker's own `scripts/ci/lint_agents.rb` enforces this, because the
    // workflow names the agent by string and Claude Code resolves that string
    // against the FILENAME. Renaming silently would hide the dangling link.
    const text = fixture('lifehacker/.claude/agents/grow-lifehacker.md');
    const moved = parseAgentFile('.claude/agents/renamed.md', text);
    assert.equal(moved.nameMatchesFile, false);
    assert.equal(moved.name, 'grow-lifehacker', 'the declared name is kept as declared');
    assert.equal(agentStem('.claude/agents/renamed.md'), 'renamed');

    const missing = parseAgentFile('.claude/agents/nofm.md', '# no front matter here\n');
    assert.equal(missing.nameMatchesFile, false);
    assert.equal(missing.name, 'nofm', 'the stem stands in so a join still resolves');
    assert.deepEqual(missing.tools, []);
  });

  test('an agent that cites the shared quarantine doc and names a skill says so', async () => {
    const agents = await readAgents(fixtureIo('it-journey'));
    const auditor = agents.find((agent) => agent.name === 'agent-auditor');
    assert.ok(auditor !== undefined);
    assert.equal(auditor.citesQuarantine, true);
    assert.equal(auditor.dialect, 'it-journey');

    const grow = parseAgentFile(
      'lifehacker/.claude/agents/grow-lifehacker.md',
      fixture('lifehacker/.claude/agents/grow-lifehacker.md'),
    );
    // "Follow the **grow-lifehacker skill**" — the only agent→skill link in the
    // fleet is prose, and `_shared` is never one of the answers.
    assert.deepEqual(grow.skillRefs, ['grow-lifehacker']);

    // Structure decides the dialect, not the site a file happens to name: an
    // agent with no house markers at all is `unknown`, which is a real answer.
    assert.equal(
      classifyDialect({ description: 'x', hasColor: false, model: null, body: 'y' }),
      'unknown',
    );
  });
});

suite('harness — skills', () => {
  test('a SKILL.md parses to a SkillRecord with its trigger phrases', () => {
    const rel = 'lifehacker/.claude/skills/grow-lifehacker/SKILL.md';
    const record = parseSkillFile(rel, fixture(rel));
    assert.equal(record.name, 'grow-lifehacker');
    assert.equal(record.nameMatchesDir, true);
    assert.ok(record.description.length > 0);
    assert.ok(
      record.triggerPhrases.some((phrase) => phrase.toLowerCase().includes('grow the site')),
      `expected a quoted trigger, got ${JSON.stringify(record.triggerPhrases)}`,
    );
  });

  test('`_shared` is not a skill, and both counts are reported rather than reconciled', async () => {
    const { skills, counts } = await readSkills(fixtureIo('lifehacker'));
    assert.deepEqual(
      skills.map((skill) => skill.name),
      ['grow-lifehacker'],
      '_shared has no SKILL.md and is never a skill',
    );
    // lifehacker's lint excludes `_shared`; `wtd fleet adopt` counts every
    // directory. Same tree, two numbers, both right under their own rule.
    assert.deepEqual(counts, { lintAgents: 1, wtdAdopt: 2 });
    assert.deepEqual(skillCountsFor(['a', 'b', '_shared']), { lintAgents: 2, wtdAdopt: 3 });
  });
});

suite('harness — _data/ai.yml', () => {
  test('three real shapes read the same way', () => {
    // lifehacker: the full file, with keys this module deliberately does not
    // model (the illustrator and xAI image settings) preserved in `extra`.
    const lifehacker = parseAiConfig('_data/ai.yml', fixture('lifehacker/_data/ai.yml'));
    assert.equal(lifehacker.model, 'claude-opus-4-8');
    assert.equal(lifehacker.fallbackModel, 'claude-opus-4-8');
    assert.equal(lifehacker.maxTokens, 8000);
    assert.equal(lifehacker.provider, 'anthropic');
    assert.equal(lifehacker.extra['illustrator_model'], 'claude-sonnet-4-6');

    // zer0-mistakes: the minimal three keys, and no fallback at all.
    const zer0 = parseAiConfig('_data/ai.yml', fixture('zer0-mistakes/_data/ai.yml'));
    assert.equal(zer0.model, 'claude-opus-4-8');
    assert.equal(zer0.fallbackModel, null);
    assert.equal(zer0.maxTokens, 8000);

    // it-journey: the same keys behind a long comment block, including one that
    // documents a per-lane exception the file itself does not encode.
    const itJourney = parseAiConfig('_data/ai.yml', fixture('it-journey/_data/ai.yml'));
    assert.equal(itJourney.model, 'claude-opus-4-8');
    assert.equal(itJourney.fallbackModel, 'claude-opus-4-8');
    assert.equal(itJourney.extra['api_version'], '2023-06-01');

    // A file that is not there at all is a normal state, not an error.
    const empty = parseAiConfig('_data/ai.yml', '# nothing but a comment\n');
    assert.deepEqual(
      { model: empty.model, fallback: empty.fallbackModel, max: empty.maxTokens },
      { model: null, fallback: null, max: null },
    );
  });
});

suite('harness — model precedence', () => {
  test('settings win over every other layer', () => {
    const profile = resolveHarnessProfile(
      input({
        cfg: { ...CFG, agent: { ...CFG.agent, model: 'claude-haiku-4-5' } },
        settingsModel: 'claude-sonnet-4-6',
        aiConfig: aiConfig('claude-opus-4-8'),
      }),
    );
    assert.equal(profile.model, 'claude-sonnet-4-6');
    assert.equal(profile.modelSource, 'settings');
  });

  test('zer0.json wins over the repository’s ai.yml', () => {
    const profile = resolveHarnessProfile(
      input({
        cfg: { ...CFG, agent: { ...CFG.agent, model: 'claude-haiku-4-5' } },
        aiConfig: aiConfig('claude-opus-4-8'),
      }),
    );
    assert.equal(profile.model, 'claude-haiku-4-5');
    assert.equal(profile.modelSource, 'zer0.json');
  });

  test('an untouched setting inherits the repository’s own ai.yml', () => {
    // The whole point of D-F: with nothing configured, the merged value is the
    // manifest default, which is not an answer anybody gave — so the editor
    // resolves what this site's CI resolves instead of disagreeing with it.
    const profile = resolveHarnessProfile(
      input({ aiConfig: parseAiConfig('_data/ai.yml', fixture('lifehacker/_data/ai.yml')) }),
    );
    assert.equal(profile.model, 'claude-opus-4-8');
    assert.equal(profile.modelSource, 'ai.yml');
    assert.notEqual(profile.model, DEFAULT_HARNESS_MODEL);
    // A fallback identical to the primary is not a fallback.
    assert.equal(profile.fallbackModel, null);
  });

  test('the built-in default answers only when nothing else did', () => {
    const profile = resolveHarnessProfile(input());
    assert.equal(profile.model, DEFAULT_HARNESS_MODEL);
    assert.equal(profile.modelSource, 'default');

    const withFallback = resolveHarnessProfile(
      input({ aiConfig: aiConfig('claude-opus-4-8', 'claude-haiku-4-5') }),
    );
    assert.equal(withFallback.fallbackModel, 'claude-haiku-4-5');
  });
});

suite('harness — the gate survives the projection', () => {
  test('settingSources is [] unless the workspace is trusted AND the person opted in', () => {
    const cases: Array<[boolean, boolean, number]> = [
      [false, false, 0],
      [false, true, 0],
      [true, false, 0],
      [true, true, 3],
    ];
    for (const [trusted, opted, expected] of cases) {
      const profile = resolveHarnessProfile(input({ trusted, loadProjectSettings: opted }));
      assert.equal(
        profile.settingSources.length,
        expected,
        `trusted=${trusted} optedIn=${opted}`,
      );
    }
    const loaded = resolveHarnessProfile(input({ trusted: true, loadProjectSettings: true }));
    assert.deepEqual(loaded.settingSources, ['user', 'project', 'local']);
    assert.equal(profileWarnings(loaded, 'default').length, 1, 'and the transcript says so');
  });

  test('a permission mode that can skip the card is clamped, and reported', () => {
    // Measured against the SDK: under `acceptEdits` a Write never reaches
    // `canUseTool` at all. D10 says the callback is the single gate, so the
    // mode is clamped rather than honoured — including when it arrives from a
    // `zer0.json` that came with a cloned repository.
    assert.equal(permissionModeSkipsCard('acceptEdits'), true);
    assert.equal(permissionModeSkipsCard('bypassPermissions'), true);
    assert.equal(permissionModeSkipsCard('default'), false);
    assert.equal(permissionModeSkipsCard('plan'), false);

    const profile = resolveHarnessProfile(
      input({ cfg: { ...CFG, agent: { ...CFG.agent, permissionMode: 'acceptEdits' } } }),
    );
    assert.equal(profile.permissionMode, 'default');
    const warnings = profileWarnings(profile, 'acceptEdits');
    assert.equal(warnings.length, 1);
    assert.match(warnings[0] ?? '', /acceptEdits/);

    const planned = resolveHarnessProfile(
      input({ cfg: { ...CFG, agent: { ...CFG.agent, permissionMode: 'plan' } } }),
    );
    assert.equal(planned.permissionMode, 'plan');
    assert.deepEqual(profileWarnings(planned, 'plan'), []);
  });

  test('toSdkOptions never emits allowedTools, always pins strictMcpConfig, and strips the publish flag', () => {
    const profile = resolveHarnessProfile(input({ mcpServer: MCP }));
    const options = toSdkOptions(profile, {
      PATH: '/usr/bin',
      HOME: '/home/someone',
      ZER0_CMS_MCP_ALLOW_PUBLISH: '1',
      ZER0_CMS_MCP_ALLOW_SCAFFOLD: '1',
      EMPTY: undefined,
    });

    assert.equal('allowedTools' in options, false, 'D10: the callback is the single gate');
    assert.equal(options.strictMcpConfig, true);
    assert.deepEqual(options.mcpServers, { 'zer0-cms': MCP });
    // The SDK replaces the child environment wholesale when `env` is set, so
    // this is a deletion, not a hope.
    assert.deepEqual(options.env, { PATH: '/usr/bin', HOME: '/home/someone' });
    assert.equal(options.systemPrompt.preset, 'claude_code');
    assert.match(options.systemPrompt.append, /zer0-CMS 9\.9\.9/);
  });

  test('the MCP read tools are auto-allowed only when the server is actually attached', () => {
    const without = resolveHarnessProfile(input());
    assert.deepEqual([...without.readOnlyTools], [...BASE_READ_ONLY_TOOLS]);

    const withServer = resolveHarnessProfile(input({ mcpServer: MCP }));
    for (const tool of MCP_READ_ONLY_TOOLS) {
      assert.ok(withServer.readOnlyTools.includes(tool), tool);
      assert.match(tool, /^mcp__zer0-cms__zer0_/);
    }
    // The five writers are absent, so they fail closed onto the approval card.
    for (const writer of ['zer0_draft', 'zer0_publish', 'zer0_worklist', 'zer0_ingest', 'zer0_contract']) {
      assert.equal(
        withServer.readOnlyTools.includes(`mcp__zer0-cms__${writer}`),
        false,
        writer,
      );
    }
  });
});

suite('harness — the CI projection', () => {
  test('toRunnerInvocation speaks the runner’s own flag names', () => {
    const agents = [
      parseAgentFile(
        'lifehacker/.claude/agents/grow-lifehacker.md',
        fixture('lifehacker/.claude/agents/grow-lifehacker.md'),
      ),
    ];
    const inherited = resolveHarnessProfile(
      input({ agents, agentName: 'grow-lifehacker', aiConfig: aiConfig('claude-opus-4-8') }),
    );
    const { argv, env } = toRunnerInvocation(inherited, 'write the next hack');

    assert.equal(argv[0], 'scripts/ai/run.sh');
    const flags = argv.filter((token) => token.startsWith('--'));
    assert.deepEqual(flags, ['--prompt', '--agent', '--tools', '--system', '--max-turns']);
    assert.equal(argv[argv.indexOf('--agent') + 1], 'grow-lifehacker');
    assert.equal(argv[argv.indexOf('--tools') + 1], 'Bash,Read,Write,Edit,Grep,Glob');
    // No `--model`: the model was inherited from `_data/ai.yml`, and the runner
    // reads that same file. Pinning it here would freeze in a workflow what the
    // site can change in one place.
    assert.equal(argv.includes('--model'), false);
    assert.deepEqual(env, {});

    // The system line is the role's, not the editor's — a lane's whole job is
    // often to open the pull request the editor's prompt forbids.
    const system = argv[argv.indexOf('--system') + 1] ?? '';
    assert.equal(system, ciSystemFor(inherited));
    assert.match(system, /Never merge\.$/);
    assert.equal(system.includes('VS Code'), false);

    const pinned = resolveHarnessProfile(
      input({ agents, agentName: 'grow-lifehacker', settingsModel: 'claude-sonnet-4-6' }),
    );
    const pinnedArgv = toRunnerInvocation(pinned, 'x').argv;
    assert.equal(pinnedArgv[pinnedArgv.indexOf('--model') + 1], 'claude-sonnet-4-6');
  });

  test('toAiLaneWith emits the lane inputs the profile actually knows', () => {
    const agents = [
      parseAgentFile(
        'zer0-mistakes/.claude/agents/a11y-fixer.md',
        fixture('zer0-mistakes/.claude/agents/a11y-fixer.md'),
      ),
    ];
    const profile = resolveHarnessProfile(
      input({ agents, agentName: 'a11y-fixer', aiConfig: aiConfig('claude-opus-4-8') }),
    );
    const block = toAiLaneWith(profile);

    // `lane`, `switch` and `prompt` are the author's to fill: inventing them
    // would be this console writing a workflow field it derived, not read.
    assert.deepEqual(Object.keys(block).sort(), ['agent', 'max-turns', 'system', 'tools']);
    assert.equal(block['agent'], 'a11y-fixer');
    assert.equal(block['tools'], 'Read,Grep,Glob,Edit,Bash');
    assert.equal(block['max-turns'], String(profile.maxTurns));
    assert.equal(block['model'], undefined);

    // Every key is a real `ai-lane.yml` `workflow_call` input.
    const inputs = new Set([
      'lane', 'switch', 'prompt', 'agent', 'system', 'tools', 'mcp', 'model', 'max-turns', 'out',
      'setup-ruby', 'bundler-cache', 'setup-node', 'setup-python', 'pre-run', 'post-run',
      'result-file', 'artifact-path', 'timeout-minutes', 'cancel-in-progress', 'continue-on-error',
    ]);
    for (const key of Object.keys(block)) {
      assert.ok(inputs.has(key), `${key} is not an ai-lane.yml input`);
    }
  });
});

suite('harness — metering', () => {
  test('a run is recorded in the shape the fleet’s own ledger uses', async () => {
    const record = usageRecordFrom(
      {
        type: 'result',
        subtype: 'success',
        is_error: false,
        duration_ms: 4321,
        num_turns: 7,
        session_id: 'sess-1',
        total_cost_usd: 0.1234,
        usage: {
          input_tokens: 100,
          output_tokens: 20,
          cache_read_input_tokens: 5,
          cache_creation_input_tokens: 3,
        },
      },
      {
        agent: 'grow-lifehacker',
        model: 'claude-opus-4-8',
        repo: 'bamr87/lifehacker.dev',
        workspaceRoot: '/w/lifehacker.dev',
        startedAt: 1_000,
        now: 1_700_000_000_000,
      },
    );

    assert.equal(record.source, 'zer0-cms-agent');
    assert.equal(record.auth, 'sdk');
    assert.equal(record.status, 'success');
    assert.equal(record.agent, 'grow-lifehacker');
    assert.equal(record.num_turns, 7);
    assert.equal(record.duration_ms, 4321);
    assert.equal(record.cost_usd, 0.1234);
    assert.equal(record.cost_source, 'reported');
    assert.deepEqual(record.tokens, { input: 100, output: 20, cache_read: 5, cache_creation: 3 });
    assert.equal(record.id.length, 16, 'a stable 16-hex id, like usage.rb’s');

    // Nothing reported means `null`, never a zero: a zero adds up.
    const quiet = usageRecordFrom(
      { type: 'result', is_error: true },
      {
        agent: null,
        model: 'm',
        repo: 'r',
        workspaceRoot: '/w',
        startedAt: 1_000,
        now: 2_000,
      },
    );
    assert.equal(quiet.cost_usd, null);
    assert.equal(quiet.cost_source, 'estimated');
    assert.equal(quiet.status, 'error');
    assert.equal(quiet.duration_ms, 1_000);

    // JSONL, sorted keys, one line, newline-terminated.
    const line = serializeUsageRecord(record);
    assert.equal(line.endsWith('\n'), true);
    assert.equal(line.trimEnd().includes('\n'), false);
    const keys = Object.keys(JSON.parse(line) as Record<string, unknown>);
    assert.deepEqual(keys, [...keys].sort(), 'sorted keys keep the file diff-stable');

    const dir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'zer0-usage-'));
    const target = path.join(dir, 'nested', 'records.jsonl');
    await appendUsageRecord(target, record);
    await appendUsageRecord(target, quiet);
    const written = await fs.promises.readFile(target, 'utf8');
    assert.equal(written.trimEnd().split('\n').length, 2, 'appends, never rewrites');
    await fs.promises.rm(dir, { recursive: true, force: true });
  });
});

// ===========================================================================
// PR4 WP4.1 — the harness inventory: what the seven files say, and where they
// disagree.
//
// Everything below runs over the same verbatim copies the readers above use,
// plus the workflow files and manifests already staged under
// `fixtures/fleet/`. Those are read where they lie rather than copied into a
// second tree: one copy of `content-factory.yml` at one recorded commit cannot
// drift away from itself, and two copies eventually would.
//
// The claim this half of the suite exists to defend is narrower than "the
// reader works". It is: **a finding that fires on a healthy repository is a
// wrong rule.** So the fixtures are six real repositories with real wiring, the
// derivation is checked against a manifest a different tool generated from the
// same bytes, and every rule that fires here fires on something a maintainer
// would agree is broken.
// ===========================================================================

const FLEET_FIXTURES = path.join(FIXTURES, 'fleet');

/** A workflow staged under `fixtures/fleet/workflows/<repo>/`. */
function fleetWorkflow(repo: string, file: string): string {
  return fs.readFileSync(path.join(FLEET_FIXTURES, 'workflows', repo, file), 'utf8');
}

/** Which fleet-fixture manifest stands in for a repository's `fleet.manifest.yml`. */
const FLEET_MANIFESTS: Readonly<Record<string, string>> = {
  lifehacker: 'lifehacker.fleet.manifest.yml',
  'it-journey': 'it-journey.fleet.manifest.yml',
  'zer0-mistakes': 'zer0-mistakes.fleet.manifest.yml',
  'irony-works': 'irony-works.fleet.manifest.yml',
  'ai-world-view': 'ai-world-view.fleet.manifest.yml',
};

/**
 * The injected I/O for a whole fixture repository, overlaid from two trees.
 *
 * `fixtures/harness/<repo>/` is the repository tree (agents, skills, `_data/`,
 * and the workflows PR4 added). `fixtures/fleet/` holds the workflows and
 * manifests earlier packages already staged, with their provenance recorded in
 * its own `FIXTURE-SOURCES.md`. The overlay is what lets both be true at once
 * without a byte of either being copied twice — and it is only possible because
 * the readers take their filesystem as a parameter, which is the argument for
 * the injection in the first place.
 */
function inventoryIo(repo: string): HarnessIo {
  const primary = path.join(HARNESS, repo);
  const fleetWorkflows = path.join(FLEET_FIXTURES, 'workflows', repo);
  const manifestFile = FLEET_MANIFESTS[repo];
  const manifestPath =
    manifestFile === undefined ? null : path.join(FLEET_FIXTURES, 'manifests', manifestFile);

  const readIfPresent = (abs: string): string | undefined => {
    try {
      return fs.readFileSync(abs, 'utf8');
    } catch {
      return undefined;
    }
  };
  const listIfPresent = (abs: string): string[] => {
    try {
      return fs.readdirSync(abs);
    } catch {
      return [];
    }
  };

  return {
    async list(rel: string): Promise<string[]> {
      const own = listIfPresent(path.join(primary, rel));
      if (rel !== '.github/workflows') {
        return own;
      }
      return [...new Set([...own, ...listIfPresent(fleetWorkflows)])];
    },
    async read(rel: string): Promise<string | undefined> {
      const own = readIfPresent(path.join(primary, rel));
      if (own !== undefined) {
        return own;
      }
      if (rel.startsWith('.github/workflows/')) {
        return readIfPresent(path.join(fleetWorkflows, path.basename(rel)));
      }
      if (rel === 'fleet.manifest.yml' && manifestPath !== null) {
        return readIfPresent(manifestPath);
      }
      return undefined;
    },
  };
}

const INVENTORY_OPTS = {
  manifestPath: 'fleet.manifest.yml',
  aiConfigPath: '_data/ai.yml',
  now: Date.UTC(2026, 8, 9, 12, 0, 0),
};

/** A lane with everything unsaid, for the synthetic manifests below. */
function laneStub(overrides: Partial<FleetLane>): FleetLane {
  return {
    id: 'stub',
    kind: 'other',
    harness: 'claude-cli',
    implementation: '',
    description: 'stub',
    triggers: [],
    switch: null,
    usesTokens: [],
    guardrails: {
      neverMerges: null,
      opensPullRequests: null,
      writesDirectlyToDefaultBranch: null,
      writablePaths: [],
    },
    ...overrides,
  };
}

/** A manifest carrying exactly these lanes. */
function manifestOf(lanes: FleetLane[]): FleetManifest {
  return {
    specVersion: 'fleet/v1',
    repo: 'bamr87/example',
    provenance: 'derived',
    summary: '',
    lanes,
    tokens: [],
    metering: {},
    agents: [],
    skills: [],
  };
}

/** A join input with nothing in it, overridable per case. */
function joinInput(overrides: Partial<HarnessJoinInput> = {}): HarnessJoinInput {
  return {
    manifest: null,
    workflows: [],
    agents: [],
    skills: [],
    ledger: null,
    hasSkillsDir: false,
    sources: {},
    ...overrides,
  };
}

const kindsOf = (findings: readonly HarnessFinding[]): string[] =>
  [...new Set(findings.map((f) => f.kind))].sort();

suite('harness — reading a workflow', () => {
  test('scanWorkflow classifies every runner shape the fleet actually runs', () => {
    // Fourteen files, six shapes, six repositories plus the hub. The ORDER of
    // `classifyRunnerShape` is what this table really pins: `germinate.yml`
    // installs the Claude CLI in order to run its own engine and must read as the
    // engine; `quest-walkthrough.yml` drives an agentic Python engine *through*
    // the hub composite and must read as the composite.
    const cases: Array<{ repo: string; file: string; shape: RunnerShape }> = [
      { repo: 'hub', file: 'ai-lane.template.yml', shape: 'ai-lane-caller' },
      { repo: 'hub', file: 'ai-lane.yml', shape: 'claude-run' },
      { repo: 'lifehacker', file: 'content-factory.yml', shape: 'claude-run' },
      { repo: 'lifehacker', file: 'pipeline.yml', shape: 'claude-run' },
      { repo: 'lifehacker', file: 'factory--issue-factory-1.yml', shape: 'claude-code-action' },
      { repo: 'lifehacker', file: 'triage.yml', shape: 'none' },
      { repo: 'lifehacker', file: 'ai-usage.yml', shape: 'none' },
      { repo: 'it-journey', file: 'quest-walkthrough.yml', shape: 'claude-run' },
      { repo: 'it-journey', file: 'cms-daily-loop.yml', shape: 'claude-cli' },
      { repo: 'zer0-mistakes', file: 'ai-content-review.yml', shape: 'claude-cli' },
      { repo: 'zer0-mistakes', file: 'translate.yml', shape: 'engine' },
      { repo: 'zer0-mistakes', file: 'issue-pr-auto-merge.yml', shape: 'none' },
      { repo: 'irony-works', file: 'germinate.yml', shape: 'agentic-engine' },
      { repo: 'bash-365', file: 'content-loop.yml', shape: 'claude-code-action' },
      { repo: 'ai-world-view', file: 'grow-lineage.yml', shape: 'claude-code-action' },
    ];
    for (const expected of cases) {
      const rel = `.github/workflows/${expected.file}`;
      const record = scanWorkflow(rel, fleetWorkflow(expected.repo, expected.file));
      assert.equal(record.runnerShape, expected.shape, `${expected.repo}/${expected.file}`);
      assert.equal(record.path, rel);
    }

    // The hub's own reusable lane carries a copy-me example of
    // `uses: .../ai-lane.yml@main` in its header comment. Classifying from raw
    // text made the reusable a caller of itself.
    assert.equal(
      classifyRunnerShape(fleetWorkflow('hub', 'ai-lane.yml')),
      'claude-run',
      'a comment ABOUT a runner is not a runner',
    );

    // A `factory--*.yml` is compiled from a blueprint; nothing may offer to edit one.
    const generated = scanWorkflow(
      '.github/workflows/factory--issue-factory-1.yml',
      fleetWorkflow('lifehacker', 'factory--issue-factory-1.yml'),
    );
    assert.equal(generated.generatedByGitFactory, true);
    assert.equal(
      scanWorkflow(
        '.github/workflows/content-factory.yml',
        fleetWorkflow('lifehacker', 'content-factory.yml'),
      ).generatedByGitFactory,
      false,
    );
  });

  test('a workflow this reader cannot parse yields honest nulls, never a throw', () => {
    for (const text of ['', 'not: [yaml', '   ', 'name:\n\ton: {']) {
      const record = scanWorkflow('.github/workflows/broken.yml', text);
      assert.equal(record.runnerShape, 'none');
      assert.deepEqual(record.agentRefs, []);
      assert.deepEqual(record.switches, []);
      assert.equal(record.switchHost, null, 'null is "the file did not say"');
      assert.equal(record.dispatchBypassesSwitch, null, 'and it is not `false`');
      assert.equal(record.timeoutMinutes, null);
      assert.equal(record.resultFile, null);
      assert.deepEqual(record.permissions, {});
      assert.equal(record.matrix, 'none');
      assert.equal(record.continueOnError, false);
    }
    // A file with no `name:` is named for its stem, not left blank.
    assert.equal(scanWorkflow('.github/workflows/broken.yml', '').name, 'broken');
  });

  test('dispatchBypassesSwitch is read, not assumed — the fleet is split on it', () => {
    // The hub's reusable lane: `[ "$EVENT" != "workflow_dispatch" ]` inside the
    // gate. It declares only `workflow_call`, because for a reusable workflow the
    // event is the CALLER's — a guard that looked only at this file's own
    // triggers would report the fleet's canonical bypass as "not applicable".
    const hub = scanWorkflow('.github/workflows/ai-lane.yml', fleetWorkflow('hub', 'ai-lane.yml'));
    assert.deepEqual(hub.events, ['workflow_call']);
    assert.equal(hub.dispatchBypassesSwitch, true);

    // lifehacker's `triage.yml`: a shell branch that answers `go=true` before the
    // switch is read at all.
    const triage = scanWorkflow(
      '.github/workflows/triage.yml',
      fleetWorkflow('lifehacker', 'triage.yml'),
    );
    assert.equal(triage.dispatchBypassesSwitch, true);

    // irony-works' `germinate.yml`: a job-level `if:` that ORs the event against
    // the switch.
    const germinate = scanWorkflow(
      '.github/workflows/germinate.yml',
      fleetWorkflow('irony-works', 'germinate.yml'),
    );
    assert.equal(germinate.dispatchBypassesSwitch, true);

    // And the counter-example the whole field exists for: lifehacker's content
    // factory requires the variable even on a manual run.
    const factory = scanWorkflow(
      '.github/workflows/content-factory.yml',
      fleetWorkflow('lifehacker', 'content-factory.yml'),
    );
    assert.equal(factory.dispatchBypassesSwitch, false);

    // `null` when the question does not arise: a dispatch-only lane with no
    // switch of its own has nothing to bypass, and `false` would claim otherwise.
    const grow = scanWorkflow(
      '.github/workflows/grow-lineage.yml',
      fleetWorkflow('ai-world-view', 'grow-lineage.yml'),
    );
    assert.deepEqual(grow.switches, []);
    assert.equal(grow.dispatchBypassesSwitch, null);
  });

  test('switchHost finds a switch enforced on a different workflow', () => {
    // ai-world-view's `grow-lineage.yml` is dispatch-only and carries no gate.
    // Its manifest lane still says `switch: ORCHESTRATE_ENABLED`, because that
    // variable gates `orchestrate.yml`, the lane's only automated dispatcher. A
    // reader that looked only for `vars.` here would call the manifest wrong.
    const text = fleetWorkflow('ai-world-view', 'grow-lineage.yml');
    assert.equal(text.includes('vars.ORCHESTRATE_ENABLED'), false, 'it never reads the variable');
    assert.equal(text.includes('ORCHESTRATE_ENABLED'), true, 'but it names it, in prose');
    assert.equal(readSwitchHost(text, [], 'grow-lineage.yml'), 'orchestrate.yml');

    // A workflow that reads its own switch has no host elsewhere.
    const factory = fleetWorkflow('lifehacker', 'content-factory.yml');
    assert.equal(readSwitchHost(factory, ['CONTENT_FACTORY_ENABLED'], 'content-factory.yml'), null);
  });

  test("switchPolarity reads the default-ON `!= 'false'` form", () => {
    // zer0-mistakes' visual-evidence lane is the fleet's only default-ON switch:
    // it runs unless somebody sets the variable to `false`. A console that
    // assumed "unset means off" would report a running lane as idle.
    const on = scanWorkflow(
      '.github/workflows/visual-evidence-autogen.yml',
      fixture('zer0-mistakes/.github/workflows/visual-evidence-autogen.yml'),
    );
    assert.deepEqual(on.switches, ['VISUAL_EVIDENCE_AUTOGEN_ENABLED']);
    assert.equal(on.switchPolarity, 'disabled-when-false');

    // The default-OFF posture everything else uses.
    const off = scanWorkflow(
      '.github/workflows/content-factory.yml',
      fleetWorkflow('lifehacker', 'content-factory.yml'),
    );
    assert.equal(off.switchPolarity, 'enabled-when-true');

    // lifehacker's `loop-tuner.yml` tests a dispatch INPUT with `!= "false"`
    // while its own switch is default-OFF. A looser rule read that as polarity.
    const tuner = scanWorkflow(
      '.github/workflows/loop-tuner.yml',
      fixture('lifehacker/.github/workflows/loop-tuner.yml'),
    );
    assert.equal(tuner.switchPolarity, 'enabled-when-true');

    // No switch means no polarity to have.
    assert.equal(readSwitchPolarity('name: x\n', []), 'unknown');
  });

  test('a commented-out schedule is a dormant cron, not a schedule', () => {
    const usage = scanWorkflow(
      '.github/workflows/ai-usage.yml',
      fleetWorkflow('lifehacker', 'ai-usage.yml'),
    );
    assert.deepEqual(usage.crons, [], 'the daily run was parked in July');
    assert.deepEqual(usage.dormantCrons, ['17 8 * * *']);

    const explore = scanWorkflow(
      '.github/workflows/explore.yml',
      fleetWorkflow('lifehacker', 'explore.yml'),
    );
    assert.deepEqual(explore.crons, []);
    assert.deepEqual(explore.dormantCrons, ['23 6 * * *']);

    // A live one still reads as live.
    const factory = scanWorkflow(
      '.github/workflows/content-factory.yml',
      fleetWorkflow('lifehacker', 'content-factory.yml'),
    );
    assert.deepEqual(factory.crons, ['0 9 * * *']);
    assert.deepEqual(factory.dormantCrons, []);

    // `wtd fleet adopt` scans raw text, so the manifest records the parked cron
    // as a live schedule. `derive.ts` reproduces that on purpose; this is the
    // disagreement, and the reason both fields exist.
    const derived = deriveLaneFromWorkflow(
      '.github/workflows/explore.yml',
      fleetWorkflow('lifehacker', 'explore.yml'),
    );
    assert.deepEqual(
      derived.triggers.filter((t) => t.kind === 'schedule').map((t) => t.cron),
      ['23 6 * * *'],
    );
  });

  test('agent references: literals and subagent prose, never expressions or ledger roles', () => {
    const factory = scanWorkflow(
      '.github/workflows/content-factory.yml',
      fleetWorkflow('lifehacker', 'content-factory.yml'),
    );
    assert.deepEqual(factory.agentRefs, ['grow-lifehacker']);
    assert.deepEqual(factory.skillRefs, ['grow-lifehacker']);

    // A computed role is not a reference — no file-level reader can resolve it,
    // and lifehacker's own `lint_agents.rb` skips the same expressions.
    assert.deepEqual(readAgentRefs('        agent: ${{ matrix.item.role }}\n'), []);

    // `--agent` on a metering line labels a LEDGER ROW, not an agent file. Three
    // lifehacker workflows do this and none of the three names an agent file;
    // reading them as agent references produced three confident, wrong errors.
    assert.deepEqual(
      readAgentRefs(
        '            ruby scripts/ai/usage.rb ingest-execution-log "$f" --agent claude-mention || true\n',
      ),
      [],
    );
    assert.deepEqual(readAgentRefs('        run: scripts/ai/run.sh --agent grow-lifehacker\n'), [
      'grow-lifehacker',
    ]);

    // `Use the <x> subagent` names an AGENT. zer0-mistakes writes both of its
    // bare-CLI lanes that way, and reading it as a skill citation reported two
    // correctly-wired lanes as having broken skill links.
    const review = scanWorkflow(
      '.github/workflows/ai-content-review.yml',
      fleetWorkflow('zer0-mistakes', 'ai-content-review.yml'),
    );
    assert.equal(review.agentRefs.includes('content-reviewer'), true);
    assert.equal(review.skillRefs.includes('content-reviewer'), false);

    // "Follow the skill in order:" names no skill. bash-365 writes exactly that,
    // and a looser reader reported `.claude/skills/the/SKILL.md` missing.
    assert.deepEqual(readWorkflowSkillRefs('            Follow the skill in order: read\n'), []);
    assert.deepEqual(readWorkflowSkillRefs('following the **content-loop** skill) then\n'), [
      'content-loop',
    ]);
  });

  test('the rest of the record — result file, labels, branch, setup, matrix, permissions', () => {
    const triage = scanWorkflow(
      '.github/workflows/triage.yml',
      fleetWorkflow('lifehacker', 'triage.yml'),
    );
    assert.deepEqual(triage.permissions, {
      contents: 'write',
      issues: 'write',
      'pull-requests': 'write',
    });
    assert.equal(triage.setup.ruby, '3.3');
    assert.equal(triage.setup.node, null, 'null is "this file does not say"');
    assert.equal(triage.branchPattern, 'triage/$(date +%Y%m%d-%H%M)');
    assert.deepEqual(triage.labels, ['source/triage-bot']);
    assert.equal(triage.continueOnError, true);

    const factory = scanWorkflow(
      '.github/workflows/content-factory.yml',
      fleetWorkflow('lifehacker', 'content-factory.yml'),
    );
    assert.equal(factory.resultFile, 'pr-result.txt');
    assert.equal(factory.matrix, 'static');
    assert.equal(factory.timeoutMinutes, 20);

    // The convention is not a rule: bash-365 asserts a different file.
    const loop = scanWorkflow(
      '.github/workflows/content-loop.yml',
      fleetWorkflow('bash-365', 'content-loop.yml'),
    );
    assert.equal(loop.resultFile, 'loop-result.json');

    // A planning job computes the fan-out.
    const dispatch = scanWorkflow(
      '.github/workflows/issue-autopilot.yml',
      fleetWorkflow('it-journey', 'issue-autopilot.yml'),
    );
    assert.equal(dispatch.matrix, 'dynamic');

    // The kit stamp, wherever in the header it is written.
    const template = scanWorkflow(
      '.github/workflows/ai-lane.template.yml',
      fleetWorkflow('hub', 'ai-lane.template.yml'),
    );
    assert.equal(template.kitStamp, 'ai-runner v__KIT_VERSION__');
    assert.equal(template.resultFile, 'pr-result.txt');
    assert.deepEqual(template.permissions, { contents: 'write', 'pull-requests': 'write' });
    assert.equal(
      scanWorkflow('.github/workflows/ai-lane.yml', fleetWorkflow('hub', 'ai-lane.yml')).kitStamp,
      'ai-runner v0.1.0',
      'the trailing sentence period is not part of the version',
    );
  });
});

suite('harness — deriving a lane (the `wtd fleet adopt` port)', () => {
  test('deriveLaneFromWorkflow agrees with the committed lifehacker manifest, all 17 lanes', async () => {
    // The manifest was generated by a Python script (`wtd fleet adopt`) reading
    // these exact files. Agreeing with it is what makes a DISAGREEMENT mean
    // something later: a drift row is only evidence if the derivation is known
    // to reproduce the tool that wrote the file.
    const io = inventoryIo('lifehacker');
    const manifestText = await io.read('fleet.manifest.yml');
    assert.notEqual(manifestText, undefined);
    const parsed = parseFleetManifest(manifestText ?? '');
    const lanes = parsed.manifest?.lanes ?? [];
    assert.equal(lanes.length, 17);

    const disagreements: string[] = [];
    for (const lane of lanes) {
      const text = await io.read(lane.implementation);
      assert.notEqual(text, undefined, `${lane.id}: ${lane.implementation} is staged`);
      const derived = deriveLaneFromWorkflow(lane.implementation, text ?? '');
      assert.equal(derived.id, lane.id);
      assert.equal(derived.implementation, lane.implementation);
      for (const row of compareLanes(lane, derived)) {
        disagreements.push(
          `${lane.id}.${row.field}: "${row.manifestSays}" vs "${row.workflowSays}"`,
        );
      }
    }
    assert.deepEqual(disagreements, [], 'the port reproduces adopt.py on every committed lane');
  });

  test('the port recognises an `ai-lane.yml` caller that adopt.py drops', () => {
    // `adopt.py:_HARNESS_PATTERNS` matches `claude-code-action`, `wtd fleet`, the
    // bare CLI (and `claude-run@`), and four engine script names. None of them
    // matches `uses: bamr87/bamr87/.github/workflows/ai-lane.yml@main`, so such a
    // lane gets `Harness.NONE` and is dropped from the manifest ENTIRELY — a lane
    // that runs an agent every Monday, invisible to the fleet's own inventory.
    const text = fleetWorkflow('hub', 'ai-lane.template.yml');
    assert.equal(upstreamWouldDropLane(text), true, 'upstream sees no harness here');

    const lane = deriveLaneFromWorkflow('.github/workflows/ai-lane.template.yml', text);
    assert.equal(lane.harness, 'claude-cli', 'this port derives the lane upstream loses');
    assert.deepEqual(
      lane.triggers.map((t) => t.kind),
      ['schedule', 'dispatch'],
    );

    // The divergence is only that one shape: everything upstream recognises, this
    // recognises the same way, including the two it maps to the same value.
    assert.equal(upstreamWouldDropLane(fleetWorkflow('lifehacker', 'content-factory.yml')), false);
    assert.equal(detectHarness(fleetWorkflow('lifehacker', 'content-factory.yml')), 'claude-cli');
    assert.equal(
      detectHarness(fleetWorkflow('lifehacker', 'factory--issue-factory-1.yml')),
      'claude-code-action',
    );
    assert.equal(
      detectHarness(fleetWorkflow('irony-works', 'germinate.yml')),
      'claude-cli',
      'the engine installs the CLI, and upstream matches the CLI first',
    );
    assert.equal(
      detectHarness(fleetWorkflow('zer0-mistakes', 'translate.yml')),
      'none',
      'upstream drops a lane that spends through a Ruby script',
    );

    // The `mention` kind is decided by the GATING EXPRESSION, never the bare
    // string: a fan-out workflow legitimately carries "@claude" as payload.
    assert.equal(detectKind('claude.yml', 'Claude', ''), 'mention');
    assert.equal(detectKind('content-factory.yml', 'content-factory', ''), 'content');
    assert.equal(detectKind('auto-fix.yml', 'auto-fix', ''), 'maintenance');

    // The eight-character switch pick, verbatim from upstream: the SORTED switch
    // list is walked and the first whose squashed name starts with the first
    // eight squashed characters of the stem wins. "contentscout" truncates to
    // "contents", which `contentfactoryenabled` does NOT start with — so the
    // scout's own switch wins even though the factory's sorts first.
    assert.equal(
      pickSwitch(['CONTENT_FACTORY_ENABLED', 'CONTENT_SCOUT_ENABLED'], 'content-scout'),
      'CONTENT_SCOUT_ENABLED',
    );
    // And when nothing matches the stem, the first mentioned wins.
    assert.equal(pickSwitch(['FLEET_ENABLED', 'ZZZ_ENABLED'], 'quest-forge'), 'FLEET_ENABLED');
    assert.equal(
      pickSwitch(['WIRE_SCOUT_ENABLED', 'FLEET_ENABLED'], 'wire-scout'),
      'WIRE_SCOUT_ENABLED',
    );
    assert.equal(pickSwitch([], 'anything'), null);
  });
});

suite('harness — the joins and the findings', () => {
  test('joinHarness produces one row per workflow, joining all seven artefacts', async () => {
    const inventory = await readHarnessInventory(
      '/fixtures/lifehacker',
      inventoryIo('lifehacker'),
      INVENTORY_OPTS,
    );
    assert.equal(inventory.root, '/fixtures/lifehacker');
    assert.equal(inventory.readAt, '2026-09-09T12:00:00.000Z');
    assert.equal(inventory.joins.length, inventory.workflows.length, 'one row per workflow');

    const factory = inventory.joins.find(
      (join) => join.workflowPath === '.github/workflows/content-factory.yml',
    );
    assert.equal(factory?.laneId, 'content-factory');
    assert.equal(factory?.agent, 'grow-lifehacker');
    assert.equal(factory?.skill, 'grow-lifehacker');
    assert.equal(factory?.switch, 'CONTENT_FACTORY_ENABLED');
    assert.deepEqual(factory?.tokens, [
      'ANTHROPIC_API_KEY',
      'CLAUDE_CODE_OAUTH_TOKEN',
      'FLEET_TOKEN',
    ]);
    assert.equal(factory?.costUsd, null, 'no ledger row for this lane is null, never 0');

    // The ledger's `workflow` key is the workflow's `name:`, not its filename
    // stem — the one committed row says "pipeline", and that is how spend
    // reaches a lane at all.
    const pipeline = inventory.joins.find(
      (join) => join.workflowPath === '.github/workflows/pipeline.yml',
    );
    assert.equal(pipeline?.laneId, 'pipeline');
    assert.equal(pipeline?.costUsd, inventory.ledger?.byWorkflow['pipeline']?.costUsd);
    assert.equal(typeof pipeline?.costUsd, 'number');

    // A workflow no lane claims still gets a row — with `laneId: null`, which is
    // a different answer from being absent from the table.
    const triage = inventory.joins.find(
      (join) => join.workflowPath === '.github/workflows/triage.yml',
    );
    assert.equal(triage?.laneId, null);
    assert.equal(triage?.switch, 'TRIAGE_ENABLED', 'the workflow still names its own switch');

    // The match rule is `implementation`, falling back to id <-> filename stem —
    // the same rule the engines' `laneForPath` uses, so the two agree.
    const lanes = inventory.manifest.manifest?.lanes ?? [];
    assert.equal(laneForWorkflow(lanes, '.github/workflows/triage.yml'), null);
    assert.equal(laneForWorkflow(lanes, '.github/workflows/theme-scout.yml')?.id, 'theme-scout');
    assert.equal(
      laneForWorkflow([laneStub({ id: 'orphan' })], '.github/workflows/orphan.yml')?.id,
      'orphan',
      'a manifest lane that names no path still matches by id',
    );
  });

  test('every dangling-reference finding fires — and none of them fires on healthy wiring', async () => {
    // 1 — a workflow naming an agent file that is not there.
    const dangling = joinHarness(
      joinInput({
        workflows: [scanWorkflow('.github/workflows/x.yml', 'name: x\n      agent: nobody\n')],
      }),
    );
    assert.equal(kindsOf(dangling.findings).includes('dangling-agent'), true);
    assert.equal(
      dangling.findings.find((f) => f.kind === 'dangling-agent')?.severity,
      'error',
      'a dangling agent means the role would run with no system prompt',
    );

    // 2 — a prompt naming a skill that is not there. zer0-mistakes' giscus lane
    //     really does say "Reply locally with the `giscus-conversation` skill",
    //     and that skill does not exist in that repository.
    const ghostSkill = joinInput({
      workflows: [
        scanWorkflow('.github/workflows/x.yml', 'name: x\n  prompt: "Use the ghost skill."\n'),
      ],
      hasSkillsDir: true,
    });
    assert.equal(kindsOf(joinHarness(ghostSkill).findings).includes('dangling-skill'), true);

    //     ...and NOT where the repository keeps no skills at all. A house that
    //     writes its procedures into the prompt has not broken a link it never made.
    assert.equal(
      kindsOf(joinHarness({ ...ghostSkill, hasSkillsDir: false }).findings).includes(
        'dangling-skill',
      ),
      false,
    );

    // 3 — `secrets.X || github.token`. `||` returns the first NON-EMPTY operand,
    //     so an expired PAT wins and the fallback is unreachable: eleven days of
    //     silent failures (bamr87/bamr87#53).
    const trap = 'name: x\n    env:\n      GH_TOKEN: ${{ secrets.FLEET_TOKEN || github.token }}\n';
    const chained = joinHarness(
      joinInput({
        workflows: [scanWorkflow('.github/workflows/x.yml', trap)],
        sources: { '.github/workflows/x.yml': trap },
      }),
    );
    assert.equal(kindsOf(chained.findings).includes('token-presence-chain'), true);

    //     ...but a COMMENT about the trap is not the trap. lifehacker's migrated
    //     `content-scout.yml` documents the idiom it was moved off, and its own
    //     `lint_tokens.rb` skips comment lines for exactly this reason.
    const documented =
      'name: x\n      # It used to read `${{ secrets.FLEET_TOKEN || github.token }}`. That is\n';
    const clean = joinHarness(
      joinInput({
        workflows: [scanWorkflow('.github/workflows/x.yml', documented)],
        sources: { '.github/workflows/x.yml': documented },
      }),
    );
    assert.equal(kindsOf(clean.findings).includes('token-presence-chain'), false);

    // 4 — a lane the manifest declares and no workflow implements.
    const orphanLane = joinHarness(
      joinInput({
        manifest: manifestOf([
          laneStub({ id: 'ghost', implementation: '.github/workflows/ghost.yml' }),
        ]),
      }),
    );
    assert.equal(kindsOf(orphanLane.findings).includes('lane-without-workflow'), true);

    // 5 — the other direction: a model-calling workflow no lane claims. bash-365
    //     commits no manifest at all, which is a normal state, not an error — so
    //     its four AI lanes are reported at `info`, not as failures (decision D9).
    const bash = await readHarnessInventory('/f/bash-365', inventoryIo('bash-365'), INVENTORY_OPTS);
    assert.equal(bash.manifest.manifest, null);
    assert.equal(bash.manifest.reason, 'not found: fleet.manifest.yml');
    const undeclared = bash.findings.filter((f) => f.kind === 'workflow-without-lane');
    assert.equal(undeclared.length, 4, 'four claude-code-action lanes, nothing declaring them');
    assert.deepEqual([...new Set(undeclared.map((f) => f.severity))], ['info']);

    // 6 — the switch enforced somewhere else, joined against the real manifest
    //     that records it.
    const worldview = await readHarnessInventory(
      '/f/ai-world-view',
      inventoryIo('ai-world-view'),
      INVENTORY_OPTS,
    );
    const hosted = worldview.findings.filter((f) => f.kind === 'switch-hosted-elsewhere');
    assert.equal(hosted.length, 1);
    assert.equal(hosted[0]?.path, '.github/workflows/grow-lineage.yml');
    assert.equal(hosted[0]?.message.includes('ORCHESTRATE_ENABLED'), true);
    assert.equal(hosted[0]?.message.includes('orchestrate.yml'), true);
    assert.equal(hosted[0]?.severity, 'info', 'it is prose, not a broken gate');

    // 7 — an agent whose front-matter name disagrees with its filename. Claude
    //     Code resolves `--agent` against the FILENAME, so the role no-ops.
    const mismatch = agentNameFindings([
      { ...parseAgentFile('.claude/agents/renamed.md', '---\nname: other\n---\n') },
    ]);
    assert.equal(mismatch.length, 1);
    assert.equal(mismatch[0]?.severity, 'error');

    // And the healthy half of the claim, which is the one that matters:
    // lifehacker's real wiring produces NO dangling reference of any kind.
    //
    // The fixture tree stages one agent file and one skill (they are large, and
    // the readers above already prove the four dialects). The full name lists come
    // from the committed manifest's own `agents:` and `skills:` blocks — nineteen
    // and seventeen entries that `wtd fleet adopt` wrote by listing the two
    // directories. Joining against those is joining against the real repository's
    // inventory without copying sixty-eight files to say so.
    const lifehacker = await readHarnessInventory(
      '/f/lifehacker',
      inventoryIo('lifehacker'),
      INVENTORY_OPTS,
    );
    const declared = lifehacker.manifest.manifest;
    assert.notEqual(declared, null);
    assert.equal(declared?.agents.length, 19);
    assert.equal(declared?.skills.length, 17);

    const real = joinHarness(
      joinInput({
        manifest: declared,
        workflows: lifehacker.workflows,
        agents: (declared?.agents ?? []).map((name) =>
          parseAgentFile(`.claude/agents/${name}.md`, `---\nname: ${name}\n---\n`),
        ),
        skills: (declared?.skills ?? [])
          .filter((name) => name !== '_shared')
          .map((name) =>
            parseSkillFile(`.claude/skills/${name}/SKILL.md`, `---\nname: ${name}\n---\n`),
          ),
        hasSkillsDir: true,
        sources: {},
      }),
    );
    assert.deepEqual(
      real.findings.map((f) => `${f.kind} ${f.path ?? ''}`),
      [],
      'a finding that fires on a healthy repository is a wrong rule, not a discovery',
    );
  });

  test('manifest drift is reported, never corrected', () => {
    const text = fleetWorkflow('lifehacker', 'content-factory.yml');
    const workflow = scanWorkflow('.github/workflows/content-factory.yml', text);
    const derived = deriveLaneFromWorkflow('.github/workflows/content-factory.yml', text);

    // Worth writing down, because it is the shape of drift this comparison
    // CANNOT find: the committed lane says `opens_pull_requests: false`, the lane
    // opens one pull request per collection per day, and the derivation agrees
    // with the manifest — because `gh pr create` is run by the AGENT, not by a
    // command line in the file. Inference reads command lines; an agent's
    // behaviour is not one. So the manifest is wrong and both readers say the
    // same wrong thing, which is exactly why a derived lane is never written back
    // over a committed one.
    assert.equal(derived.guardrails.opensPullRequests, false);

    // A rename, on the other hand, is text-visible in both places.
    const stale: FleetLane = { ...derived, switch: 'RENAMED_ENABLED' };
    assert.deepEqual(
      compareLanes(stale, derived).map((row) => row.field),
      ['switch'],
    );

    const findings = manifestDriftFindings(manifestOf([stale]), [workflow], {
      '.github/workflows/content-factory.yml': text,
    });
    assert.equal(findings.length, 1);
    assert.equal(findings[0]?.kind, 'manifest-drift');
    assert.equal(findings[0]?.severity, 'warning');
    assert.equal(findings[0]?.message.includes('RENAMED_ENABLED'), true);
    assert.equal(findings[0]?.message.includes('CONTENT_FACTORY_ENABLED'), true);

    // A guardrail the manifest DID claim and the workflow contradicts is drift.
    const lying: FleetLane = {
      ...derived,
      guardrails: { ...derived.guardrails, neverMerges: false },
    };
    assert.equal(derived.guardrails.neverMerges, true, 'no merge command runs here');
    assert.deepEqual(
      compareLanes(lying, derived).map((row) => row.field),
      ['never_merges'],
    );

    // A guardrail the manifest never claimed is a SILENCE, not a disagreement:
    // `null` means "the manifest did not say", and reporting that as drift is
    // exactly the mistake the tristate exists to prevent.
    const silent: FleetLane = {
      ...derived,
      guardrails: {
        neverMerges: null,
        opensPullRequests: null,
        writesDirectlyToDefaultBranch: null,
        writablePaths: [],
      },
    };
    assert.deepEqual(
      compareLanes(silent, derived).map((row) => row.field),
      [],
    );

    // With no manifest there is nothing to disagree with.
    assert.deepEqual(manifestDriftFindings(null, [workflow], {}), []);
  });
});

suite('harness — the ledger and the whole inventory', () => {
  test('readLedger reads the committed shape; an absent ledger is null, never zero', async () => {
    const ledger = await readLedger(inventoryIo('lifehacker'));
    assert.notEqual(ledger, null);
    assert.equal(ledger?.path, '_data/ai_usage/ledger.jsonl');
    assert.equal(ledger?.records, 1);
    assert.equal(ledger?.unit, 'api-equivalent-usd', 'API-equivalent dollars, not money billed');

    // `agent` joins to an agent file; `workflow` joins to the workflow's `name:`.
    assert.equal(ledger?.byRole['content-reviewer']?.calls, 1);
    assert.equal(ledger?.byWorkflow['pipeline']?.calls, 1);
    assert.equal((ledger?.byWorkflow['pipeline']?.costUsd ?? 0) > 0.6, true);

    // The three window totals come from the committed rollup, whose windows are
    // relative to ITS `generated_at` — recomputing them against now would
    // silently answer a different question than the site's own usage page.
    assert.equal(ledger?.allTimeUsd, 0.6397);
    assert.equal(ledger?.last7dUsd, 0.6397);
    assert.equal(ledger?.last30dUsd, 0.6397);

    // Five of the fleet's six repositories meter nothing at all.
    assert.equal(await readLedger(inventoryIo('it-journey')), null);
    assert.equal(parseLedger('_data/ai_usage/ledger.jsonl', undefined, undefined), null);

    // A truncated last line costs that row, never the file: the ledger is
    // append-only and written by more than one script.
    const partial = parseLedger(
      'l.jsonl',
      '{"agent":"a","workflow":"w","cost_usd":1.5}\n{"agent":"b","wor',
    );
    assert.equal(partial?.records, 1);
    assert.equal(partial?.allTimeUsd, 1.5);

    // A ledger whose rows carry no cost reports `null`, not `0` — a zero adds up.
    const costless = parseLedger('l.jsonl', '{"agent":"a","workflow":"w"}\n');
    assert.equal(costless?.records, 1);
    assert.equal(costless?.allTimeUsd, null);
  });

  test('readHarnessInventory reads the whole harness, and reports BOTH skill counts', async () => {
    const inventory = await readHarnessInventory(
      '/fixtures/lifehacker',
      inventoryIo('lifehacker'),
      INVENTORY_OPTS,
    );

    assert.equal(inventory.manifest.manifest?.repo, 'bamr87/lifehacker.dev');
    assert.equal(inventory.manifest.manifest?.lanes.length, 17);
    assert.equal(inventory.workflows.length, 19, 'the seventeen lanes plus triage and ai-usage');
    assert.equal(inventory.aiConfig?.model, 'claude-opus-4-8');
    assert.equal(inventory.guardrailsDoc?.path, '.claude/skills/_shared/quarantine.md');
    assert.equal(inventory.guardrailsDoc?.kit, 'agent-context v0.4.0');
    assert.notEqual(inventory.ledger, null);

    // The two counters disagree about `_shared/`, and both are right under their
    // own definition. Nothing here silently picks a winner: a scorecard showing
    // one number would be telling a repository that its own lint is wrong.
    assert.deepEqual(inventory.skillCount, { lintAgents: 1, wtdAdopt: 2 });
    assert.equal(inventory.skills.length, 1, 'one SKILL.md is staged; `_shared` is not a skill');
    assert.deepEqual(
      skillCountsFor([
        '_shared',
        'agent-skill-review',
        'content-import',
        'content-reviewer',
        'content-scout',
        'devops-manager',
        'fleet-bugfix',
        'grow-lifehacker',
        'loop-tuner',
        'quest-forge',
        'session-retrospective',
        'site-explorer',
        'test-lifehacker',
        'theme-scout',
        'triage-lifehacker',
        'weekly-epic',
        'wire-scout',
      ]),
      { lintAgents: 16, wtdAdopt: 17 },
      "the real repository: its own lint says 16, `wtd fleet adopt` says 17",
    );

    // A repository with none of this is a normal repository, not an error.
    const empty = await readHarnessInventory(
      '/fixtures/nothing',
      {
        async list(): Promise<string[]> {
          return [];
        },
        async read(): Promise<string | undefined> {
          return undefined;
        },
      },
      INVENTORY_OPTS,
    );
    assert.equal(empty.manifest.manifest, null);
    assert.equal(empty.manifest.reason, 'not found: fleet.manifest.yml');
    assert.deepEqual(empty.workflows, []);
    assert.deepEqual(empty.agents, []);
    assert.equal(empty.aiConfig, null);
    assert.equal(empty.ledger, null, 'unmetered is `null`, never `$0.00`');
    assert.equal(empty.guardrailsDoc, null);
    assert.deepEqual(empty.findings, []);
    assert.deepEqual(empty.joins, []);
    assert.equal(describeHarnessInventory(empty).includes('no manifest'), true);
    assert.equal(describeHarnessInventory(empty).includes('unmetered'), true);
  });
});
