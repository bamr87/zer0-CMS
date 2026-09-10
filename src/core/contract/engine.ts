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
 * Three contracts are load-bearing:
 *
 *   - **Nothing rejects.** Every runner resolves an `EngineResult`. A missing
 *     interpreter, a missing script, a script that exited 1, a run that timed
 *     out and a run the trust gate refused are all normal outcomes for a tool
 *     that runs against someone else's repository, and the caller wants to show
 *     the output either way. That is why the refusal below is `{ code: 1 }`
 *     with a note on stderr rather than a thrown error.
 *   - **Exit code 2 means "changes pending", not failure.** The normalizer
 *     uses it for "this dry-run found work to do". The zer0 layer documented
 *     that in a comment and then dropped the distinction on the floor;
 *     `changesPending` makes it a value.
 *   - **Every spawn passes `evaluateExecGate` first** (decision D13). This
 *     module and `../content/placeholders.ts` are the only two files in the
 *     repository allowed to import `node:child_process`; eslint fences the
 *     rest, which is why `runVerifyCommand` lives here rather than in
 *     `src/commands/audit.ts` where its one caller does.
 *
 * ### The log line is the point of `layer`
 *
 * `EngineConfig.layer` records **who named the interpreter and the scripts** —
 * a person's VS Code settings, the `zer0.json` that arrived with the clone, or
 * the built-in default. Every run logs it before it starts, so the output
 * channel shows what a freshly-cloned repository asked this extension to
 * execute on its behalf. It changes no decision here: a path that leaves the
 * workspace is refused whichever layer supplied it.
 */

import { execFile, type ExecFileException } from 'node:child_process';
import * as path from 'node:path';

import { describeExecTarget, evaluateExecGate } from '../shared/trust';
import { NOOP_LOG, type ExecVector, type LogSink, type Zer0Config } from '../shared/types';

/** Engine subcommands, as the Python lane defines them. */
export type EngineCommand = 'index' | 'analyze' | 'plan' | 'all' | 'status';

export const ENGINE_COMMANDS: readonly EngineCommand[] = [
  'index',
  'analyze',
  'plan',
  'all',
  'status',
];

/** Which configuration layer named a command this module is about to run. */
export type ExecLayer = 'settings' | 'zer0.json' | 'default';

/**
 * Everything a run needs, and nothing about the editor.
 *
 * `root` is the **working directory** the scripts run in — the repository
 * root, because that is what their relative paths resolve against. It is not
 * `Zer0Config.cms.root`, which locates the `.cms/` output directory; use
 * `engineConfigFor()` and the distinction is made for you.
 *
 * `trusted` is VS Code Workspace Trust for that root, passed in rather than
 * read, because this module never imports `vscode`. It has no default: a
 * caller that forgets it does not compile, which is the only way a gate whose
 * whole job is to be un-forgettable stays un-forgotten.
 */
export interface EngineConfig {
  root: string;
  python: string;
  engineScript: string;
  normalizerScript: string;
  contentDirs: string[];
  /** `vscode.workspace.isTrusted` for `root`, as the shell read it. */
  trusted: boolean;
  /** Which layer supplied `python` and the two script paths. */
  layer: ExecLayer;
}

export interface EngineResult {
  /** Process exit code; `1` stands in for "failed to start" and "refused". */
  code: number;
  stdout: string;
  stderr: string;
  /** Exit code 2: the normalizer found work to do. Not a failure. */
  changesPending: boolean;
}

/** The engine can emit a whole repository's worth of JSON on stdout. */
const MAX_BUFFER = 32 * 1024 * 1024;

/**
 * How long any of these may run before it is killed.
 *
 * There was no timeout at all: a `cms all` over a large site legitimately runs
 * for minutes, so the placeholder layer's five seconds is far too short, but
 * "no limit" means a script that waits on stdin holds a progress notification
 * open until the window is reloaded. Ten minutes is longer than any observed
 * real run and short enough that a hung one is noticed the same afternoon.
 */
export const ENGINE_TIMEOUT_MS = 10 * 60 * 1000;

/** Exit code the normalizer uses for "there are changes to apply". */
export const CHANGES_PENDING_CODE = 2;

/** Marker the normalizer prints for files it declined to touch. */
export const SKIP_MARKER = 'read-only/vendored';

/** The `cms.*` keys whose value is a command this module would execute. */
const EXECUTABLE_KEYS: readonly string[] = [
  'python',
  'pythonPath',
  'engineScript',
  'normalizerScript',
  'verifyCommand',
];

function namesAnExecutable(layer: Record<string, unknown> | undefined): boolean {
  if (layer === undefined) {
    return false;
  }
  return EXECUTABLE_KEYS.some((key) => {
    const value = layer[key];
    return typeof value === 'string' && value.trim() !== '';
  });
}

/**
 * Which layer named the interpreter or a script, given the two raw layers.
 *
 * Pure, and deliberately coarse: it answers "did a person write this, or did it
 * arrive with the repository", which is the only distinction the log line and
 * the settings-only gates care about. The shell passes its settings snapshot's
 * `cms` group and the `zer0.json` `cms` object; the MCP server passes
 * `undefined` for the first, because it has no settings layer.
 */
export function engineLayer(
  settingsCms: Record<string, unknown> | undefined,
  fileCms: Record<string, unknown> | undefined,
): ExecLayer {
  if (namesAnExecutable(settingsCms)) {
    return 'settings';
  }
  if (namesAnExecutable(fileCms)) {
    return 'zer0.json';
  }
  return 'default';
}

/**
 * Project the editor's resolved configuration onto the subprocess layer.
 *
 * `exec` is not optional and has no default. Trust is the outer gate on every
 * spawn in this extension (D13), and a parameter with a permissive default is
 * a gate that is off wherever somebody forgot it.
 */
export function engineConfigFor(
  cfg: Zer0Config,
  exec: { trusted: boolean; layer?: ExecLayer },
): EngineConfig {
  return {
    root: cfg.workspaceRoot,
    python: cfg.cms.python,
    engineScript: cfg.cms.engineScript,
    normalizerScript: cfg.cms.normalizerScript,
    contentDirs: [...cfg.cms.contentDirs],
    trusted: exec.trusted,
    layer: exec.layer ?? 'default',
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
  if (error.killed === true) {
    return `timed out after ${ENGINE_TIMEOUT_MS / 60000} minutes and was killed.\n`;
  }
  return `${error.message}\n`;
}

/**
 * Gate, log, spawn.
 *
 * `scriptPath` is what the gate judges — the first argument, resolved against
 * the working directory, falling back to the interpreter when there are no
 * arguments at all (`make`). A bare word like `run` or `make` resolves *inside*
 * the root and passes; the trust gate is what stands in front of that case, and
 * an absolute path pointing out of the tree is refused whoever named it.
 */
function run(
  cfg: EngineConfig,
  args: string[],
  vector: ExecVector,
  log: LogSink = NOOP_LOG,
  interpreter: string = cfg.python,
): Promise<EngineResult> {
  const gate = {
    trusted: cfg.trusted,
    workspaceRoot: cfg.root,
    scriptPath: args[0] ?? interpreter,
    interpreter,
    layer: cfg.layer,
    vector,
  } as const;

  // Logged before the gate answers, so the channel shows what was *attempted*
  // even when nothing ran. This is the line that names what a clone asked for.
  log.info(`${vector}: ${describeExecTarget(gate)} in ${cfg.root || '(no workspace)'}`);

  const blocker = evaluateExecGate(gate);
  if (blocker !== undefined) {
    log.warn(blocker.message);
    return Promise.resolve({
      code: 1,
      stdout: '',
      stderr: `${blocker.message}\n`,
      changesPending: false,
    });
  }

  return new Promise<EngineResult>((resolve) => {
    execFile(
      interpreter,
      args,
      { cwd: cfg.root, maxBuffer: MAX_BUFFER, timeout: ENGINE_TIMEOUT_MS, windowsHide: true },
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
export function runEngine(
  cfg: EngineConfig,
  command: EngineCommand,
  log?: LogSink,
): Promise<EngineResult> {
  return run(cfg, [nativePath(cfg.engineScript), command], 'engine', log);
}

/** Dry-run the mechanical front-matter normalizer. Writes nothing. */
export function runNormalizerPreview(cfg: EngineConfig, log?: LogSink): Promise<EngineResult> {
  return run(
    cfg,
    [nativePath(cfg.normalizerScript), ...cfg.contentDirs.map(nativePath)],
    'normalizer',
    log,
  );
}

/** Apply the mechanical front-matter normalizer. This one writes files. */
export function runNormalizerApply(cfg: EngineConfig, log?: LogSink): Promise<EngineResult> {
  return run(
    cfg,
    [nativePath(cfg.normalizerScript), ...cfg.contentDirs.map(nativePath), '--apply'],
    'normalizer',
    log,
  );
}

/**
 * Run the repository's own verification command — `zer0Cms.cms.verifyCommand`,
 * already split into an argv array by its caller.
 *
 * It is a sibling of the three above rather than a stranger in
 * `src/commands/`, for one reason: `node:child_process` is fenced by eslint to
 * this file and `../content/placeholders.ts`, so a command that spawns has to
 * come through here. `argv[0]` is the executable and the rest are its
 * arguments — **no shell**, so a repository path containing a quote is an
 * argument and never a second command. An empty argv is refused as a value,
 * like everything else in this module.
 */
export function runVerifyCommand(
  cfg: EngineConfig,
  argv: readonly string[],
  log?: LogSink,
): Promise<EngineResult> {
  const [interpreter, ...rest] = argv;
  if (interpreter === undefined || interpreter.trim() === '') {
    return Promise.resolve({
      code: 1,
      stdout: '',
      stderr: 'no verify command is configured (set "zer0Cms.cms.verifyCommand").\n',
      changesPending: false,
    });
  }
  return run(cfg, rest, 'verify', log, interpreter);
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
