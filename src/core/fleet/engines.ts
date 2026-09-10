/**
 * The engines seam — the ONLY file in this repository that imports
 * `@bamr87/fleet-engines`.
 *
 * The package is the hub's copy of the fleet's pure engines (`templates/fleet-engines`):
 * workflow facts, the audit rulebook, run metrics, the harness scorecard, the hub
 * reader, the roster helpers and the manifest emitter. GitFactory consumes the same
 * package. Consuming it rather than re-porting it is decision D14 — a build-time
 * dependency, bundled into `dist/extension.js` alone, never a runtime one.
 *
 * Two rules make that safe, and both are enforced from outside this file:
 *
 *   1. **This file is never re-exported through `src/core/index.ts`.** The package
 *      exports `FleetLane`, `FleetManifest`, `parseFleetManifest`, `LANE_KINDS` and
 *      `RosterEntry`, every one of which this repository already declares with a
 *      different shape. `export *` on a duplicate name silently makes the barrel
 *      ambiguous, and the barrel is what `src/mcp/` imports through — so a star
 *      export here would also drag the package into `dist/mcp-server.js`, where
 *      `external: []` and an empty bare-import allow-list exist to keep it out.
 *      Everything the console needs from a package value crosses the boundary
 *      through `./adapters.ts`, which imports types only.
 *
 *   2. **Every colliding name is re-exported under an alias.** `Engine`-prefixed
 *      for a shape this repository also declares; verbatim for a name that is the
 *      package's alone. That is what lets a reader of `src/commands/fleet.ts` tell
 *      at a glance which `FleetLane` is on screen.
 *
 * eslint forbids importing this module from `src/mcp/**`, and `engines.test.ts`
 * greps `src/` to prove no second importer of the package has appeared.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

// ---------------------------------------------------------------------------
// Values — the engines proper
// ---------------------------------------------------------------------------

export {
  extractFacts,
  parseWorkflow,
  buildFleet,
  attachLanes,
  AUDIT_RULES,
  auditWorkflow,
  auditRepo,
  gradeFor,
  computeWorkflowMetrics,
  assignFlags,
  rollup,
  rollupByType,
  harnessHealth,
  readHub,
  compareHealth,
  HUB_PATHS,
  DEFAULT_HUB,
  parseGitmodules,
  parseRosterText,
  mergeRoster,
  toFleetManifestYaml,
  yamlDump as engineYamlDump,
  parseRepo,
  GithubError,
} from '@bamr87/fleet-engines';

/**
 * The three names that collide head-on with `src/core/fleet/manifest.ts` and
 * `shared/types.ts`. The package's `parseFleetManifest` is the one this console
 * checks its own parser against — it is deliberately NOT the one the console
 * reads a manifest with (decision D-A: our reader refuses a foreign
 * `spec_version` and keeps a tristate guardrail, the package's defaults an
 * absent `never_merges` to `true` and answers an unreadable file with an empty
 * manifest whose `skipped` is `0`).
 */
export {
  parseFleetManifest as engineParseFleetManifest,
  laneForPath as engineLaneForPath,
  LANE_KINDS as ENGINE_LANE_KINDS,
} from '@bamr87/fleet-engines';

// ---------------------------------------------------------------------------
// Types — erased at build time, so an `import type` of these is barrel-safe
// ---------------------------------------------------------------------------

export type {
  FleetLane as EngineFleetLane,
  FleetManifest as EngineFleetManifest,
  GithubClient as EngineGithubClient,
  WorkflowFacts,
  RepoAudit,
  AuditFinding,
  FactoryRun,
  RepoWorkflow,
  RepoVariable,
  HubSnapshot,
  RosterEntry as EngineRosterEntry,
} from '@bamr87/fleet-engines';

/**
 * Three more package types, split out because they are not on the alias list in
 * the plan: `inspect.ts` needs them to type the engine functions its caller
 * injects, and a type is the only thing that may cross into a barrel-exported
 * module (`import type` is erased before esbuild resolves anything). None of
 * them collides with a name this repository declares, so they keep their own.
 */
export type { ImportedWorkflow, Fleet, FleetEdge, RepoRef } from '@bamr87/fleet-engines';

// ---------------------------------------------------------------------------
// Which engines build this is
// ---------------------------------------------------------------------------

/**
 * Compiled in by esbuild (`define.__ENGINES_VERSION__`, read from the installed
 * package's `package.json` at build time). Declared rather than imported because
 * the bundles are single files with no `package.json` beside them at runtime.
 */
declare const __ENGINES_VERSION__: string;

/**
 * The installed package version, read from disk — the fallback for the plain
 * Mocha fast loop (`tsc -p . --outDir out` + `mocha out/test/*.js`), which never
 * runs esbuild and therefore has no `define`.
 *
 * Walks up from this module's directory looking for
 * `node_modules/@bamr87/fleet-engines/package.json`, which is where it sits for
 * both `out/core/fleet/engines.js` and `src/core/fleet/engines.ts`. Returns
 * `undefined` rather than throwing: a version string is telemetry, and telemetry
 * must never be the reason a test run dies.
 */
function readVersionAt(file: string): string | undefined {
  let raw: unknown;
  try {
    raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    // Not this directory. A missing file is the normal answer for every
    // directory but one, so the walk continues rather than reporting.
    return undefined;
  }
  if (typeof raw !== 'object' || raw === null || !('version' in raw)) {
    return undefined;
  }
  const version = (raw as { version: unknown }).version;
  return typeof version === 'string' && version !== '' ? version : undefined;
}

function installedEnginesVersion(): string | undefined {
  let dir = __dirname;
  for (let depth = 0; depth < 12; depth += 1) {
    const found = readVersionAt(
      path.join(dir, 'node_modules', '@bamr87', 'fleet-engines', 'package.json'),
    );
    if (found !== undefined) {
      return found;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return undefined;
    }
    dir = parent;
  }
  return undefined;
}

function resolveEnginesVersion(): string {
  if (typeof __ENGINES_VERSION__ === 'string' && __ENGINES_VERSION__ !== '') {
    return __ENGINES_VERSION__;
  }
  return installedEnginesVersion() ?? '0.0.0-dev';
}

/**
 * Which build of the engines produced the numbers on screen and in the goldens
 * under `src/test/fixtures/golden/engines/`.
 *
 * Resolution order, and each answer is honest about where it came from:
 *   1. the esbuild `define` (both `dist/extension.js` and `dist/mcp-server.js`
 *      carry it, though only the extension bundle carries the package itself);
 *   2. the installed `node_modules/@bamr87/fleet-engines/package.json` — the
 *      fast loop's path;
 *   3. `'0.0.0-dev'`, which is not a published version and cannot be mistaken
 *      for one.
 */
export const ENGINES_VERSION: string = resolveEnginesVersion();
