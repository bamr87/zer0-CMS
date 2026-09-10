// Regenerate the engines goldens. Run from the repository root:
//
//     node src/test/fixtures/golden/engines/generate.mjs
//
// WHAT THIS IS. `@bamr87/fleet-engines` is an exact-pinned devDependency
// (a deliberate standard deviation — see CLAUDE.md), and every number the Fleet
// tab shows comes out of it: workflow facts, the audit rulebook, the grade.
// These goldens are that output, frozen, over the verbatim sister-repo workflow
// files under `src/test/fixtures/fleet/workflows/`. A `chore(deps)` bump of the
// package changes them, and the point is that a person reads the diff — an
// archetype that silently reclassified, a rule that stopped firing, a grade that
// moved — instead of discovering it on a dashboard three weeks later.
//
// THE RULES.
//   * NEVER hand-edit a golden. Re-run this file.
//   * NEVER edit a fixture workflow to make a golden nicer. Re-copy it from its
//     origin (see `src/test/fixtures/fleet/FIXTURE-SOURCES.md`) and re-run.
//   * `ENGINES_VERSION` beside the goldens records which build produced them.
//     `engines.test.ts` reads it and SKIPS with a note when the installed
//     version differs, because a stale golden failing is noise, not a signal.
//
// This is the same contract as `src/test/fixtures/golden/generate.py`, which
// freezes the Python publishing lane's bytes for the same reason.

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  AUDIT_RULES,
  auditRepo,
  extractFacts,
  toFleetManifestYaml,
  yamlDump,
} from '@bamr87/fleet-engines';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '../../../../..');
const FLEET = path.join(REPO, 'src/test/fixtures/fleet');
const WORKFLOWS = path.join(FLEET, 'workflows');
const ENGINES_PKG = path.join(REPO, 'node_modules/@bamr87/fleet-engines/package.json');

const enginesVersion = JSON.parse(fs.readFileSync(ENGINES_PKG, 'utf8')).version;

/** Repository directories under `workflows/`, and their files, both sorted. */
function fixtureWorkflows() {
  const out = [];
  for (const repo of fs.readdirSync(WORKFLOWS).sort()) {
    const dir = path.join(WORKFLOWS, repo);
    if (!fs.statSync(dir).isDirectory()) {
      continue;
    }
    for (const file of fs.readdirSync(dir).sort()) {
      if (!file.endsWith('.yml')) {
        continue;
      }
      out.push({
        repo,
        file,
        // The path the engines are given is the one a real repository would
        // hand them, because `classifyDashType` and `classifyArchetype` both
        // read it. `claude-run.action.yml` is a composite action rather than a
        // workflow, and is fed through the same door on purpose: the engines
        // must not fall over on it.
        enginePath: `.github/workflows/${file}`,
        text: fs.readFileSync(path.join(dir, file), 'utf8'),
      });
    }
  }
  return out;
}

const workflows = fixtureWorkflows();

// --- facts ------------------------------------------------------------------
// Keyed `<repo>/<file>` so two repositories may both have `issue-autopilot.yml`.
const facts = {};
for (const wf of workflows) {
  facts[`${wf.repo}/${wf.file}`] = extractFacts(wf.enginePath, wf.text);
}

// --- audit ------------------------------------------------------------------
// One `auditRepo` per repository — the repo-scoped rules (the standard trio, the
// disabled-workflow rule) only mean anything over a whole repository's set.
const byRepo = {};
for (const wf of workflows) {
  (byRepo[wf.repo] ??= []).push(facts[`${wf.repo}/${wf.file}`]);
}
const audit = {};
for (const repo of Object.keys(byRepo).sort()) {
  audit[repo] = auditRepo(byRepo[repo]);
}

// --- the rulebook -----------------------------------------------------------
// Frozen so a rule added, removed or re-worded upstream shows up as a diff here
// before it shows up as a changed grade. GitFactory's vendored copy of this
// rulebook carries a sixteenth rule (`vendored-runner`, ADR-037) that the
// published package does not — which is why the count is pinned in the test.
const rulebook = AUDIT_RULES.map((rule) => ({
  id: rule.id,
  severity: rule.severity,
  title: rule.title,
}));

// --- the emitter ------------------------------------------------------------
// `toFleetManifestYaml` is what a generated lane would be written with (PR4), and
// `yamlDump` is the deterministic block-style emitter under it. Both are frozen
// over a fixed input so a formatting change upstream cannot quietly rewrite a
// person's committed manifest.
const emitterLanes = [
  {
    id: 'content-factory',
    kind: 'content',
    harness: 'claude-cli',
    implementation: '.github/workflows/content-factory.yml',
    description: 'content-factory',
    triggers: [{ kind: 'schedule', cron: '0 9 * * *' }, { kind: 'dispatch' }],
    switch: 'CONTENT_FACTORY_ENABLED',
    uses_tokens: ['ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'FLEET_TOKEN'],
    guardrails: { never_merges: true, opens_pull_requests: true },
  },
  {
    id: 'claude',
    kind: 'mention',
    harness: 'claude-code-action',
    implementation: '.github/workflows/claude.yml',
    description: 'Claude',
    triggers: [{ kind: 'event', events: ['issue_comment', 'issues'] }],
    switch: null,
    uses_tokens: ['CLAUDE_CODE_OAUTH_TOKEN'],
    guardrails: { never_merges: true, writable_paths: ['pages/', '_data/'] },
  },
];
const manifestYaml = toFleetManifestYaml(emitterLanes, {
  repo: 'bamr87/zer0-CMS',
  summary: 'A frozen two-lane manifest — the emitter golden, not a real fleet.',
  provenance: 'declared',
  header: ['GENERATED for src/test/fixtures/golden/engines. Not a real manifest.'],
});
const dumped = yamlDump({
  scalar: 'plain',
  needsQuotes: 'yes: really',
  empty: '',
  nested: { list: ['a', 'b'], flag: true, count: 3, nothing: null },
});

// --- write ------------------------------------------------------------------
function writeJson(name, value) {
  fs.writeFileSync(path.join(HERE, name), `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

writeJson('facts.json', facts);
writeJson('audit.json', audit);
writeJson('rulebook.json', rulebook);
fs.writeFileSync(path.join(HERE, 'manifest.yml'), manifestYaml, 'utf8');
fs.writeFileSync(path.join(HERE, 'yamldump.yml'), dumped, 'utf8');
fs.writeFileSync(path.join(HERE, 'ENGINES_VERSION'), `${enginesVersion}\n`, 'utf8');

console.log(
  `engines goldens regenerated at @bamr87/fleet-engines ${enginesVersion}: ` +
    `${workflows.length} workflows, ${Object.keys(audit).length} repositories, ` +
    `${rulebook.length} audit rules`,
);
