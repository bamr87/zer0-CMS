/**
 * The three site commands: switch, set active, and preview.
 *
 * Two of them move a pointer and one of them starts a process, so they are two
 * quite different kinds of thing sharing a file.
 *
 * **`site.pick` / `site.setActive` — an id, validated host-side.** The webview's
 * switcher and the Sites tree both post `{site: '<id>'}` and nothing else. This
 * file hands that id to `SiteRegistry.setActive`, which refuses anything that is
 * not a folder it currently holds. A stale id from a webview that was rendered
 * before a folder closed is dropped with a log line, not dispatched (D5).
 *
 * **`site.preview` — a task, never a spawn.** Two reasons, and the first is a
 * gate: `src/commands/` is fenced against `node:child_process` by eslint,
 * because the five execution vectors are the five files that own them and a
 * sixth is a design decision rather than an import. The second is better: a
 * `vscode.Task` is something a person can *see* in the terminal panel and stop
 * from it. A hidden child process serving a site on port 4000 until the window
 * closes is the kind of thing you discover a week later.
 *
 * It refuses, in words, four ways — untrusted workspace (decision D13: a serve
 * command is a command this repository named), a virtual folder (there is no
 * process to start), a platform whose profile declares no `serve`, and no open
 * folder at all. None of those is an exception; every one of them is a sentence
 * naming what would make it work.
 *
 * The preview URL is offered rather than opened. `bundle exec jekyll serve`
 * takes several seconds to bind, and a browser tab that says
 * ERR_CONNECTION_REFUSED is how a button stops being trusted; the notification
 * carries the URL and opens it when the person says so.
 */

import * as vscode from 'vscode';

import { workspaceTrusted } from '../config';
import type { Zer0Shell } from '../extension';
import type { Site, SiteRegistry } from '../sites';
import { notifyError, notifyInfo, notifyWarning } from '../uiState';
import { register } from './project';

/** The two verbs the dashboard is built around, exactly as the palette calls them. */
export interface SiteActions {
  /** Make one site active. `false` when the id names no open folder. */
  setActive(id: unknown): boolean;
  /** Start the site's serve task. `false` when it refused, with the reason shown. */
  preview(arg?: unknown): Promise<boolean>;
}

/**
 * The site an argument names: a webview's `{site}`, a tree row's `{site:{id}}`,
 * a bare id, or a `Uri` inside one of the folders.
 *
 * Everything here is a *lookup* against the registry — the argument never
 * carries a folder path this file then trusts.
 */
export function siteFrom(sites: SiteRegistry, arg: unknown): Site | undefined {
  if (typeof arg === 'string' && arg.trim() !== '') {
    return sites.byId(arg.trim());
  }
  if (arg instanceof vscode.Uri) {
    return sites.forUri(arg);
  }
  if (typeof arg === 'object' && arg !== null) {
    const record = arg as { site?: unknown; id?: unknown };
    if (typeof record.site === 'string') {
      return sites.byId(record.site);
    }
    // A `SiteTreeItem`, whose `site` is the whole `SiteView`.
    if (typeof record.site === 'object' && record.site !== null) {
      const nested = (record.site as { id?: unknown }).id;
      if (typeof nested === 'string') {
        return sites.byId(nested);
      }
    }
    if (typeof record.id === 'string') {
      return sites.byId(record.id);
    }
  }
  return undefined;
}

/** Ask which site, showing what each one is. */
async function pickSite(sites: SiteRegistry): Promise<string | undefined> {
  const views = await sites.views();
  if (views.length === 0) {
    await notifyWarning('no folder is open.');
    return undefined;
  }
  const only = views[0];
  if (views.length === 1 && only !== undefined) {
    await notifyInfo(`"${only.name}" is the only open folder.`);
    return undefined;
  }
  const picked = await vscode.window.showQuickPick(
    views.map((site) => ({
      label: site.active ? `$(circle-filled) ${site.name}` : `$(circle-outline) ${site.name}`,
      description: `${site.platform}${site.overlay === null ? '' : ` + ${site.overlay}`}${site.configured ? '' : ' · no project config'}`,
      detail: site.root,
      siteId: site.id,
    })),
    { placeHolder: 'Which site?', ignoreFocusOut: true },
  );
  return picked?.siteId;
}

// ---------------------------------------------------------------------------
// site.preview
// ---------------------------------------------------------------------------

/**
 * Start the detected platform's serve command as a task, and offer its URL.
 *
 * Every refusal below re-reads its own condition rather than trusting a context
 * key: `zer0Cms:workspace:trusted` gates the menu entry, and this asks
 * `workspaceTrusted()` again in the same function the palette calls (D13).
 */
export async function doPreviewSite(
  shell: Zer0Shell,
  sites: SiteRegistry,
  arg?: unknown,
): Promise<boolean> {
  const site = siteFrom(sites, arg) ?? sites.active();
  if (site === undefined) {
    await notifyWarning('open a folder before previewing a site.');
    return false;
  }

  if (!workspaceTrusted()) {
    await notifyError(
      `previewing "${site.name}" would run this repository's own serve command, and this ` +
        'workspace is not trusted. Trust the folder to allow it.',
    );
    return false;
  }

  if (site.folder.uri.scheme !== 'file') {
    await notifyError(
      `"${site.name}" is a ${site.folder.uri.scheme} folder — there is no local process to start ` +
        'for it, so there is nothing to preview.',
    );
    return false;
  }

  const platform = await sites.platformOf(site);
  const serve = platform.profile.commands.serve;
  if (serve === null || serve.length === 0) {
    await notifyWarning(
      `the ${platform.profile.id} profile declares no serve command, so zer0-CMS does not know ` +
        `how to start "${site.name}". Run the site the way its README says, then open ` +
        `${platform.profile.commands.previewUrl ?? 'its local URL'} yourself.`,
    );
    return false;
  }

  const [command, ...args] = serve;
  if (command === undefined) {
    await notifyWarning(`the ${platform.profile.id} profile's serve command is empty.`);
    return false;
  }
  const execution = new vscode.ShellExecution(command, args, { cwd: site.folder.uri.fsPath });
  const task = new vscode.Task(
    { type: 'shell' },
    site.folder,
    `preview ${site.name}`,
    'zer0-CMS',
    execution,
  );
  // A long-running server, not a build: `isBackground` stops VS Code waiting
  // for it to exit, and a dedicated panel keeps two sites' servers apart.
  task.isBackground = true;
  task.presentationOptions = {
    reveal: vscode.TaskRevealKind.Always,
    panel: vscode.TaskPanelKind.Dedicated,
    clear: false,
  };

  await vscode.tasks.executeTask(task);
  shell.log.info(`site preview: ${site.name} — ${serve.join(' ')} (in ${site.folder.uri.fsPath})`);

  const url = platform.profile.commands.previewUrl;
  if (url === null) {
    await notifyInfo(`serving "${site.name}" with \`${serve.join(' ')}\`.`);
    return true;
  }
  const answer = await notifyInfo(
    `serving "${site.name}" with \`${serve.join(' ')}\`. It takes a few seconds to bind ${url}.`,
    'Open preview',
  );
  if (answer === 'Open preview') {
    await vscode.env.openExternal(vscode.Uri.parse(url));
  }
  return true;
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerSiteCommands(shell: Zer0Shell, sites: SiteRegistry): SiteActions {
  const actions: SiteActions = {
    setActive: (arg) => {
      const site = siteFrom(sites, arg);
      if (site === undefined) {
        shell.log.warn('site.setActive: the argument named no open folder');
        return false;
      }
      return sites.setActive(site.id);
    },
    preview: (arg) => doPreviewSite(shell, sites, arg),
  };

  // --- Switch site ---------------------------------------------------------
  register(shell, 'site.pick', async () => {
    const id = await pickSite(sites);
    if (id !== undefined) {
      sites.setActive(id);
      // The other eleven sites have never been scanned in this window; the
      // person just said they care about this one, so it gets read now.
      await sites.active()?.store.refresh();
    }
  });

  // --- Set the active site (webview + tree row; `when: false` in the palette) ---
  register(shell, 'site.setActive', async (arg: unknown) => {
    if (!actions.setActive(arg)) {
      return;
    }
    await sites.active()?.store.refresh();
  });

  // --- Preview -------------------------------------------------------------
  register(shell, 'site.preview', async (arg: unknown) => {
    await doPreviewSite(shell, sites, arg);
  });

  return actions;
}
