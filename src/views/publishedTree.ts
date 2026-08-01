/**
 * The **Published** view — the idempotency ledger, newest first.
 *
 * One row per share: the canonical URL that was published, when, by which
 * target, and which file it came from. This is the answer to "did we already
 * send this?", and it is the same answer `publishPreview` gets — both read
 * `shareEntries()`, which skips `_`-prefixed metadata keys and any record
 * without a `urn`. Enumerating `Object.entries(ledger)` directly would show
 * the `_meta` block as if it were a post.
 *
 * Sorting is a plain string compare on `posted_at`, descending. That works
 * because the stamps are `utcStamp()` — fixed-width, UTC, second precision —
 * so lexical order *is* chronological order. Parsing them into `Date`s would
 * buy nothing and would turn a malformed stamp into a `NaN` that sorts
 * unpredictably instead of simply sorting last.
 *
 * Like every view here, this one reads `store.current()` and never the disk.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import type { LedgerEntry } from '../core';
import type { WorkspaceStore } from '../store';

export class PublishedTreeItem extends vscode.TreeItem {
  constructor(
    readonly url: string,
    readonly entry: LedgerEntry,
    workspaceRoot: string,
  ) {
    super(entry.source_file ?? url, vscode.TreeItemCollapsibleState.None);

    this.id = url;
    this.description = [entry.type, entry.posted_at].filter((part) => part !== '').join(' · ');
    this.contextValue = 'published-entry';
    this.iconPath = new vscode.ThemeIcon('cloud-upload', new vscode.ThemeColor('charts.blue'));
    this.tooltip = new vscode.MarkdownString(
      [
        `**${url}**`,
        '',
        `- urn: \`${entry.urn}\``,
        `- posted: ${entry.posted_at === '' ? 'unknown' : entry.posted_at}`,
        `- type: ${entry.type}`,
        ...(entry.target === undefined ? [] : [`- target: \`${entry.target}\``]),
        ...(entry.source_file === undefined ? [] : [`- source: \`${entry.source_file}\``]),
      ].join('\n'),
    );

    // Only rows that name a source file can be opened. A ledger written by the
    // Python lane may not carry one, and a row that silently opened the wrong
    // file would be worse than a row that opens nothing.
    if (entry.source_file !== undefined && workspaceRoot !== '') {
      const absolute = path.resolve(workspaceRoot, entry.source_file);
      this.resourceUri = vscode.Uri.file(absolute);
      this.command = { command: 'zer0Cms.openFile', title: 'Open source', arguments: [absolute] };
    }
  }
}

export class PublishedTreeProvider
  implements vscode.TreeDataProvider<PublishedTreeItem>, vscode.Disposable
{
  private readonly emitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData: vscode.Event<void> = this.emitter.event;

  private readonly subscription: vscode.Disposable;

  constructor(private readonly store: WorkspaceStore) {
    this.subscription = store.onDidChange(() => this.emitter.fire());
  }

  getTreeItem(element: PublishedTreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: PublishedTreeItem): Promise<PublishedTreeItem[]> {
    if (element !== undefined) {
      return [];
    }
    const snapshot = await this.store.current();
    return [...snapshot.published]
      .sort((a, b) => b[1].posted_at.localeCompare(a[1].posted_at))
      .map(([url, entry]) => new PublishedTreeItem(url, entry, snapshot.cfg.workspaceRoot));
  }

  dispose(): void {
    this.subscription.dispose();
    this.emitter.dispose();
  }
}
