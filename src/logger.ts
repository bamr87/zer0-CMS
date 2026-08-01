/**
 * The output channel, wearing the core's `LogSink` face.
 *
 * `src/core` never imports `vscode`, so it logs through the `LogSink`
 * interface and the shell supplies the implementation. This file is that
 * implementation: one `OutputChannel` named "zer0-CMS", four levels, and a
 * threshold read from `zer0Cms.logging.level` *at the moment each line is
 * written* — flipping the setting takes effect on the next line, not on the
 * next window.
 *
 * There is a module-level `log` that every shell file can import without
 * ceremony. It is a thin façade over a lazily created channel, so importing
 * this module has no side effects: nothing is created until the first line is
 * written or `log.show()` is called. That matters because `activate()` must be
 * cheap and because the unit tests import shell modules outside an extension
 * host.
 */

import * as vscode from 'vscode';

import type { LogLevel, LogSink } from './core';

/** The name shown in the Output panel's dropdown. */
export const CHANNEL_NAME = 'zer0-CMS';

/** Ordered by verbosity: a line is written when its rank <= the threshold. */
const RANK: Record<LogLevel, number> = { error: 0, warn: 1, info: 2, verbose: 3 };

const LEVELS: readonly LogLevel[] = ['error', 'warn', 'info', 'verbose'];

/** The `LogSink` the core expects, plus the two things a shell wants. */
export interface ExtensionLog extends LogSink, vscode.Disposable {
  /** Reveal the output channel. `preserveFocus` defaults to `true`. */
  show(preserveFocus?: boolean): void;
  /** The threshold currently in force, read fresh from settings. */
  level(): LogLevel;
}

/**
 * Read `zer0Cms.logging.level`. An unrecognised value degrades to `info`
 * rather than throwing: a typo in a setting must not silence the log that
 * would tell you about the typo.
 */
function configuredLevel(): LogLevel {
  const raw = vscode.workspace.getConfiguration('zer0Cms').get<string>('logging.level');
  return LEVELS.find((level) => level === raw) ?? 'info';
}

/** `2026-07-31T19:57:04.123Z` — sortable, unambiguous, timezone-free. */
function stamp(): string {
  return new Date().toISOString();
}

class OutputChannelLog implements ExtensionLog {
  private channel: vscode.OutputChannel | undefined;

  constructor(private readonly name: string) {}

  private write(level: LogLevel, message: string): void {
    if (RANK[level] > RANK[configuredLevel()]) {
      return;
    }
    if (this.channel === undefined) {
      this.channel = vscode.window.createOutputChannel(this.name);
    }
    // Multi-line payloads (a subprocess dump, a JSON preview) keep their shape
    // but every line carries the prefix, so a copy-paste out of the panel is
    // still greppable.
    const prefix = `[${stamp()}] [${level}] `;
    for (const line of message.split('\n')) {
      this.channel.appendLine(`${prefix}${line}`);
    }
  }

  info(message: string): void {
    this.write('info', message);
  }

  warn(message: string): void {
    this.write('warn', message);
  }

  error(message: string): void {
    this.write('error', message);
  }

  verbose(message: string): void {
    this.write('verbose', message);
  }

  level(): LogLevel {
    return configuredLevel();
  }

  show(preserveFocus = true): void {
    if (this.channel === undefined) {
      this.channel = vscode.window.createOutputChannel(this.name);
    }
    this.channel.show(preserveFocus);
  }

  dispose(): void {
    this.channel?.dispose();
    this.channel = undefined;
  }
}

/** A private channel. Used by tests; the extension uses the shared `log`. */
export function createLog(name: string = CHANNEL_NAME): ExtensionLog {
  return new OutputChannelLog(name);
}

let shared: ExtensionLog | undefined;

function instance(): ExtensionLog {
  if (shared === undefined) {
    shared = createLog();
  }
  return shared;
}

/**
 * The shared log. Import it anywhere in the shell:
 *
 * ```ts
 * import { log } from '../logger';
 * log.info('refreshed');
 * ```
 *
 * A façade rather than the object itself so that importing this module never
 * creates an `OutputChannel` — the channel appears on the first line written.
 */
export const log: ExtensionLog = {
  info: (message) => instance().info(message),
  warn: (message) => instance().warn(message),
  error: (message) => instance().error(message),
  verbose: (message) => instance().verbose(message),
  level: () => instance().level(),
  show: (preserveFocus) => instance().show(preserveFocus),
  dispose: () => {
    shared?.dispose();
    shared = undefined;
  },
};

/**
 * Format an unknown thrown value for a log line or a notification. Every
 * `catch` in the shell goes through this so the message is the same in the
 * output channel and in the toast.
 */
export function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return typeof error === 'string' ? error : JSON.stringify(error);
}
