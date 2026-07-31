/**
 * The content engine driver — a parameterised subprocess layer.
 *
 * The `.cms/` contract is produced by a Python engine that lives in the *user's*
 * repository, not in this extension: `scripts/cms/cms.py` builds the index and
 * `scripts/content/normalize-frontmatter.py` performs the mechanical fixes.
 * The zer0 layer this is descended from hardcoded both paths, hardcoded
 * `pages/` as the content directory, and read the interpreter out of
 * `vscode.workspace.getConfiguration()` — which made the whole thing unusable
 * from the MCP server and from a plain `node` test. Here everything arrives in
 * an `EngineConfig`, and the module imports nothing but Node.
 *
 * Two contracts are load-bearing:
 *
 *   - **Nothing rejects.** Every runner resolves an `EngineResult`. A missing
 *     interpreter, a missing script and a script that exited 1 are all normal
 *     outcomes for a tool that runs against someone else's repository, and the
 *     caller wants to show the output either way.
 *   - **Exit code 2 means "changes pending", not failure.** The normalizer
 *     uses it for "this dry-run found work to do". The zer0 layer documented
 *     that in a comment and then dropped the distinction on the floor;
 *     `changesPending` makes it a value.
 */

import { execFile, type ExecFileException } from 'node:child_process';
import * as path from 'node:path';

import type { Zer0Config } from '../shared/types';

/** Engine subcommands, as the Python lane defines them. */
export type EngineCommand = 'index' | 'analyze' | 'plan' | 'all' | 'status';

export const ENGINE_COMMANDS: readonly EngineCommand[] = [
  'index',
  'analyze',
  'plan',
  'all',
  'status',
];

/**
 * Everything a run needs, and nothing about the editor.
 *
 * `root` is the **working directory** the scripts run in — the repository
 * root, because that is what their relative paths resolve against. It is not
 * `Zer0Config.cms.root`, which locates the `.cms/` output directory; use
 * `engineConfigFor()` and the distinction is made for you.
 */
export interface EngineConfig {
  root: string;
  python: string;
  engineScript: string;
  normalizerScript: string;
  contentDirs: string[];
}

export interface EngineResult {
  /** Process exit code; `1` stands in for "failed to start". */
  code: number;
  stdout: string;
  stderr: string;
  /** Exit code 2: the normalizer found work to do. Not a failure. */
  changesPending: boolean;
}

/** The engine can emit a whole repository's worth of JSON on stdout. */
const MAX_BUFFER = 32 * 1024 * 1024;

/** Exit code the normalizer uses for "there are changes to apply". */
export const CHANGES_PENDING_CODE = 2;

/** Marker the normalizer prints for files it declined to touch. */
export const SKIP_MARKER = 'read-only/vendored';

/** Project the editor's resolved configuration onto the subprocess layer. */
export function engineConfigFor(cfg: Zer0Config): EngineConfig {
  return {
    root: cfg.workspaceRoot,
    python: cfg.cms.python,
    engineScript: cfg.cms.engineScript,
    normalizerScript: cfg.cms.normalizerScript,
    contentDirs: [...cfg.cms.contentDirs],
  };
}

/** Configured paths are written POSIX-style; the child needs native ones. */
function nativePath(value: string): string {
  return value.split('/').join(path.sep).split('\\').join(path.sep);
}

/**
 * `error.code` is a number for "the process ran and exited", and a string
 * (`ENOENT`, `EACCES`) for "the process never started". Only the first is an
 * exit code; the second is reported as 1 with the reason on stderr, so a
 * missing `python3` reads as a failed run rather than a silent zero.
 */
function exitCodeOf(error: ExecFileException | null): number {
  if (error === null) {
    return 0;
  }
  return typeof error.code === 'number' ? error.code : 1;
}

function startupNote(error: ExecFileException | null): string {
  if (error === null || typeof error.code === 'number') {
    return '';
  }
  return `${error.message}\n`;
}

function run(cfg: EngineConfig, args: string[]): Promise<EngineResult> {
  return new Promise<EngineResult>((resolve) => {
    execFile(
      cfg.python,
      args,
      { cwd: cfg.root, maxBuffer: MAX_BUFFER, windowsHide: true },
      (error, stdout, stderr) => {
        const code = exitCodeOf(error);
        resolve({
          code,
          stdout: stdout.toString(),
          stderr: startupNote(error) + stderr.toString(),
          changesPending: code === CHANGES_PENDING_CODE,
        });
      },
    );
  });
}

/** Run `<python> <engineScript> <command>` in the repository root. */
export function runEngine(cfg: EngineConfig, command: EngineCommand): Promise<EngineResult> {
  return run(cfg, [nativePath(cfg.engineScript), command]);
}

/** Dry-run the mechanical front-matter normalizer. Writes nothing. */
export function runNormalizerPreview(cfg: EngineConfig): Promise<EngineResult> {
  return run(cfg, [nativePath(cfg.normalizerScript), ...cfg.contentDirs.map(nativePath)]);
}

/** Apply the mechanical front-matter normalizer. This one writes files. */
export function runNormalizerApply(cfg: EngineConfig): Promise<EngineResult> {
  return run(cfg, [
    nativePath(cfg.normalizerScript),
    ...cfg.contentDirs.map(nativePath),
    '--apply',
  ]);
}

/**
 * Strip the normalizer's "SKIP … read-only/vendored" chorus.
 *
 * On a large site those lines outnumber the real ones ten to one, and a
 * reviewer scrolling past them is a reviewer who stops reading. The count is
 * kept so the surface can say *how many* were skipped instead of pretending
 * they did not exist.
 */
export function condenseNormalizerOutput(raw: string): { shown: string; skipped: number } {
  const lines = raw.split('\n');
  let skipped = 0;
  const kept: string[] = [];
  for (const line of lines) {
    if (line.includes(SKIP_MARKER)) {
      skipped += 1;
    } else {
      kept.push(line);
    }
  }
  return { shown: kept.join('\n').trim(), skipped };
}
