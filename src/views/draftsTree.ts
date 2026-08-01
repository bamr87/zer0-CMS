/**
 * The **Drafts** view — the governed queue, as a tree.
 *
 * One line per file in `governance.draftsFolder`, ordered the way a reviewer
 * works: everything waiting on a human first, then what has been approved but
 * not sent, then everything else.
 *
 * The load-bearing detail in this file is one string:
 *
 * ```ts
 * this.contextValue = `draft-${draft.status}`;
 * ```
 *
 * That is the *entire* menu-gating mechanism for the queue. `package.json`
 * matches on it — `viewItem == draft-pending` puts **Approve** on the row,
 * `viewItem =~ /^draft-(pending|approved)$/` puts **Publish** there, and
 * `viewItem =~ /^draft-/` puts Review/Guard/Preview on every row. Change the
 * shape of the string here and the menus silently disappear; there is no
 * compiler that connects the two, so the format is pinned by a test instead.
 *
 * Note what the context value is **not**: permission. A visible Publish button
 * means "this row is the right shape for the command", not "this draft may be
 * published". `commands/governance.ts` re-reads the file from disk and re-runs
 * every gate before it writes anything (decision D5). The menus are an
 * affordance; the gate is somewhere else on purpose.
 *
 * This provider never touches the filesystem. It renders `store.current()` and
 * nothing else, so the tree, the panel and the dashboard can never disagree
 * about what is in the queue.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  STATUS_APPROVED,
  STATUS_PENDING,
  STATUS_PUBLISHED,
  commentaryOf,
  sourceOf,
  titleOf,
  truncate,
  type DraftFile,
} from '../core';
import type { WorkspaceStore } from '../store';

/** How far the tooltip quotes a draft's commentary before it gets in the way. */
const TOOLTIP_CHARS = 400;

/**
 * Queue order: what is waiting on a human, then what is waiting on a machine,
 * then everything already dealt with. Ranks are deliberately coarse — an
 * unrecognised status sorts last rather than throwing the list into a shape
 * nobody predicted.
 */
function statusRank(status: string): number {
  if (status === STATUS_PENDING) {
    return 0;
  }
  if (status === STATUS_APPROVED) {
    return 1;
  }
  return 2;
}

function iconFor(status: string): vscode.ThemeIcon {
  switch (status) {
    case STATUS_PENDING:
      return new vscode.ThemeIcon('circle-large-outline', new vscode.ThemeColor('charts.yellow'));
    case STATUS_APPROVED:
      return new vscode.ThemeIcon('pass', new vscode.ThemeColor('charts.green'));
    case STATUS_PUBLISHED:
      return new vscode.ThemeIcon('cloud-upload', new vscode.ThemeColor('charts.blue'));
    default:
      return new vscode.ThemeIcon('question');
  }
}

export class DraftTreeItem extends vscode.TreeItem {
  constructor(readonly draft: DraftFile) {
    super(titleOf(draft) || path.basename(draft.path), vscode.TreeItemCollapsibleState.None);

    const source = sourceOf(draft);
    this.id = draft.path;
    this.description = `${draft.status} · ${draft.type}`;
    this.contextValue = `draft-${draft.status}`;
    this.iconPath = iconFor(draft.status);
    this.resourceUri = vscode.Uri.file(draft.path);

    const lines = [
      `**${path.basename(draft.path)}**`,
      '',
      `- status: \`${draft.status}\``,
      `- type: \`${draft.type}\``,
      ...(source === '' ? [] : [`- source: \`${source}\``]),
      '',
      truncate(commentaryOf(draft).replace(/\s+/g, ' '), TOOLTIP_CHARS),
    ];
    this.tooltip = new vscode.MarkdownString(lines.join('\n'));

    // `zer0Cms.openFile` rather than `vscode.open` so that every "open this"
    // in the extension goes through one handler — the one that also copes with
    // a workspace-relative path arriving from a webview.
    this.command = {
      command: 'zer0Cms.openFile',
      title: 'Open draft',
      arguments: [draft.path],
    };
  }
}

export class DraftsTreeProvider implements vscode.TreeDataProvider<DraftTreeItem>, vscode.Disposable {
  private readonly emitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData: vscode.Event<void> = this.emitter.event;

  private readonly subscription: vscode.Disposable;

  constructor(private readonly store: WorkspaceStore) {
    this.subscription = store.onDidChange(() => this.emitter.fire());
  }

  getTreeItem(element: DraftTreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: DraftTreeItem): Promise<DraftTreeItem[]> {
    if (element !== undefined) {
      return [];
    }
    const { drafts } = await this.store.current();
    return [...drafts]
      .sort(
        (a, b) => statusRank(a.status) - statusRank(b.status) || a.path.localeCompare(b.path),
      )
      .map((draft) => new DraftTreeItem(draft));
  }

  dispose(): void {
    this.subscription.dispose();
    this.emitter.dispose();
  }
}
