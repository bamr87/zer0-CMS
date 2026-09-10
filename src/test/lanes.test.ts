/**
 * Lane generation (decision D-E) — the suite that keeps what this console writes
 * honest about the shape it is writing into.
 *
 * Three kinds of claim are pinned here, and they fail for three different
 * reasons, which is the point of separating them:
 *
 *  1. **Drift against the hub.** `AI_LANE_INPUTS` and `AI_LANE_SECRETS` are
 *     copies of somebody else's declaration, so they are parsed back out of a
 *     verbatim fixture copy of `bamr87/bamr87/.github/workflows/ai-lane.yml` and
 *     compared. A new input upstream fails a test that names the input, rather
 *     than becoming a capability this console silently never offers. The
 *     vendored caller template is byte-compared against the same fixture set, so
 *     a refresh of the shipped copy that forgot the fixture (or the reverse) is
 *     a failing test rather than a generator rendering against a template
 *     nothing pins.
 *  2. **Byte goldens.** Three rendered lanes — Ruby/Jekyll, Python/MkDocs,
 *     Node/Wiki.js — plus the gate+claude-run form, the agent file, the skill
 *     stub, the manifest entry and the manifest after it is appended. Every one
 *     is produced by `fixtures/golden/lanes/generate.mjs` and NEVER hand-edited;
 *     the specs behind them are generated too (`specs.json`), so a spec that
 *     moved and a golden that did not is a failure rather than a quiet
 *     divergence between what the generator drew and what this file checks.
 *  3. **The house rules.** The kit stamp on line 1, an odd cron minute, no
 *     `secrets.X || …` presence chain, an `*_ENABLED` switch on every lane, and
 *     never a `factory--*.yml`. These are asserted over *everything* the
 *     renderers produce rather than over one example, because a rule that holds
 *     for the case somebody wrote a test for is not a rule.
 *
 * No network, no `vscode`, and the only writes are into a `mkdtemp` directory —
 * which the `planScaffold` test then asserts is still empty, because a planner
 * that writes is the one failure a plan-then-confirm flow cannot survive.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { parse as parseYaml } from 'yaml';

import { parseAgentFile } from '../core/harness/agents';
import {
  classifyExpressibility,
  parseKitVersion,
  planScaffold,
  scaffoldGateFacts,
  type ScaffoldContext,
} from '../core/harness/lanes';
import {
  appendLaneToManifest,
  laneIdOf,
  laneIdsIn,
  switchesIn,
} from '../core/harness/manifestWrite';
import { preflightLaneSpec } from '../core/harness/preflight';
import {
  AI_LANE_INPUTS,
  AI_LANE_OWNED_LINES,
  AI_LANE_PLACEHOLDERS,
  AI_LANE_SECRETS,
  HUB_CLAUDE_RUN_USES,
  renderAgentFile,
  renderAiLaneCaller,
  renderGateAndClaudeRun,
  renderManifestLane,
  renderSkillStub,
  TEMPLATE_FILES,
} from '../core/harness/render';
import { selfAudit } from '../core/harness/selfAudit';
import { emitYaml, yamlScalar } from '../core/harness/emitYaml';
import type { LaneSpec, ScaffoldPlan } from '../core/shared/types';

const REPO = path.resolve(__dirname, '../..');
const GOLDEN = path.join(REPO, 'src/test/fixtures/golden/lanes');
const HUB_FIXTURE = path.join(REPO, 'src/test/fixtures/harness/hub');

function repoFile(rel: string): string {
  return fs.readFileSync(path.join(REPO, rel), 'utf8');
}

function golden(name: string): string {
  return fs.readFileSync(path.join(GOLDEN, name), 'utf8');
}

const TEMPLATE = repoFile(TEMPLATE_FILES.aiLane);
const AGENT_TEMPLATE = repoFile(TEMPLATE_FILES.agent);
const VERSION_FILE = repoFile(TEMPLATE_FILES.version);
const KIT_VERSION = parseKitVersion(VERSION_FILE) ?? '';

/** The four specs the goldens were generated from — generated beside them. */
const SPECS = JSON.parse(golden('specs.json')) as Record<
  'jekyll' | 'mkdocs' | 'wikijs' | 'matrixed',
  LaneSpec
>;

/**
 * The goldens carry the kit version that produced them. When the vendored
 * VERSION moves past it, a golden failing says nothing useful — the fix is to
 * re-run the generator and read the diff — so the byte comparisons skip with a
 * note, exactly as `engines.test.ts` does for the engines package.
 */
const GOLDEN_KIT = /kit: ai-runner v(.+)/.exec(golden('LANES_VERSION'))?.[1] ?? '';
const GOLDENS_CURRENT = GOLDEN_KIT === KIT_VERSION;

function assertGolden(name: string, actual: string): void {
  if (!GOLDENS_CURRENT) {
    return;
  }
  assert.equal(
    actual,
    golden(name),
    `${name} is stale — re-run: npx tsc -p . --outDir out && node src/test/fixtures/golden/lanes/generate.mjs, then READ the diff`,
  );
}

/** Everything the four specs render to, for the rules asserted over all of it. */
function everythingRendered(): Array<{ what: string; text: string }> {
  const out: Array<{ what: string; text: string }> = [];
  for (const [name, spec] of Object.entries(SPECS)) {
    out.push({ what: `${name}:caller`, text: renderAiLaneCaller(spec, TEMPLATE) });
    out.push({ what: `${name}:gate+claude-run`, text: renderGateAndClaudeRun(spec) });
    out.push({ what: `${name}:agent`, text: renderAgentFile(spec, AGENT_TEMPLATE) });
    out.push({ what: `${name}:skill`, text: renderSkillStub(spec) });
    out.push({ what: `${name}:manifest`, text: renderManifestLane(spec) });
  }
  return out;
}

function specWith(base: LaneSpec, overrides: Partial<LaneSpec>): LaneSpec {
  return { ...base, ...overrides };
}

/** A context that reads nothing and can therefore write nothing. */
function emptyContext(overrides: Partial<ScaffoldContext> = {}): ScaffoldContext {
  return {
    template: TEMPLATE,
    agentTemplate: AGENT_TEMPLATE,
    manifestText: golden('manifest-before.yml'),
    existing: async () => undefined,
    ...overrides,
  };
}

suite('lanes: the hub contract', () => {
  test('AI_LANE_INPUTS equals the workflow_call inputs of the hub fixture', () => {
    const hub = parseYaml(fs.readFileSync(path.join(HUB_FIXTURE, 'ai-lane.yml'), 'utf8'));
    const inputs = Object.keys(hub.on.workflow_call.inputs);
    assert.deepEqual(
      [...AI_LANE_INPUTS],
      inputs,
      'the hub has changed its reusable lane; the generator offers a different set of inputs than it accepts',
    );
    assert.equal(AI_LANE_INPUTS.length, 21);
    // The five the template already carries are a subset, spelled the same way.
    for (const key of ['lane', 'switch', 'agent', 'prompt', 'tools']) {
      assert.ok(AI_LANE_INPUTS.includes(key), `the template writes \`${key}\`, the workflow does not accept it`);
    }
  });

  test('AI_LANE_SECRETS equals the workflow_call secrets of the hub fixture', () => {
    const hub = parseYaml(fs.readFileSync(path.join(HUB_FIXTURE, 'ai-lane.yml'), 'utf8'));
    assert.deepEqual([...AI_LANE_SECRETS], Object.keys(hub.on.workflow_call.secrets));
    assert.equal(AI_LANE_SECRETS.length, 4);
    // The template passes three of the four; OPENAI_API_KEY is opt-in per lane.
    assert.ok(TEMPLATE.includes('CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}'));
    assert.ok(TEMPLATE.includes('GH_PAT: ${{ secrets.FLEET_TOKEN }}'));
  });

  test('the shipped templates are byte-identical to the fixture copies', () => {
    assert.equal(
      TEMPLATE,
      fs.readFileSync(path.join(HUB_FIXTURE, 'ai-lane.template.yml'), 'utf8'),
      'media/templates/ai-lane.template.yml and the fixture copy have diverged — refresh BOTH from the hub (media/templates/README.md)',
    );
    assert.equal(VERSION_FILE, fs.readFileSync(path.join(HUB_FIXTURE, 'VERSION'), 'utf8'));
    assert.equal(KIT_VERSION, '0.1.0');
  });

  test('the vendored template declares the five placeholders and every owned line', () => {
    for (const placeholder of AI_LANE_PLACEHOLDERS) {
      assert.ok(TEMPLATE.includes(placeholder), `the template no longer declares ${placeholder}`);
    }
    const lines = TEMPLATE.split('\n');
    for (const [name, line] of Object.entries(AI_LANE_OWNED_LINES)) {
      assert.ok(
        lines.includes(line),
        `the template no longer carries the line the renderer owns as \`${name}\` — a refreshed template must be re-read, not rendered against blind`,
      );
    }
    // The runner is referenced, never copied.
    assert.ok(TEMPLATE.includes('uses: bamr87/bamr87/.github/workflows/ai-lane.yml@main'));
  });
});

suite('lanes: rendered goldens', () => {
  test('a Ruby/Jekyll content lane renders to its golden', () => {
    assertGolden('caller-jekyll-ruby.yml', renderAiLaneCaller(SPECS.jekyll, TEMPLATE));
  });

  test('a Python/MkDocs docs audit renders to its golden', () => {
    const text = renderAiLaneCaller(SPECS.mkdocs, TEMPLATE);
    assertGolden('caller-mkdocs-python.yml', text);
    // The platform is the difference: Python, and a pre-run block scalar.
    assert.ok(text.includes('setup-python: "3.12"'));
    assert.ok(!text.includes('setup-ruby'), 'the template\'s hard-coded Ruby survived into a Python lane');
    assert.ok(text.includes('pre-run: |'));
  });

  test('a Node/Wiki.js review lane renders to its golden', () => {
    const text = renderAiLaneCaller(SPECS.wikijs, TEMPLATE);
    assertGolden('caller-wikijs-node.yml', text);
    // Event-driven: the schedule block is gone, the event is declared, and the
    // dispatch line stays because a human running a lane by hand is the escape
    // hatch that makes an off-by-default switch safe.
    assert.ok(!text.includes('schedule:'));
    assert.ok(text.includes('  pull_request:'));
    assert.ok(text.includes('  workflow_dispatch:'));
    assert.ok(text.includes('cancel-in-progress: true'));
  });

  test('the gate+claude-run shape renders to its golden', () => {
    const text = renderGateAndClaudeRun(SPECS.matrixed);
    assertGolden('gate-claude-run-jekyll.yml', text);
    const parsed = parseYaml(text);
    assert.deepEqual(Object.keys(parsed.jobs), ['gate', 'run']);
    assert.deepEqual(parsed.jobs.run.strategy.matrix, {
      item: ['hack', 'tool', 'post', 'doc', 'wire'],
    });
    assert.equal(parsed.jobs.run.strategy['max-parallel'], 1);
    assert.equal(parsed.jobs.run['timeout-minutes'], 20);
    // The composite is referenced at @main, never vendored.
    assert.equal(parsed.jobs.run.steps.find((s: { uses?: string }) => s.uses?.includes('claude-run')).uses, HUB_CLAUDE_RUN_USES);
  });

  test('renderAiLaneCaller is a substitution: the hub template survives it', () => {
    const comments = TEMPLATE.split('\n').filter((line) => line.trim().startsWith('#'));
    assert.ok(comments.length >= 3);
    for (const spec of Object.values(SPECS)) {
      const rendered = renderAiLaneCaller(spec, TEMPLATE);
      const lines = rendered.split('\n');
      // Every whole-line comment the hub wrote, still there, still in order.
      let cursor = 0;
      for (const comment of comments) {
        const filled = comment.split('__KIT_VERSION__').join(spec.kitVersion);
        const at = lines.indexOf(filled, cursor);
        assert.notEqual(at, -1, `the hub's comment vanished from a rendered lane: ${filled}`);
        cursor = at;
      }
      // And nothing left unfilled.
      for (const placeholder of AI_LANE_PLACEHOLDERS) {
        assert.ok(!rendered.includes(placeholder), `${placeholder} survived into ${spec.id}`);
      }
      assert.ok(parseYaml(rendered) !== null, `${spec.id} did not render to valid YAML`);
    }
  });

  test('the agent file carries the guardrail citation and the Hard rules', () => {
    const text = renderAgentFile(SPECS.jekyll, AGENT_TEMPLATE);
    assertGolden('agent-jekyll.md', text);
    assertGolden('agent-wikijs.md', renderAgentFile(SPECS.wikijs, AGENT_TEMPLATE));

    // Read back through the fleet's own reader, not a regex written for this test.
    const record = parseAgentFile('.claude/agents/grow-lifehacker.md', text);
    assert.equal(record.name, 'grow-lifehacker');
    assert.ok(record.nameMatchesFile, 'the front-matter name must equal the filename stem');
    assert.deepEqual(record.tools, ['Bash', 'Read', 'Write', 'Edit', 'Grep', 'Glob']);
    assert.equal(record.kitStamp, `ai-runner v${KIT_VERSION}`);
    assert.ok(record.citesQuarantine, 'the agent file must CITE the shared guardrails, not restate them');
    assert.deepEqual(record.skillRefs, ['grow-lifehacker']);
    assert.equal(record.dialect, 'it-journey', 'the unbolded Guardrails line is the hub template dialect');

    assert.ok(text.includes('## Hard rules'));
    assert.ok(text.includes('write the resulting PR URL to `pr-result.txt`'));
    assert.ok(/\*\*Never merge\.\*\*/.test(text), 'every agent file in this fleet ends at "Never merge"');
    assert.ok(text.includes('Never weaken a guardrail'));
    // The result file follows the spec, not a constant.
    assert.ok(renderAgentFile(SPECS.wikijs, AGENT_TEMPLATE).includes('`review-result.txt`'));
  });

  test('the skill stub renders to its golden and says it is a stub', () => {
    const text = renderSkillStub(SPECS.jekyll);
    assertGolden('skill-jekyll.md', text);
    assert.ok(text.includes('**This is a stub.**'), 'a generated routine nobody wrote must say so');
    assert.ok(text.includes('## When to use'));
    assert.ok(text.includes('## The routine'));
    assert.ok(text.includes('## What it never does'));
    assert.ok(text.includes('_shared/quarantine.md'));
  });
});

suite('lanes: the house rules', () => {
  test('the kit stamp is line 1 of every workflow and matches the vendored VERSION', () => {
    const stamp = `# kit: ai-runner v${KIT_VERSION}`;
    for (const spec of Object.values(SPECS)) {
      for (const text of [renderAiLaneCaller(spec, TEMPLATE), renderGateAndClaudeRun(spec)]) {
        const first = text.split('\n')[0] ?? '';
        assert.ok(first.startsWith(stamp), `line 1 is not the kit stamp: ${first}`);
        // A stamped file that GitHub cannot parse is a stamped file nobody runs,
        // so every workflow either renderer produces is parsed here — both
        // shapes, all four specs, schedules and events alike.
        const parsed = parseYaml(text);
        assert.ok(parsed?.jobs !== undefined, `${spec.id} rendered a workflow with no jobs`);
        assert.equal(parsed.name, spec.id);
      }
      // Markdown cannot open with a YAML comment above its front matter, so the
      // same stamp appears inside it AND as the comment `readKitStamp` reads.
      for (const text of [renderAgentFile(spec, AGENT_TEMPLATE), renderSkillStub(spec)]) {
        const lines = text.split('\n');
        assert.equal(lines[0], '---');
        assert.equal(lines[1], stamp);
        assert.ok(text.includes(`<!-- kit: ai-runner v${KIT_VERSION} -->`));
      }
    }
  });

  test('nothing rendered carries a `secrets.X || …` presence chain', () => {
    for (const { what, text } of everythingRendered()) {
      // Whole-line comments are dropped first: the generated gate *quotes* the
      // trap in a comment to explain why it probes instead, and a chain nothing
      // evaluates cannot degrade a token.
      const live = text
        .split('\n')
        .filter((line) => !line.trim().startsWith('#'))
        .join('\n');
      assert.ok(
        !/secrets\.[A-Z_][A-Z0-9_]*\s*\|\|/.test(live),
        `${what} degrades a token with \`||\` — an expired PAT is present, wins the chain, and fails at push time`,
      );
    }
    // What the gate does instead: probe, then export the winner — and say why.
    const gate = renderGateAndClaudeRun(SPECS.matrixed);
    assert.ok(gate.includes('gh api user -q .login'));
    assert.ok(gate.includes('echo "GH_TOKEN=$PAT" >> "$GITHUB_ENV"'));
    assert.ok(gate.includes('# NOT `${{ secrets.FLEET_TOKEN || github.token }}`'));
  });

  test('nothing is scheduled on the hour, and every lane carries its switch', () => {
    for (const { what, text } of everythingRendered()) {
      for (const match of text.matchAll(/cron:\s*"?([^"\n#]+)"?/g)) {
        const minute = (match[1] ?? '').trim().split(/\s+/)[0];
        assert.notEqual(minute, '0', `${what} fires on the hour: ${match[1]}`);
      }
    }
    for (const [name, spec] of Object.entries(SPECS)) {
      assert.ok(spec.switch !== null);
      assert.ok(
        renderAiLaneCaller(spec, TEMPLATE).includes(`switch: ${spec.switch}`),
        `${name}'s caller lost its kill switch`,
      );
      assert.ok(
        renderGateAndClaudeRun(spec).includes(`vars.${spec.switch}`),
        `${name}'s gate lost its kill switch`,
      );
    }
    // And a spec that tried to schedule on the hour never gets that far.
    const onTheHour = specWith(SPECS.jekyll, { cron: '0 9 * * *' });
    assert.ok(
      preflightLaneSpec(onTheHour).some((f) => f.message.includes('fires on the hour')),
      'the real content-factory cron (0 9 * * *) must be refused, not copied',
    );
  });

  test('a rendered file never targets a GitFactory-compiled `factory--*.yml`', async () => {
    const spec = specWith(SPECS.jekyll, { id: 'factory--issue-factory-1' });
    const verdict = classifyExpressibility(spec);
    assert.equal(verdict.shape, 'bespoke');
    assert.ok(verdict.reasons.some((r) => r.includes('GitFactory')));

    const plan = await planScaffold(spec, emptyContext());
    assert.deepEqual(plan.files, [], 'a factory-owned lane must render no files at all');
    assert.equal(plan.manifest, null);
    assert.ok(preflightLaneSpec(spec).some((f) => f.message.includes("compiler's files")));

    // Nothing any renderer produces, for any spec, ever names such a file.
    for (const { what, text } of everythingRendered()) {
      assert.ok(!/factory--/.test(text), `${what} names a GitFactory-compiled workflow`);
    }
  });
});

suite('lanes: expressibility', () => {
  test("classifyExpressibility answers the kit's six cases with reasons", () => {
    const cases: Array<{ label: string; spec: Partial<LaneSpec>; says: string }> = [
      { label: 'dynamic matrix', spec: { matrix: { dynamic: true } }, says: 'computed at run time' },
      { label: 'cross-repo checkout', spec: { crossRepoCheckout: true }, says: 'another repository' },
      { label: 'PR-head checkout', spec: { prHeadCheckout: true }, says: "pull request's head" },
      { label: 'several model passes', spec: { modelPasses: 3 }, says: '3 model passes' },
      {
        label: 'multi-job artifact hand-off',
        spec: { preRun: 'gh run download --name contract # actions/download-artifact' },
        says: "another job's artifact",
      },
      {
        label: 'bare-CLI stdout capture',
        spec: { postRun: 'claude -p "grade it" --output-format text > verdict.txt' },
        says: 'bare-CLI lane',
      },
    ];
    for (const one of cases) {
      const verdict = classifyExpressibility(specWith(SPECS.jekyll, one.spec));
      assert.equal(verdict.shape, 'bespoke', `${one.label} should be bespoke`);
      assert.ok(
        verdict.reasons.some((r) => r.includes(one.says)),
        `${one.label} gave no actionable reason: ${verdict.reasons.join(' | ')}`,
      );
    }

    // And the two shapes it CAN write, each with its reason for being chosen.
    assert.deepEqual(classifyExpressibility(SPECS.jekyll), { shape: 'ai-lane-caller', reasons: [] });
    const matrixed = classifyExpressibility(SPECS.matrixed);
    assert.equal(matrixed.shape, 'gate+claude-run');
    assert.ok(matrixed.reasons[0]?.includes('fans out over 5 items'));
    const strictSwitch = classifyExpressibility(
      specWith(SPECS.jekyll, { dispatchBypassesSwitch: false }),
    );
    assert.equal(strictSwitch.shape, 'gate+claude-run');
    assert.ok(strictSwitch.reasons[0]?.includes('even for a manual run'));
    // …and the gate it writes really does hold on a manual run.
    const gate = renderGateAndClaudeRun(specWith(SPECS.jekyll, { dispatchBypassesSwitch: false }));
    assert.ok(!gate.includes('"$EVENT" != "workflow_dispatch"'));
  });
});

suite('lanes: the manifest', () => {
  test('renderManifestLane emits the fleet/v1 wire vocabulary', () => {
    const text = [SPECS.jekyll, SPECS.mkdocs, SPECS.wikijs]
      .map((spec) => renderManifestLane(spec))
      .join('');
    assertGolden('manifest-lanes.yml', text);

    const lanes = parseYaml(renderManifestLane(SPECS.wikijs));
    assert.equal(lanes.length, 1);
    assert.deepEqual(Object.keys(lanes[0]), [
      'id',
      'kind',
      'harness',
      'implementation',
      'description',
      'triggers',
      'switch',
      'uses_tokens',
      'guardrails',
    ]);
    assert.equal(lanes[0].harness, 'claude-cli');
    assert.equal(lanes[0].implementation, '.github/workflows/content-review.yml');
    assert.deepEqual(lanes[0].triggers, [
      { kind: 'event', events: ['pull_request'] },
      { kind: 'dispatch' },
    ]);
    // Stated, not left absent: an unsaid guardrail is a tristate, and a lane
    // whose agent file ends in "Never merge" should say so where tools read it.
    assert.equal(lanes[0].guardrails.never_merges, true);
  });

  test('appendLaneToManifest inserts before `tokens:` and leaves every other byte alone', () => {
    const before = golden('manifest-before.yml');
    const result = appendLaneToManifest(before, renderManifestLane(SPECS.jekyll));
    assert.ok('text' in result, 'the append refused a manifest it should have accepted');
    assertGolden('manifest-after.yml', result.text);

    // Line surgery: the only change is an insertion.
    const beforeLines = before.split('\n');
    const afterLines = result.text.split('\n');
    const added = afterLines.length - beforeLines.length;
    assert.equal(added, renderManifestLane(SPECS.jekyll).replace(/\n+$/, '').split('\n').length);
    assert.deepEqual(afterLines.slice(0, 35), beforeLines.slice(0, 35));
    assert.deepEqual(afterLines.slice(35 + added), beforeLines.slice(35));

    // The things a re-emitter would have destroyed.
    assert.ok(result.text.startsWith("# fleet.manifest.yml — this repository's AI fleet, in the"));
    assert.ok(result.text.includes('provenance: derived'));
    assert.ok(result.text.includes('# The token contract. Every name here is a repository secret a human created.'));
    const parsed = parseYaml(result.text);
    assert.deepEqual(
      parsed.lanes.map((l: { id: string }) => l.id),
      ['agent-review', 'triage', 'content-factory'],
    );
    assert.equal(parsed.tokens.length, 1);
  });

  test('appendLaneToManifest refuses a duplicate id and a document with no lanes', () => {
    const before = golden('manifest-before.yml');
    const duplicate = renderManifestLane(specWith(SPECS.jekyll, { id: 'triage' }));
    const refused = appendLaneToManifest(before, duplicate);
    assert.ok('refused' in refused);
    assert.ok(refused.refused.includes('already declares a lane called `triage`'));

    const noLanes = appendLaneToManifest('spec_version: fleet/v1\nrepo: a/b\n', renderManifestLane(SPECS.jekyll));
    assert.ok('refused' in noLanes && noLanes.refused.includes('no `lanes:` key'));

    const notALane = appendLaneToManifest(before, 'id: content-factory\n');
    assert.ok('refused' in notALane && notALane.refused.includes('- id:'));

    assert.deepEqual(laneIdsIn(before), ['agent-review', 'triage']);
    assert.equal(laneIdOf(renderManifestLane(SPECS.jekyll)), 'content-factory');
    assert.deepEqual(switchesIn(before), ['AGENT_REVIEW_ENABLED']);
  });

  test('emitYaml is deterministic and quotes only what it must', () => {
    const value = {
      id: 'content-factory',
      switch: null,
      triggers: [{ kind: 'schedule', cron: '17 9 * * *' }, { kind: 'dispatch' }],
      uses_tokens: [] as string[],
      guardrails: { never_merges: true, writable_paths: ['pages/_posts'] },
      summary: 'Two lanes: one writes, one reads.',
    };
    const once = emitYaml(value);
    assert.equal(once, emitYaml(structuredClone(value)), 'two dumps of one value disagreed');
    assert.equal(
      once,
      [
        'id: content-factory',
        'switch: null',
        'triggers:',
        '- kind: schedule',
        '  cron: "17 9 * * *"',
        '- kind: dispatch',
        'uses_tokens: []',
        'guardrails:',
        '  never_merges: true',
        '  writable_paths:',
        '  - pages/_posts',
        'summary: "Two lanes: one writes, one reads."',
        '',
      ].join('\n'),
    );
    // The predicate, spelled out: plain where it can be, quoted where YAML would
    // otherwise read something else.
    assert.equal(yamlScalar('pr-result.txt'), 'pr-result.txt');
    assert.equal(yamlScalar('yes'), '"yes"');
    assert.equal(yamlScalar('17 9 * * *'), '"17 9 * * *"');
    assert.equal(yamlScalar(null), 'null');
    assert.equal(yamlScalar(30), '30');
  });
});

suite('lanes: preflight and the plan', () => {
  test('preflightLaneSpec catches what the house rules forbid', () => {
    assert.deepEqual(preflightLaneSpec(SPECS.jekyll), [], 'a clean spec produced findings');

    const noSwitch = preflightLaneSpec(specWith(SPECS.jekyll, { switch: null }));
    assert.equal(noSwitch.length, 1);
    assert.equal(noSwitch[0]?.kind, 'switch-hosted-elsewhere');
    assert.equal(noSwitch[0]?.severity, 'error');
    assert.ok(noSwitch[0]?.message.includes('kill switch is hosted nowhere'));

    const misnamed = preflightLaneSpec(specWith(SPECS.jekyll, { switch: 'CONTENT_FACTORY' }));
    assert.ok(misnamed.some((f) => f.message.includes('is not a kill-switch name')));

    const onTheHour = preflightLaneSpec(specWith(SPECS.jekyll, { cron: '0 9 * * *' }));
    assert.equal(onTheHour.length, 1);
    assert.equal(onTheHour[0]?.severity, 'error');

    const chained = preflightLaneSpec(
      specWith(SPECS.jekyll, { postRun: 'GH_TOKEN=${{ secrets.FLEET_TOKEN || github.token }} gh pr list' }),
    );
    assert.equal(chained[0]?.kind, 'token-presence-chain');
    assert.ok(chained[0]?.message.includes('expired token is present'));

    const silent = preflightLaneSpec(
      specWith(SPECS.jekyll, { prompt: 'Write something good and stop. Never merge.' }),
    );
    assert.equal(silent[0]?.kind, 'unmetered-model-call');
    assert.ok(silent[0]?.message.includes('never tells the agent to write it'));

    // The real content-factory's five-way fan-out, with a prompt that forgot to
    // name the leg: five agents, one instruction, four duplicates.
    const blindMatrix = preflightLaneSpec(
      specWith(SPECS.matrixed, { prompt: SPECS.jekyll.prompt }),
    );
    assert.ok(blindMatrix.some((f) => f.message.includes('fans out over 5 items')));

    const badNames = preflightLaneSpec(specWith(SPECS.jekyll, { agent: 'Grow Lifehacker' }));
    assert.equal(badNames[0]?.kind, 'agent-name-mismatch');
  });

  test('planScaffold reports everything and writes nothing', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'zer0-lanes-'));
    try {
      // One of the three files is already there; the plan must say so rather
      // than overwrite it, and the gate refuses on that fact.
      const existingWorkflow = '.github/workflows/content-factory.yml';
      fs.mkdirSync(path.join(root, '.github/workflows'), { recursive: true });
      fs.writeFileSync(path.join(root, existingWorkflow), '# somebody wrote this by hand\n');
      const treeBefore = snapshot(root);

      const audits: ScaffoldPlan[] = [];
      const plan = await planScaffold(
        SPECS.jekyll,
        emptyContext({
          existing: async (rel) => {
            try {
              return fs.readFileSync(path.join(root, rel), 'utf8');
            } catch {
              return undefined;
            }
          },
          audit: (p) => {
            audits.push(p);
            return selfAudit(p);
          },
        }),
      );

      assert.equal(plan.shape, 'ai-lane-caller');
      assert.deepEqual(
        plan.files.map((f) => f.rel),
        [
          '.github/workflows/content-factory.yml',
          '.claude/agents/grow-lifehacker.md',
          '.claude/skills/grow-lifehacker/SKILL.md',
        ],
      );
      assert.deepEqual(
        plan.files.map((f) => f.exists),
        [true, false, false],
        'the plan must know which files already exist before anything is written',
      );
      assert.ok(plan.manifest !== null);
      assert.equal(plan.manifest?.rel, 'fleet.manifest.yml');
      assert.notEqual(plan.manifest?.before, plan.manifest?.after);

      // The switch is a NOTE. Writing a file and creating a repository variable
      // are different powers, and this plan exercises exactly one of them.
      assert.equal(plan.switchToCreateLater, 'CONTENT_FACTORY_ENABLED');

      // The self-audit ran over what would be written, and nothing it generates
      // trips a failing rule. `pin-branch`, `concurrency` and `top-level-write`
      // are the documented blind spots of a rulebook that cannot follow a
      // `uses:` into the hub — reported, never suppressed.
      assert.equal(audits.length, 1);
      const fails = plan.audit.filter((f) => f.severity === 'fail');
      assert.deepEqual(fails, [], `a generated lane failed its own audit: ${JSON.stringify(fails)}`);
      assert.ok(plan.audit.some((f) => f.rule === 'concurrency'));
      assert.ok(!plan.audit.some((f) => f.rule === 'kill-switch'));

      // What the gate needs, derived from the plan rather than re-guessed.
      const facts = scaffoldGateFacts(SPECS.jekyll, plan, emptyContext().manifestText);
      assert.deepEqual(facts, {
        laneId: 'content-factory',
        workflowPath: existingWorkflow,
        workflowExists: true,
        switchName: 'CONTENT_FACTORY_ENABLED',
        switchTaken: false,
        notExpressibleReasons: [],
      });

      // A repository with no manifest is where a FIRST lane gets written: the
      // files are still planned, and the absence is said out loud.
      const first = await planScaffold(
        SPECS.mkdocs,
        emptyContext({ manifestText: undefined }),
      );
      assert.equal(first.manifest, null);
      assert.ok(first.audit.some((f) => f.rule === 'manifest-absent'));
      assert.equal(first.files.length, 3);

      assert.deepEqual(snapshot(root), treeBefore, 'planScaffold wrote to disk');
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
});

/** Every file under `root`, with its bytes — the "nothing was written" check. */
function snapshot(root: string): Record<string, string> {
  const out: Record<string, string> = {};
  const walk = (dir: string): void => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else {
        out[path.relative(root, full)] = fs.readFileSync(full, 'utf8');
      }
    }
  };
  walk(root);
  return out;
}
