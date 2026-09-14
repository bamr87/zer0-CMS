// Regenerate the lane-generation goldens. Run from the repository root:
//
//     npx tsc -p . --outDir out && node src/test/fixtures/golden/lanes/generate.mjs
//
// WHAT THIS IS. Everything this console would write when somebody describes a
// lane — the workflow, the agent role, the skill stub, the manifest entry, and
// the manifest after the entry is appended — frozen for three real shapes: a
// Ruby/Jekyll content lane, a Python/MkDocs docs audit, and a Node/Wiki.js
// pull-request reviewer, plus the gate+claude-run form of the first.
//
// THE RULES.
//   * NEVER hand-edit a golden. Re-run this file and read the diff.
//   * NEVER edit `media/templates/ai-lane.template.yml` to make a golden nicer.
//     It is a verbatim copy of the hub's; re-copy it (see
//     `media/templates/README.md`) and re-run.
//   * `specs.json` is generated too, and the test renders FROM it — so a spec
//     that changed and a golden that did not is a failing test, not a silent
//     drift between what the generator drew and what the suite checks.
//   * `LANES_VERSION` records which ai-runner kit produced these bytes.
//     `lanes.test.ts` reads it and skips the golden comparisons with a note when
//     the vendored VERSION has moved, because a stale golden failing is noise.
//
// This is the same contract as `golden/engines/generate.mjs` and
// `golden/generate.py`: a generated artefact, beside its generator, with the
// version that made it.

import * as fs from 'node:fs';
import { createRequire } from 'node:module';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '../../../../..');
const OUT = path.join(REPO, 'out');

const {
  renderAiLaneCaller,
  renderGateAndClaudeRun,
  renderAgentFile,
  renderSkillStub,
  renderManifestLane,
} = require(path.join(OUT, 'core/harness/render.js'));
const { appendLaneToManifest } = require(path.join(OUT, 'core/harness/manifestWrite.js'));
const { parseKitVersion } = require(path.join(OUT, 'core/harness/lanes.js'));

const TEMPLATE = fs.readFileSync(path.join(REPO, 'media/templates/ai-lane.template.yml'), 'utf8');
const AGENT_TEMPLATE = fs.readFileSync(path.join(REPO, 'media/templates/agent.template.md'), 'utf8');
const VERSION_FILE = fs.readFileSync(path.join(REPO, 'media/templates/ai-runner.VERSION'), 'utf8');
const KIT_VERSION = parseKitVersion(VERSION_FILE);

/** Every field of a LaneSpec, so a new one shows up here as `undefined`. */
function spec(overrides) {
  return {
    id: 'lane',
    kind: 'other',
    verb: 'create',
    description: 'A lane.',
    agent: 'agent',
    skill: null,
    projectName: 'the site',
    platform: 'jekyll',
    switch: 'LANE_ENABLED',
    dispatchBypassesSwitch: true,
    cron: '17 6 * * 1',
    events: [],
    prompt: 'Do one thing. Write the PR URL to pr-result.txt. Never merge.',
    system: '',
    tools: ['Bash', 'Read', 'Write', 'Edit', 'Grep', 'Glob'],
    mcp: null,
    model: null,
    maxTurns: null,
    setup: { ruby: null, node: null, python: null },
    preRun: null,
    postRun: null,
    resultFile: 'pr-result.txt',
    artifactPath: null,
    timeoutMinutes: 30,
    cancelInProgress: false,
    continueOnError: false,
    permissions: { contents: 'write', 'pull-requests': 'write' },
    matrix: null,
    crossRepoCheckout: false,
    prHeadCheckout: false,
    modelPasses: 1,
    labels: [],
    branchPattern: null,
    kitVersion: KIT_VERSION,
    ...overrides,
  };
}

// ── 1. Ruby / Jekyll: the daily content lane ───────────────────────────────
// Modelled on lifehacker.dev's own content-factory, with its matrix removed —
// this is the shape a person gets when they say "draft one post a day".
const jekyll = spec({
  id: 'content-factory',
  kind: 'content',
  verb: 'create',
  description:
    'Produce ONE on-voice, tested piece from the backlog, verify it with the repository harness, and open ONE pull request. Never merges.',
  agent: 'grow-lifehacker',
  skill: 'grow-lifehacker',
  projectName: 'lifehacker.dev',
  platform: 'jekyll',
  switch: 'CONTENT_FACTORY_ENABLED',
  cron: '17 9 * * *',
  prompt:
    "Use the grow-lifehacker skill to produce exactly ONE piece for lifehacker.dev. Pick the highest-priority backlog item whose kind matches the assignment; if every candidate duplicates an open pull request, propose a fresh on-voice idea, add it to the backlog, and draft that — never silently no-op. Verify with the repository's own harness before opening anything. Open ONE pull request on a branch, label it 'auto:content', write the resulting PR URL to pr-result.txt, flip the backlog item to done, and STOP. Never merge.",
  system:
    'You are the lifehacker.dev content factory. Produce one on-voice, tested piece and open one pull request. Never merge.',
  setup: { ruby: '3.3', node: null, python: null },
  timeoutMinutes: 20,
  labels: ['auto:content'],
  branchPattern: 'autopilot/',
});

// ── 2. Python / MkDocs: the weekly docs audit ──────────────────────────────
const mkdocs = spec({
  id: 'docs-audit',
  kind: 'maintenance',
  verb: 'audit',
  description:
    'Read the built documentation for pages that no longer match the code, fix the smallest honest set of them, and open ONE pull request. Never merges.',
  agent: 'docs-auditor',
  skill: 'docs-audit',
  projectName: 'the handbook',
  platform: 'mkdocs',
  switch: 'DOCS_AUDIT_ENABLED',
  cron: '41 6 * * 1',
  prompt:
    'Audit the documentation under docs/ against the code it describes. Fix only what you can verify is wrong — a page that is merely old is not a finding. Run `mkdocs build --strict` before opening anything, open ONE pull request, write its URL to pr-result.txt, and STOP. Never merge.',
  system: 'You are the documentation auditor for the handbook. Verify before you claim. Never merge.',
  tools: ['Bash', 'Read', 'Edit', 'Grep', 'Glob'],
  setup: { ruby: null, node: null, python: '3.12' },
  preRun: 'pip install -r requirements.txt\nmkdocs build --strict',
  timeoutMinutes: 25,
});

// ── 3. Node / Wiki.js: the pull-request reviewer ───────────────────────────
// Event-driven, cancellable (a superseded review is wasted work), and allowed
// to stay green when the model call fails — a reviewer that reddens a content
// pull request is a reviewer people turn off.
const wikijs = spec({
  id: 'content-review',
  kind: 'review',
  verb: 'review',
  description:
    'Read the changed pages on a pull request, apply small improvements in place, and post judgement calls as comments. Never merges.',
  agent: 'content-reviewer',
  skill: 'content-reviewer',
  projectName: 'the wiki',
  platform: 'wikijs',
  switch: 'CONTENT_REVIEW_ENABLED',
  cron: null,
  events: ['pull_request'],
  prompt:
    'Review the changed pages on this pull request. Apply small improvements to the changed content files ONLY; if it already reads clean, make no commit and post a one-line comment instead. This is a single editorial pass, not an iterative polish. Post larger follow-ups as comments. Write what you did to review-result.txt. Never touch infrastructure. Never merge.',
  system: 'You are the content reviewer for the wiki. Improve the changed content only; never merge.',
  tools: ['Bash(gh pr comment:*)', 'Bash(git:*)', 'Read', 'Edit', 'Write(pages/**)', 'Grep', 'Glob'],
  setup: { ruby: null, node: '20', python: null },
  postRun: 'node scripts/verify-links.mjs',
  resultFile: 'review-result.txt',
  timeoutMinutes: 15,
  cancelInProgress: true,
  continueOnError: true,
});

// ── 4. The same content lane, fanned out per collection ────────────────────
// A static matrix is what pushes a lane off the shared caller and onto the
// hand-written gate: the reusable lane's own answer to fan-out is "call it once
// per item", and five near-identical caller jobs is a worse file than one matrix.
// The prompt names `${{ matrix.item }}` on purpose: five legs given one
// instruction are five agents racing each other, which `preflightLaneSpec`
// warns about and this golden therefore does not demonstrate.
const matrixed = spec({
  ...jekyll,
  matrix: { static: ['hack', 'tool', 'post', 'doc', 'wire'] },
  prompt:
    "Use the grow-lifehacker skill to produce exactly ONE ${{ matrix.item }} for lifehacker.dev. Pick the highest-priority backlog item whose kind IS '${{ matrix.item }}' — never borrow an item meant for another collection. If every candidate duplicates an open pull request, propose a fresh on-voice ${{ matrix.item }} idea, add it to the backlog, and draft that — never silently no-op, never cross collections. Verify with the repository's own harness before opening anything. Open ONE pull request, label it 'auto:content' and 'collection/${{ matrix.item }}', write the resulting PR URL to pr-result.txt, flip the backlog item to done, and STOP. Never merge.",
});

// ── The manifest this console appends to ───────────────────────────────────
// Written here rather than committed by hand so that it is generated like every
// other golden: comments, a hand-written summary, a `provenance:` and a
// `tokens:` block, which are exactly the things line surgery has to preserve.
const MANIFEST_BEFORE = `# fleet.manifest.yml — this repository's AI fleet, in the
# shared 'fleet/v1' vocabulary. See docs/FLEET-SPEC.md in
# bamr87/wtd. Generated by \`wtd fleet adopt\`; edit freely —
# hand-written values survive regeneration of other fields.
spec_version: fleet/v1
repo: bamr87/example.dev
provenance: derived
summary: Two lanes and a token contract, both default-OFF behind their own *_ENABLED
  repo variable.
lanes:
- id: agent-review
  kind: review
  harness: claude-cli
  implementation: .github/workflows/agent-review.yml
  description: agent-review
  triggers:
  - kind: schedule
    cron: 17 5 1 * *
  - kind: dispatch
  switch: AGENT_REVIEW_ENABLED
  uses_tokens:
  - CLAUDE_CODE_OAUTH_TOKEN
  guardrails:
    never_merges: true
- id: triage
  kind: maintenance
  harness: none
  implementation: .github/workflows/triage.yml
  description: triage
  triggers:
  - kind: dispatch
  switch: null
  uses_tokens: []
  guardrails:
    never_merges: true

# The token contract. Every name here is a repository secret a human created.
tokens:
- name: CLAUDE_CODE_OAUTH_TOKEN
  scope: fleet
  required: true
  purpose: "Preferred Claude auth (house convention: OAuth first)."
  used_by:
  - agent-review
`;

const files = new Map();

files.set('specs.json', `${JSON.stringify({ jekyll, mkdocs, wikijs, matrixed }, null, 2)}\n`);

files.set('caller-jekyll-ruby.yml', renderAiLaneCaller(jekyll, TEMPLATE));
files.set('caller-mkdocs-python.yml', renderAiLaneCaller(mkdocs, TEMPLATE));
files.set('caller-wikijs-node.yml', renderAiLaneCaller(wikijs, TEMPLATE));
files.set('gate-claude-run-jekyll.yml', renderGateAndClaudeRun(matrixed));

files.set('agent-jekyll.md', renderAgentFile(jekyll, AGENT_TEMPLATE));
files.set('agent-wikijs.md', renderAgentFile(wikijs, AGENT_TEMPLATE));
files.set('skill-jekyll.md', renderSkillStub(jekyll));

files.set(
  'manifest-lanes.yml',
  [jekyll, mkdocs, wikijs].map((one) => renderManifestLane(one)).join(''),
);
files.set('manifest-before.yml', MANIFEST_BEFORE);

const appended = appendLaneToManifest(MANIFEST_BEFORE, renderManifestLane(jekyll));
if (!('text' in appended)) {
  throw new Error(`the manifest append refused: ${appended.refused}`);
}
files.set('manifest-after.yml', appended.text);

files.set(
  'LANES_VERSION',
  [
    '# Which ai-runner kit produced the goldens in this directory.',
    '# Read by lanes.test.ts, which skips the golden comparisons with a note',
    '# when media/templates/ai-runner.VERSION has moved past this.',
    `kit: ai-runner v${KIT_VERSION}`,
    '',
  ].join('\n'),
);

for (const [name, contents] of files) {
  fs.writeFileSync(path.join(HERE, name), contents);
}

console.log(`wrote ${files.size} lane goldens at ai-runner v${KIT_VERSION}`);
