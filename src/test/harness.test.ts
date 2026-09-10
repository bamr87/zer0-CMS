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
import { parseSkillFile, readSkills, skillCountsFor } from '../core/harness/skills';
import { resolveConfig } from '../core/shared/config';
import type { AiConfig, McpStdioSpec, Zer0Config } from '../core/shared/types';

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
