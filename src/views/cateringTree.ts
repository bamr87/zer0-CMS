/**
 * The **Distribution** view — the four catering lanes, and the only two-level
 * tree in the extension.
 *
 * Lane A says "you already wrote this and never sent it". Lane B says "this
 * topic landed, write more of it". Lane C says "this topic did not land, and
 * that is worth naming out loud". Lane D says "this one worked and has since
 * gone stale". Together they answer *what to write next* from evidence rather
 * than from mood.
 *
 * Two rules keep the tree honest:
 *
 *   1. **Same formatters as the file.** The signal rows call
 *      `formatThousands` / `formatPercent` / `rateOf` from
 *      `core/catering/worklist.ts` — the functions that render
 *      `.cms/distribution/worklists/<date>-catering.md`. If the tree computed
 *      its own percentages, the screen and the exported worklist would drift
 *      apart at the second decimal and nobody would notice for a month.
 *      Locale-free by construction, so the numbers do not change when the
 *      machine's language does.
 *   2. **Empty is a state, not an error.** A lane with nothing in it collapses
 *      to a leaf with the description `nothing yet` and carries the worklist's
 *      own prose as its tooltip. An empty Lane B in particular means "there is
 *      no audience data" — the plan refuses to guess, and so does this view.
 *
 * The lanes are already truncated by `LANE_LIMITS` inside `buildCatering`, so
 * this file does no slicing of its own: the tree shows exactly the rows that
 * would be exported.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';

import {
  MIN_OBSERVATIONS,
  formatPercent,
  formatThousands,
  hasEvidence,
  rateOf,
  type CateringPlan,
  type ContentRecord,
  type TopicSignal,
} from '../core';
import type { WorkspaceStore } from '../store';

export type LaneId = 'A' | 'B' | 'C' | 'D';

/** Headings copied verbatim from `renderWorklist` — see rule 1 in the header. */
const LANE_TITLES: Record<LaneId, string> = {
  A: 'Lane A — Distribute what already exists',
  B: 'Lane B — Write more of what landed',
  C: 'Lane C — Say the quiet part',
  D: 'Lane D — Refresh what worked',
};

/** What each lane means when it has rows. */
const LANE_BLURBS: Record<LaneId, string> = {
  A: 'Content that scores well and has never been published off-site. No writing required, so this is the cheapest work on the list.',
  B: 'Topics at or above the median engagement rate. Evidence, not a guarantee.',
  C: 'Topics below the median. Low engagement is not the same as low value.',
  D: 'Content that earned engagement and has since gone stale.',
};

/** …and what each lane means when it does not. Also from the worklist. */
function emptyBlurb(lane: LaneId, plan: CateringPlan): string {
  switch (lane) {
    case 'A':
      return 'Everything publishable has been distributed.';
    case 'B':
      return hasEvidence(plan)
        ? `Not enough observations yet — a topic needs ${MIN_OBSERVATIONS} posts before its average means anything.`
        : 'No audience data yet. Topic rankings need published posts with statistics read back; until then this lane is empty rather than guessed.';
    case 'C':
      return 'Nothing to report.';
    case 'D':
      return 'Nothing published has gone stale.';
  }
}

/** `-1` is "never scored", rendered as the worklist's em dash. */
function healthCell(health: number): string {
  return health >= 0 ? String(health) : '—';
}

function signalDescription(signal: TopicSignal): string {
  const posts = `${signal.posts} post${signal.posts === 1 ? '' : 's'}`;
  return `${posts} · ${formatThousands(signal.impressions)} impressions · ${formatPercent(rateOf(signal))}`;
}

// ---------------------------------------------------------------------------
// Nodes
// ---------------------------------------------------------------------------

export class LaneTreeItem extends vscode.TreeItem {
  constructor(
    readonly lane: LaneId,
    readonly count: number,
    blurb: string,
  ) {
    super(
      LANE_TITLES[lane],
      count > 0
        ? vscode.TreeItemCollapsibleState.Expanded
        : vscode.TreeItemCollapsibleState.None,
    );
    this.id = `lane-${lane}`;
    // An empty lane says so in the slot where a count would be. Collapsing it
    // to `None` rather than `Collapsed` means the chevron does not invite a
    // click that would reveal nothing.
    this.description = count > 0 ? String(count) : 'nothing yet';
    this.contextValue = 'catering-lane';
    this.iconPath = new vscode.ThemeIcon('list-unordered');
    this.tooltip = new vscode.MarkdownString(`**${LANE_TITLES[lane]}**\n\n${blurb}`);
  }
}

/** A piece of content in lane A or D. Opens; can be drafted from. */
export class CateringContentItem extends vscode.TreeItem {
  constructor(
    readonly lane: LaneId,
    readonly record: ContentRecord,
    workspaceRoot: string,
  ) {
    super(record.title || record.path, vscode.TreeItemCollapsibleState.None);

    const parts = [healthCell(record.health), record.freshness];
    if (record.collection !== '') {
      parts.push(record.collection);
    }
    this.id = `lane-${lane}-${record.path}`;
    this.description = parts.join(' · ');
    this.contextValue = 'catering-item';
    this.iconPath = new vscode.ThemeIcon('file-text');
    this.tooltip = record.path;

    if (workspaceRoot !== '') {
      const absolute = path.resolve(workspaceRoot, record.path);
      this.resourceUri = vscode.Uri.file(absolute);
      this.command = { command: 'zer0Cms.openFile', title: 'Open', arguments: [absolute] };
    }
  }
}

/** A topic signal in lane B or C. There is no file behind it — no command. */
export class CateringSignalItem extends vscode.TreeItem {
  constructor(
    readonly lane: LaneId,
    readonly signal: TopicSignal,
  ) {
    super(signal.topic, vscode.TreeItemCollapsibleState.None);
    this.id = `lane-${lane}-${signal.topic}`;
    this.description = signalDescription(signal);
    this.contextValue = 'catering-signal';
    this.iconPath = new vscode.ThemeIcon('graph');
    this.tooltip = new vscode.MarkdownString(
      [
        `**${signal.topic}**`,
        '',
        `- posts: ${signal.posts}`,
        `- impressions: ${formatThousands(signal.impressions)}`,
        `- engagements: ${formatThousands(signal.engagements)}`,
        `- engagement rate: ${formatPercent(rateOf(signal))}`,
      ].join('\n'),
    );
  }
}

export type CateringNode = LaneTreeItem | CateringContentItem | CateringSignalItem;

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export class CateringTreeProvider
  implements vscode.TreeDataProvider<CateringNode>, vscode.Disposable
{
  private readonly emitter = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData: vscode.Event<void> = this.emitter.event;

  private readonly subscription: vscode.Disposable;

  constructor(private readonly store: WorkspaceStore) {
    this.subscription = store.onDidChange(() => this.emitter.fire());
  }

  getTreeItem(element: CateringNode): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: CateringNode): Promise<CateringNode[]> {
    const snapshot = await this.store.current();
    const plan = snapshot.catering;

    if (element === undefined) {
      return (['A', 'B', 'C', 'D'] as const).map((lane) => {
        const count = this.laneCount(plan, lane);
        return new LaneTreeItem(
          lane,
          count,
          count > 0 ? LANE_BLURBS[lane] : emptyBlurb(lane, plan),
        );
      });
    }

    if (!(element instanceof LaneTreeItem)) {
      return [];
    }

    const root = snapshot.cfg.workspaceRoot;
    switch (element.lane) {
      case 'A':
        return plan.undistributed.map((record) => new CateringContentItem('A', record, root));
      case 'B':
        return plan.proven.map((signal) => new CateringSignalItem('B', signal));
      case 'C':
        return plan.quiet.map((signal) => new CateringSignalItem('C', signal));
      case 'D':
        return plan.refresh.map((record) => new CateringContentItem('D', record, root));
    }
  }

  private laneCount(plan: CateringPlan, lane: LaneId): number {
    switch (lane) {
      case 'A':
        return plan.undistributed.length;
      case 'B':
        return plan.proven.length;
      case 'C':
        return plan.quiet.length;
      case 'D':
        return plan.refresh.length;
    }
  }

  dispose(): void {
    this.subscription.dispose();
    this.emitter.dispose();
  }
}
