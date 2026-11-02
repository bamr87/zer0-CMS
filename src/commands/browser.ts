/**
 * The browser bridge's two commands (decision D18): start and stop the loopback
 * MCP endpoint that lets an agent outside the editor drive VS Code's integrated
 * browser. Starting is the person's act D11 asks for; the host and its gates
 * are `src/browserBridge.ts` and `src/core/browser/bridge.ts`.
 */

import { BrowserBridge } from '../browserBridge';
import type { Zer0Shell } from '../extension';
import { register } from './project';

export function registerBrowserCommands(shell: Zer0Shell): void {
  const bridge = new BrowserBridge(shell.context);
  shell.context.subscriptions.push(bridge);
  register(shell, 'browserBridge.start', () => bridge.start());
  register(shell, 'browserBridge.stop', () => bridge.stop());
}
