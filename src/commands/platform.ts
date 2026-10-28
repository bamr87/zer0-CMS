/**
 * The platform's two commands (PLAN G10): set and clear the person's token for
 * the configured platform. The token goes to the editor's SecretStorage, one
 * per platform origin, and from there only into requests the host sends to
 * that origin (`src/studio/studio.ts`, `src/core/studio/bridge.ts`); no webview,
 * setting, file or log line ever holds it.
 */

import type { Zer0Shell } from '../extension';
import { register } from './project';

export function registerPlatformCommands(shell: Zer0Shell): void {
  register(shell, 'platform.setToken', () => shell.studio.setToken());
  register(shell, 'platform.clearToken', () => shell.studio.clearToken());
}
