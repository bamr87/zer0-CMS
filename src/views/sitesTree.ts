/**
 * The **Sites** view — one row per open workspace folder.
 *
 * The fifth tree, and the only one that is about the *window* rather than about
 * one site's content. It exists because eleven of this fleet's twelve open
 * folders used to be invisible: `zer0Cms.content`, `zer0Cms.drafts` and the
 * rest all render the active site, and until there was somewhere to see the
 * others, "the active site" was a phrase with no user interface behind it.
 *
 * `package.json` hides the whole view behind `when: zer0Cms:sites:multi`, so a
 * one-folder window — which is most of them — never sees a tree that would only
 * ever hold a single row.
 *
 * Like the other four, this provider **never touches the filesystem**. It
 * renders `SiteRegistry.views()`, which is the same projection the dashboard's
 * Sites tab draws, so the tree and the tab cannot disagree about which site is
 * active or how many pages it holds. Clicking a row is
 * `zer0Cms.site.setActive` with an id — an intent and a target — and the
 * command validates that id against the registry before anything moves
 * (decision D5).
 *
 * `contextValue` is `site` or `site-active`, in the same shape the other trees
 * use, so a future menu can offer "Preview this site" on any row and "Make
 * active" on the ones that are not.
 */

import * as vscode from 'vscode';

import type { SiteRegistry } from '../sites';
import type { SiteView } from '../webview/shared/protocol';

/** How the row's second line reads. Counts stay honest about an unscanned site. */
function describeSite(site: SiteView): string {
  const parts = [site.platform + (site.overlay === null ? '' : ` + ${site.overlay}`)];
  if (!site.configured) {
    parts.push('no project config');
  }
  parts.push(
    site.detectionSource.includes('not scanned')
      ? 'not scanned yet'
      : `${site.counts.pages} page(s)`,
  );
  return parts.join(' · ');
}

export class SiteTreeItem extends vscode.TreeItem {
  constructor(readonly site: SiteView) {
    super(site.name, vscode.TreeItemCollapsibleState.None);

    this.id = site.id;
    this.description = describeSite(site);
    this.contextValue = site.active ? 'site-active' : 'site';
    this.iconPath = site.active
      ? new vscode.ThemeIcon('circle-filled', new vscode.ThemeColor('charts.green'))
      : new vscode.ThemeIcon('circle-outline');
    this.resourceUri = vscode.Uri.parse(site.id);

    const lines = [
      `**${site.name}**${site.active ? ' — active' : ''}`,
      '',
      `- platform: \`${site.platform}\`${site.overlay === null ? '' : ` (+ \`${site.overlay}\`)`}`,
      `- detected by: ${site.detectionSource}`,
      `- project config: ${site.configured ? 'present' : 'absent'}`,
      `- fleet manifest: ${site.manifestPresent ? 'present' : 'absent'}`,
      `- content roots: ${site.contentRoots.length === 0 ? '(none registered)' : site.contentRoots.join(', ')}`,
      `- ${site.counts.pages} page(s), ${site.counts.drafts} draft(s)`,
      `- root: \`${site.root}\``,
      ...(site.scheme === 'file' ? [] : [`- scheme: \`${site.scheme}\` — this folder cannot run a process`]),
    ];
    this.tooltip = new vscode.MarkdownString(lines.join('\n'));

    // An id, and nothing else. The command re-checks it against the registry.
    this.command = {
      command: 'zer0Cms.site.setActive',
      title: 'Set the active site',
      arguments: [{ site: site.id }],
    };
  }
}

export class SitesTreeProvider implements vscode.TreeDataProvider<SiteTreeItem>, vscode.Disposable {
  private readonly emitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData: vscode.Event<void> = this.emitter.event;

  private readonly subscription: vscode.Disposable;

  constructor(private readonly sites: SiteRegistry) {
    // The registry fires for a folder change, an active-site change, and any
    // site's store rebuilding — all three change a row on this tree.
    this.subscription = sites.onDidChange(() => this.emitter.fire());
  }

  getTreeItem(element: SiteTreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: SiteTreeItem): Promise<SiteTreeItem[]> {
    if (element !== undefined) {
      return [];
    }
    const views = await this.sites.views();
    return views.map((site) => new SiteTreeItem(site));
  }

  dispose(): void {
    this.subscription.dispose();
    this.emitter.dispose();
  }
}
