/**
 * The **Content** view — distributable content, best health first.
 *
 * The rows come from `snapshot.distributable`, which is `isDistributable()`
 * applied to whatever the `.cms/` contract holds — or, when the workspace has
 * no contract, to the page index standing in for it with `health: -1` and the
 * honestly degraded rule "not a draft and has a title" (decision D9). Either
 * way the shape is a `ContentRecord`, so this file has exactly one code path.
 *
 * Two context values, and the difference between them is the whole point of
 * the view:
 *
 * | `contextValue` | meaning |
 * |---|---|
 * | `content-article` | publishable, and the ledger has never seen it |
 * | `content-article-posted` | publishable, and a ledger entry names it as a `source_file` |
 *
 * `package.json` puts **New draft from content** on `/^content-article/`, so
 * it appears on both — drafting a second update about a piece you already
 * published is a normal thing to want. The distinction is there so the list
 * tells you, at a glance, what has never left the repository.
 *
 * The `posted` answer comes from `snapshot.publishedSourceFiles`, a set built
 * by `shareEntries()` from the ledger. Not from a filename convention, and not
 * from a second scan: the ledger is the only thing that knows.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import { healthBucket, type ContentRecord } from '../core';
import type { WorkspaceStore } from '../store';

/** Health scores read as colour long before they read as numbers. */
const HEALTH_COLOURS: Record<ReturnType<typeof healthBucket>, string | undefined> = {
  unknown: undefined,
  poor: 'charts.red',
  fair: 'charts.yellow',
  good: 'charts.blue',
  excellent: 'charts.green',
};

function healthIcon(record: ContentRecord, posted: boolean): vscode.ThemeIcon {
  if (posted) {
    return new vscode.ThemeIcon('pass-filled', new vscode.ThemeColor('charts.green'));
  }
  const colour = HEALTH_COLOURS[healthBucket(record.health)];
  return colour === undefined
    ? new vscode.ThemeIcon('file-text')
    : new vscode.ThemeIcon('file-text', new vscode.ThemeColor(colour));
}

/** `-1` is "the engine never scored this", which is not the same as zero. */
function healthCell(health: number): string {
  return health >= 0 ? `health ${health}` : 'health —';
}

export class ContentTreeItem extends vscode.TreeItem {
  constructor(
    readonly record: ContentRecord,
    readonly posted: boolean,
    workspaceRoot: string,
  ) {
    super(record.title || record.path, vscode.TreeItemCollapsibleState.None);

    const parts = [healthCell(record.health), record.freshness];
    if (record.collection !== '') {
      parts.push(record.collection);
    }
    if (posted) {
      parts.push('posted');
    }

    this.id = record.path;
    this.description = parts.join(' · ');
    this.contextValue = posted ? 'content-article-posted' : 'content-article';
    this.iconPath = healthIcon(record, posted);

    const issues = record.issues.length;
    this.tooltip = new vscode.MarkdownString(
      [
        `**${record.title || record.path}**`,
        '',
        `- \`${record.path}\``,
        `- ${healthCell(record.health)} · ${record.freshness} · ${record.wordCount} words`,
        `- ${issues === 0 ? 'no issues' : `${issues} issue${issues === 1 ? '' : 's'}`}`,
        `- ${posted ? 'already published' : 'never published'}`,
      ].join('\n'),
    );

    // Records carry workspace-relative POSIX paths; the editor needs an
    // absolute one. In a folderless window there is no root to join against,
    // and no file to open either, so the row stays inert rather than pointing
    // at a path that resolves against the process's cwd.
    if (workspaceRoot !== '') {
      const absolute = path.resolve(workspaceRoot, record.path);
      this.resourceUri = vscode.Uri.file(absolute);
      this.command = { command: 'zer0Cms.openFile', title: 'Open', arguments: [absolute] };
    }
  }
}

export class ContentTreeProvider
  implements vscode.TreeDataProvider<ContentTreeItem>, vscode.Disposable
{
  private readonly emitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData: vscode.Event<void> = this.emitter.event;

  private readonly subscription: vscode.Disposable;

  constructor(private readonly store: WorkspaceStore) {
    this.subscription = store.onDidChange(() => this.emitter.fire());
  }

  getTreeItem(element: ContentTreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: ContentTreeItem): Promise<ContentTreeItem[]> {
    if (element !== undefined) {
      return [];
    }
    const snapshot = await this.store.current();
    // `distributable()` already returns best-health-first; re-sorting here
    // would be a second opinion the worklist and the dashboard do not share.
    return snapshot.distributable.map(
      (record) =>
        new ContentTreeItem(
          record,
          snapshot.publishedSourceFiles.has(record.path),
          snapshot.cfg.workspaceRoot,
        ),
    );
  }

  dispose(): void {
    this.subscription.dispose();
    this.emitter.dispose();
  }
}
