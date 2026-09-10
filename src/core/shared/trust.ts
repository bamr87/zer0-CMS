/**
 * The execution gate — Workspace Trust and the workspace boundary, as values.
 *
 * Five paths in this extension can start a process: the content engine, the
 * front-matter normalizer, a `placeholders[].script`, the verify command and
 * the AI agent (`ExecVector`). Decision D13 says Workspace Trust is the outer
 * gate on all five, and that the check lives *inside* the function that
 * spawns — a `when` clause is a hint to the menu system, not an enforcement
 * point, and `capabilities.untrustedWorkspaces` only drops the
 * *workspace-scoped* value of a restricted setting, so a `true` sitting in
 * somebody's user settings still arrives in a folder they just cloned.
 *
 * This module is the single place that answers "may this run?", and it answers
 * the way `evaluateGates` (`../governance/approval.ts`) and
 * `evaluateFleetGates` (`../fleet/fleet.ts`) do:
 *
 *   - **A blocker is a value, never an exception.** `undefined` means allowed.
 *     Every caller here is a spawn path whose stated contract is that it
 *     resolves a result rather than rejecting, so a thrown refusal would be a
 *     worse outcome than the thing it refused.
 *   - **Nothing reads the filesystem.** Every input is passed in, which is what
 *     lets the same function run in the extension host, in the MCP process and
 *     in a plain `node` test.
 *   - **The order is fixed.** Trust is checked before the path, because "this
 *     folder is not trusted" is the fact the person has to act on first; the
 *     path is only interesting once running anything is on the table.
 *
 * There are exactly two refusals. `untrusted-workspace` is the outer gate.
 * `outside-workspace` is the one that holds *whichever layer supplied the
 * path*: a `zer0.json` arrives with the clone, so `cms.engineScript:
 * "../../../evil.py"` must be refused in a trusted workspace too. What the
 * layer changes is the **log line** — the output channel says whether the
 * command about to run came from a person's settings or from a file that came
 * with the repository.
 */

import * as path from 'node:path';

import type { ExecBlocker, ExecGateInput, ExecVector } from './types';

/** The five, in the order `ExecVector` declares them. For tests and menus. */
export const EXEC_VECTORS: readonly ExecVector[] = [
  'engine',
  'normalizer',
  'placeholder',
  'agent',
  'verify',
];

/** How each vector is named in a refusal a person reads. */
const VECTOR_NOUNS: Readonly<Record<ExecVector, string>> = {
  engine: 'the content engine',
  normalizer: 'the front-matter normalizer',
  placeholder: 'a placeholder script',
  agent: 'the AI agent',
  verify: 'the verify command',
};

/** How each layer is named. "A file in the repository is not a human." */
const LAYER_NOUNS: Readonly<Record<ExecGateInput['layer'], string>> = {
  settings: 'the VS Code settings layer',
  'zer0.json': 'the project file, which arrives with the repository',
  default: 'the built-in default',
};

/**
 * `<interpreter> <script> (from <layer>)` — the phrase both the refusal and
 * the "about to run" log line are built from, so a reader comparing the two
 * sees the same words.
 */
export function describeExecTarget(input: ExecGateInput): string {
  const interpreter = input.interpreter.trim() === '' ? '(no interpreter)' : input.interpreter.trim();
  const script = input.scriptPath.trim() === '' ? '(no script)' : input.scriptPath.trim();
  return `${interpreter} ${script} (from ${LAYER_NOUNS[input.layer]})`;
}

// ---------------------------------------------------------------------------
// The workspace boundary
// ---------------------------------------------------------------------------

/**
 * macOS firmlinks. `/tmp`, `/var` and `/etc` are the same directories as
 * `/private/tmp`, `/private/var` and `/private/etc`, and which spelling you get
 * depends on whether the path came from `os.tmpdir()`, from a `realpath`, or
 * from a user typing it. Comparing the two spellings as strings says a file is
 * outside a root that literally contains it, so both are folded to the short
 * form before the comparison. Only these three prefixes are folded: `/private`
 * is an ordinary directory name everywhere else.
 */
const FIRMLINKS: readonly string[] = ['/private/tmp', '/private/var', '/private/etc'];

/** `true` on the two platforms whose default filesystem is case-insensitive. */
function caseInsensitive(): boolean {
  return process.platform === 'darwin' || process.platform === 'win32';
}

/** One comparable spelling of an absolute path. Never touches the disk. */
function canonical(value: string): string {
  let out = path.resolve(value);
  if (process.platform === 'darwin') {
    for (const link of FIRMLINKS) {
      if (out === link || out.startsWith(`${link}/`)) {
        out = out.slice('/private'.length);
        break;
      }
    }
  }
  // A trailing separator would make `<root>/` and `<root>` different strings.
  if (out.length > 1 && out.endsWith(path.sep)) {
    out = out.slice(0, -1);
  }
  return caseInsensitive() ? out.toLowerCase() : out;
}

/**
 * Is `abs` the workspace root itself, or something underneath it?
 *
 * `abs` may be absolute or relative; a relative path is resolved **against the
 * root**, which is what makes `../../evil.sh` answer `false` rather than
 * accidentally landing somewhere plausible. The comparison is on path
 * boundaries, so `/site/pages-old` is not inside `/site/pages` — the same bug
 * `folderForFile` fixes on the content side.
 *
 * An empty root answers `false`: a folderless window has no inside.
 */
export function insideWorkspace(root: string, abs: string): boolean {
  if (root.trim() === '' || abs.trim() === '') {
    return false;
  }
  const base = canonical(root);
  // `path.resolve(root, abs)` keeps an absolute `abs` and anchors a relative
  // one, so both spellings of "outside" are normalised the same way.
  const target = canonical(path.resolve(root, abs));
  return target === base || target.startsWith(base.endsWith(path.sep) ? base : `${base}${path.sep}`);
}

// ---------------------------------------------------------------------------
// The gate
// ---------------------------------------------------------------------------

function untrustedWorkspace(input: ExecGateInput): ExecBlocker | undefined {
  if (input.trusted) {
    return undefined;
  }
  return {
    reason: 'untrusted-workspace',
    message:
      `${VECTOR_NOUNS[input.vector]} did not run: this workspace is not trusted. ` +
      `${describeExecTarget(input)} stays unexecuted until you trust this folder ` +
      '("Workspaces: Manage Workspace Trust").',
  };
}

function outsideWorkspace(input: ExecGateInput): ExecBlocker | undefined {
  if (insideWorkspace(input.workspaceRoot, input.scriptPath)) {
    return undefined;
  }
  const where = input.workspaceRoot.trim() === '' ? 'no workspace folder is open' : `outside ${input.workspaceRoot}`;
  return {
    reason: 'outside-workspace',
    message:
      `${VECTOR_NOUNS[input.vector]} did not run: ${describeExecTarget(input)} resolves ${where}. ` +
      'A path that leaves the workspace is refused whichever layer supplied it.',
  };
}

/**
 * The gate. `undefined` means allowed; anything else is why it was not, in
 * words a person can act on.
 *
 * Both checks apply to all five vectors. There is no mode parameter and no
 * per-vector exemption on purpose: the moment one vector gets to skip a check
 * the doc that says "every one refuses" stops being true, and this file is the
 * only place that sentence is enforced.
 */
export function evaluateExecGate(input: ExecGateInput): ExecBlocker | undefined {
  return untrustedWorkspace(input) ?? outsideWorkspace(input);
}
