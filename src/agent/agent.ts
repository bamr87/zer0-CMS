/**
 * `CmsAgent` — the optional Claude Agent SDK runner, and the only file in the
 * extension that knows the SDK exists.
 *
 * Three properties make this layer safe to ship in a tool that also holds a
 * publish gate:
 *
 *  1. **It is off unless asked for.** `zer0Cms.agent.enabled` defaults to
 *     `false`, and `run()` returns before it touches the module loader when the
 *     flag is off. There is no import, no `require` cache entry, no cost.
 *  2. **It is not a dependency.** `@anthropic-ai/claude-agent-sdk` is an
 *     `optionalDependencies` entry marked `external` in the esbuild bundle, and
 *     it is reached through `new Function("m", "return import(m)")` — esbuild
 *     does not rewrite `new Function` bodies, so the specifier survives
 *     bundling and an absent package is a caught rejection rather than a
 *     resolution failure at load time.
 *  3. **Every mutating tool call is a human decision.** `READ_ONLY_TOOLS` is
 *     auto-allowed; everything else fails closed through
 *     `AgentReporter.requestApproval`, and a rejection returns
 *     `{ behavior: 'deny' }` so the model is told *why* and can adapt.
 *
 * ### What changed from the salvaged `src/zer0/agent.ts`
 *
 * | Defect | Fix |
 * |---|---|
 * | Passed **both** `allowedTools` and `canUseTool`, and the two lists disagreed about `TodoWrite`/`NotebookRead`. | `allowedTools` is not passed at all (decision D10). `canUseTool` is the single gate — an SDK-side allow rule would silently skip it. |
 * | `describeTool('Bash', …)` summarised every command as the literal string `"shell command"`. | The summary is the first 60 characters of the actual command, so the approval card says what is about to run. |
 * | `render()` ended in an empty `catch {}`. | Rendering failures are reported into the transcript with the `error` role. Nothing is swallowed. |
 * | The load-failure message told the user to `npm install` in `tools/cms-extension`, a path that does not exist in this repository. | The message names this extension's own installation root. |
 * | `any` throughout the public surface, and configuration read from an `itjCms.*` section that was never declared in the manifest. | No `any`; the SDK is narrowed from `unknown` at the boundary, and configuration arrives as a typed `Zer0Config['agent']` from the caller. |
 *
 * The reporter indirection is the whole coupling surface: this file has no
 * opinion about whether the transcript is a webview, an output channel or a
 * test double. `agentPanel.ts` supplies the webview implementation.
 */

import * as path from 'node:path';

import * as vscode from 'vscode';

import type { Zer0Config } from '../core';
import { describeError } from '../logger';
import { notifyInfo, notifyWarning } from '../uiState';

// ---------------------------------------------------------------------------
// The reporter contract
// ---------------------------------------------------------------------------

/** A mutating tool call, described well enough for a human to say yes or no. */
export interface ApprovalRequest {
  id: string;
  tool: string;
  /** One line: the file, or the command. Shown as the card's title. */
  summary: string;
  /** The diff, the file body, or the pretty-printed input. Rendered verbatim. */
  detail: string;
}

/** The five roles a transcript line can carry. */
export type AgentRole = 'assistant' | 'tool' | 'system' | 'result' | 'error';

/**
 * The UI sink. Implement it against any surface; `CmsAgent` never imports a
 * view. `requestApproval` may stay pending indefinitely — the SDK holds the
 * tool call open until it resolves — so an implementation that can be closed
 * must resolve `false` on teardown rather than leak the promise.
 */
export interface AgentReporter {
  append(role: AgentRole, text: string): void;
  clearTranscript(): void;
  setStatus(text: string, running: boolean): void;
  requestApproval(req: ApprovalRequest): Promise<boolean>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** The optional dependency. Never imported statically. */
export const SDK_MODULE = '@anthropic-ai/claude-agent-sdk';

/** Decision D10. Also the `zer0Cms.agent.model` default in the manifest. */
export const DEFAULT_MODEL = 'claude-opus-5';

/**
 * Tools that cannot change the workspace, auto-allowed without a prompt.
 * `TodoWrite` and `NotebookRead` are in the set deliberately: the first writes
 * only to the agent's own scratch list, the second reads. Everything absent
 * from this set — `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash`, every
 * MCP tool, every tool a future SDK version adds — fails closed.
 */
export const READ_ONLY_TOOLS: ReadonlySet<string> = new Set([
  'Read',
  'Grep',
  'Glob',
  'LS',
  'TodoWrite',
  'NotebookRead',
]);

/** Detail panes are capped so one `Write` cannot post a megabyte to a webview. */
const MAX_DETAIL = 4000;

/** Instructions appended to the `claude_code` preset system prompt. */
const SYSTEM_APPEND = [
  'You are running inside the zer0-CMS VS Code extension, over the user’s content repository.',
  'Content moves through a governed queue: draft → brand guard → human approval → publish → ledger.',
  'Write drafts and edit content; never approve or publish anything yourself, and never change',
  '`governance.publishAllow` or a draft’s `status` field.',
  'Do NOT create a branch, commit, push, or open a pull request — the user reviews every edit in the',
  'approval card and handles git themselves.',
].join(' ');

const DISABLED_MESSAGE =
  'The AI agent is off. Turn on "zer0Cms.agent.enabled" to use it — it is opt-in because it loads an optional dependency and can edit files.';

// ---------------------------------------------------------------------------
// The SDK boundary
// ---------------------------------------------------------------------------

/**
 * `import()` behind a `new Function`, so neither TypeScript's CommonJS emit nor
 * esbuild's bundler rewrites it into a static `require`. The SDK may ship ESM
 * only; this is the one form that loads it from a CJS extension bundle.
 */
const dynamicImport = new Function('m', 'return import(m)') as (
  specifier: string,
) => Promise<unknown>;

/** What a mutating tool wants to do. Values are whatever the tool declares. */
type ToolInput = Record<string, unknown>;

/** The SDK's `canUseTool` return contract. */
type PermissionResult =
  | { behavior: 'allow'; updatedInput: ToolInput }
  | { behavior: 'deny'; message: string };

/**
 * The subset of `Options` this extension sets. **The SDK's own allow-list
 * option is absent on purpose** — see decision D10 and the header table. Adding
 * it back would let a tool skip `canUseTool` entirely, which is exactly the bug
 * this rewrite removes, so it is not even declared here: a field that does not
 * exist on this interface cannot be added to the call below by accident.
 */
interface QueryOptions {
  cwd: string;
  model: string;
  maxTurns: number;
  permissionMode: string;
  abortController: AbortController;
  systemPrompt: { type: 'preset'; preset: 'claude_code'; append: string };
  canUseTool: (first: unknown, second: unknown) => Promise<PermissionResult>;
}

type QueryFn = (args: { prompt: string; options: QueryOptions }) => AsyncIterable<unknown>;

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : undefined;
}

function readString(input: Record<string, unknown> | undefined, key: string): string | undefined {
  const value = input?.[key];
  return typeof value === 'string' ? value : undefined;
}

/**
 * Pull `query` out of whatever the module loader handed back. An ESM namespace,
 * a CJS `module.exports`, and an interop object with everything under
 * `default` are all shapes the same package has shipped across versions, so all
 * three are checked before declaring a version mismatch.
 */
function readQuery(module: unknown): QueryFn | undefined {
  for (const candidate of [module, asRecord(module)?.['default']]) {
    const exported = asRecord(candidate)?.['query'];
    if (typeof exported === 'function') {
      return exported as QueryFn;
    }
  }
  return undefined;
}

/**
 * Where the user would run `npm install`. The bundle lives at
 * `<extensionRoot>/dist/extension.js`, and the manifest id is the authoritative
 * answer when the extension is properly installed; `__dirname` covers the
 * development host, where the id lookup can miss.
 */
function extensionRoot(): string {
  const installed = vscode.extensions.getExtension('bamr87.zer0-cms')?.extensionPath;
  return installed ?? path.resolve(__dirname, '..');
}

let idSeq = 0;

function nextApprovalId(): string {
  idSeq += 1;
  return `appr-${Date.now()}-${idSeq}`;
}

// ---------------------------------------------------------------------------
// CmsAgent
// ---------------------------------------------------------------------------

export class CmsAgent {
  private current: AbortController | undefined;

  /** `undefined` until the first load attempt — probing would mean importing. */
  private sdkPresent: boolean | undefined;

  constructor(
    private readonly repoRoot: string,
    private readonly reporter: AgentReporter,
    private readonly cfg: Zer0Config['agent'],
  ) {}

  get running(): boolean {
    return this.current !== undefined;
  }

  /**
   * `false` only once a load has actually failed. Optimistic before that: the
   * alternative is importing an optional dependency to find out, which is the
   * one thing a disabled agent must not do.
   */
  get available(): boolean {
    return this.sdkPresent !== false;
  }

  /** The model this agent will use, after the empty-setting fallback. */
  get model(): string {
    const configured = this.cfg.model.trim();
    return configured.length > 0 ? configured : DEFAULT_MODEL;
  }

  /**
   * Abort the run. The `for await` loop rejects with the abort reason, and
   * `run()` reports `Stopped.` as a normal system line rather than an error —
   * a user pressing stop has not encountered a failure.
   */
  stop(): void {
    this.current?.abort();
  }

  /** Run one pass. Resolves when the stream ends, is aborted, or fails. */
  async run(prompt: string): Promise<void> {
    const text = prompt.trim();
    if (text.length === 0) {
      this.reporter.append('system', 'Nothing to run — the prompt was empty.');
      return;
    }

    // Re-entrancy, checked before anything expensive: a second `query()` would
    // share this reporter and interleave two transcripts into one.
    if (this.current) {
      void notifyWarning('The AI agent is already running. Stop it before starting another run.');
      return;
    }

    // The gate, ahead of the module loader. With the agent off this method
    // performs no import at all — that is the whole point of the flag.
    if (!this.cfg.enabled) {
      this.reporter.append('system', DISABLED_MESSAGE);
      this.reporter.setStatus('disabled', false);
      const choice = await notifyInfo(DISABLED_MESSAGE, 'Open settings');
      if (choice === 'Open settings') {
        await vscode.commands.executeCommand('workbench.action.openSettings', 'zer0Cms.agent.enabled');
      }
      return;
    }

    const query = await this.loadQuery();
    if (!query) {
      return;
    }

    const abort = new AbortController();
    this.current = abort;
    this.reporter.clearTranscript();
    this.reporter.setStatus('running', true);
    this.reporter.append(
      'system',
      `Starting the agent · ${this.model} · ${this.cfg.permissionMode} · max ${this.cfg.maxTurns} turns`,
    );

    try {
      const response = query({
        prompt: text,
        options: {
          cwd: this.repoRoot,
          model: this.model,
          maxTurns: this.cfg.maxTurns,
          permissionMode: this.cfg.permissionMode,
          abortController: abort,
          systemPrompt: { type: 'preset', preset: 'claude_code', append: SYSTEM_APPEND },
          // Deliberately no SDK-side allow list here — a tool matched by one
          // never reaches the callback, and the callback is the gate. (D10)
          canUseTool: (first, second) => this.decide(first, second),
        },
      });

      for await (const message of response) {
        this.render(message);
      }
    } catch (error) {
      if (abort.signal.aborted) {
        this.reporter.append('system', 'Stopped.');
      } else {
        this.reporter.append('error', `Agent error: ${describeError(error)}`);
      }
    } finally {
      this.current = undefined;
      this.reporter.setStatus('idle', false);
    }
  }

  // -------------------------------------------------------------------------
  // Loading
  // -------------------------------------------------------------------------

  private async loadQuery(): Promise<QueryFn | undefined> {
    let module: unknown;
    try {
      module = await dynamicImport(SDK_MODULE);
    } catch (error) {
      this.sdkPresent = false;
      this.reporter.append(
        'error',
        `Could not load ${SDK_MODULE}. It is an optional dependency: run \`npm install\` in ` +
          `${extensionRoot()} and reload the window. (${describeError(error)})`,
      );
      return undefined;
    }

    const query = readQuery(module);
    if (!query) {
      this.sdkPresent = false;
      this.reporter.append(
        'error',
        `${SDK_MODULE} loaded but exports no query() function — the installed version is not ` +
          `compatible. Reinstall it in ${extensionRoot()}.`,
      );
      return undefined;
    }

    this.sdkPresent = true;
    return query;
  }

  // -------------------------------------------------------------------------
  // The gate
  // -------------------------------------------------------------------------

  /**
   * `canUseTool`. The SDK's documented shape is `(toolName, input, options)`,
   * but a request-object form has appeared in its reference docs, so both are
   * accepted: whichever arrives, the decision is the same and an unrecognised
   * shape lands on the approval path rather than the allow path.
   */
  private async decide(first: unknown, second: unknown): Promise<PermissionResult> {
    const { tool, input } = resolveToolCall(first, second);

    if (READ_ONLY_TOOLS.has(tool)) {
      return { behavior: 'allow', updatedInput: input };
    }

    const { summary, detail } = describeTool(tool, input, this.repoRoot);
    this.reporter.append('tool', `Waiting for approval · ${tool} · ${summary}`);

    const approved = await this.reporter.requestApproval({
      id: nextApprovalId(),
      tool,
      summary,
      detail,
    });

    if (!approved) {
      this.reporter.append('system', `Denied ${tool} · ${summary}`);
      return {
        behavior: 'deny',
        message: 'The user denied this action in the zer0-CMS agent panel. Do not retry it; ask for a different approach.',
      };
    }
    return { behavior: 'allow', updatedInput: input };
  }

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  /**
   * Project one SDK message onto the transcript. A malformed message is
   * reported, never swallowed: the salvaged version's empty `catch {}` made a
   * shape change look like an agent that had simply gone quiet.
   */
  private render(message: unknown): void {
    try {
      this.project(message);
    } catch (error) {
      this.reporter.append('error', `Could not render an agent message: ${describeError(error)}`);
    }
  }

  private project(message: unknown): void {
    const msg = asRecord(message);
    if (!msg) {
      return;
    }
    switch (msg['type']) {
      case 'system': {
        if (msg['subtype'] === 'init') {
          const session = readString(msg, 'session_id');
          this.reporter.append('system', session ? `Session ${session} ready.` : 'Session ready.');
        }
        return;
      }
      case 'assistant': {
        // Older builds nest the API message under `message`; newer ones put
        // `content` at the top level. Both are read.
        const envelope = asRecord(msg['message']) ?? msg;
        const content = envelope['content'];
        if (!Array.isArray(content)) {
          return;
        }
        for (const raw of content) {
          const block = asRecord(raw);
          if (!block) {
            continue;
          }
          if (block['type'] === 'text') {
            const body = readString(block, 'text')?.trim();
            if (body) {
              this.reporter.append('assistant', body);
            }
          } else if (block['type'] === 'tool_use') {
            const name = readString(block, 'name') ?? 'tool';
            this.reporter.append('tool', `→ ${name}(${briefInput(asRecord(block['input']))})`);
          }
        }
        return;
      }
      case 'result': {
        const cost = msg['total_cost_usd'];
        const turns = msg['num_turns'];
        const parts = [`done: ${readString(msg, 'subtype') ?? 'ok'}`];
        if (typeof turns === 'number') {
          parts.push(`${turns} turns`);
        }
        if (typeof cost === 'number') {
          parts.push(`$${cost.toFixed(4)}`);
        }
        this.reporter.append(msg['is_error'] === true ? 'error' : 'result', parts.join(' · '));
        return;
      }
      default:
        // `user` (tool results, already summarised by the approval card) and
        // `stream_event` (per-token deltas) are deliberately not rendered.
        return;
    }
  }
}

// ---------------------------------------------------------------------------
// Tool descriptions
// ---------------------------------------------------------------------------

/**
 * Normalise the two `canUseTool` argument shapes into `(tool, input)`. An
 * unrecognised first argument yields the empty tool name, which is not in
 * `READ_ONLY_TOOLS` and therefore still goes to the user.
 */
function resolveToolCall(first: unknown, second: unknown): { tool: string; input: ToolInput } {
  if (typeof first === 'string') {
    return { tool: first, input: asRecord(second) ?? {} };
  }
  const request = asRecord(first);
  const tool = readString(request, 'tool_name') ?? readString(request, 'toolName') ?? readString(request, 'name') ?? '';
  const input = asRecord(request?.['arguments']) ?? asRecord(request?.['input']) ?? {};
  return { tool, input };
}

function truncate(value: string, limit: number): string {
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

function clamp(value: string): string {
  return value.length > MAX_DETAIL ? `${value.slice(0, MAX_DETAIL)}\n… (truncated)` : value;
}

/** A workspace-relative path, for a card title that fits on one line. */
function relativeTo(root: string, value: string | undefined): string {
  if (!value) {
    return '(no path)';
  }
  return path.relative(root, path.isAbsolute(value) ? value : path.join(root, value)) || value;
}

/** The parenthesised hint after a tool name in the transcript. */
function briefInput(input: ToolInput | undefined): string {
  if (!input) {
    return '';
  }
  const file = readString(input, 'file_path');
  if (file) {
    return path.basename(file);
  }
  const command = readString(input, 'command');
  if (command) {
    return truncate(command, 60);
  }
  const pattern = readString(input, 'pattern');
  if (pattern) {
    return truncate(pattern, 40);
  }
  return Object.keys(input).slice(0, 3).join(', ');
}

/**
 * Build the approval card for a mutating tool call.
 *
 * The `Bash` branch is the one the salvaged file got wrong: it summarised every
 * shell call as the constant `"shell command"`, so `rm -rf` and `ls` produced
 * identical cards and the summary carried no information at all. The command
 * itself is the summary now.
 */
export function describeTool(
  tool: string,
  input: ToolInput,
  repoRoot: string,
): { summary: string; detail: string } {
  const rel = (key: string): string => relativeTo(repoRoot, readString(input, key));
  const dump = (): string => clamp(JSON.stringify(input, null, 2) ?? String(input));

  switch (tool) {
    case 'Edit': {
      const oldString = readString(input, 'old_string');
      const newString = readString(input, 'new_string');
      return {
        summary: rel('file_path'),
        detail: oldString !== undefined && newString !== undefined ? diffify(oldString, newString) : dump(),
      };
    }
    case 'MultiEdit': {
      const raw = input['edits'];
      const edits = Array.isArray(raw) ? raw : [];
      const detail = edits
        .map((entry, index) => {
          const edit = asRecord(entry);
          return `# edit ${index + 1}\n${diffify(readString(edit, 'old_string') ?? '', readString(edit, 'new_string') ?? '')}`;
        })
        .join('\n');
      return { summary: `${rel('file_path')} (${edits.length} edits)`, detail: clamp(detail) };
    }
    case 'Write': {
      const content = readString(input, 'content') ?? '';
      return { summary: `${rel('file_path')} (write ${content.length} chars)`, detail: clamp(content) };
    }
    case 'NotebookEdit': {
      return { summary: rel('notebook_path'), detail: dump() };
    }
    case 'Bash': {
      const command = readString(input, 'command')?.trim() ?? '';
      const description = readString(input, 'description')?.trim();
      if (command.length === 0) {
        return { summary: 'shell command (none given)', detail: dump() };
      }
      return {
        summary: truncate(command, 60),
        detail: description ? `# ${description}\n${clamp(command)}` : clamp(command),
      };
    }
    default:
      return { summary: tool || '(unnamed tool)', detail: dump() };
  }
}

/**
 * A line-prefixed before/after block. Not a real diff — computing one would
 * mean a diff algorithm for a card the user reads in two seconds — but the
 * `-`/`+` prefixes are what the panel colours, and the full old and new text is
 * present, which is the property that matters for consent.
 */
export function diffify(oldStr: string, newStr: string): string {
  const out: string[] = [];
  for (const line of oldStr.split('\n')) {
    out.push(`- ${line}`);
  }
  for (const line of newStr.split('\n')) {
    out.push(`+ ${line}`);
  }
  return clamp(out.join('\n'));
}
