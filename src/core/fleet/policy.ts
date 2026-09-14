/**
 * The merge policy: what will merge a pull request without a human, and whether
 * it is armed right now.
 *
 * Three repository variables decide the fate of the queue an operator is
 * looking at:
 *
 *   * `AUTO_MERGE_ENABLED`  — squash-merges green bot pull requests
 *     (`lifehacker.dev` `.github/workflows/auto-merge.yml`);
 *   * `AUTO_UPDATE_ENABLED` — merges the default branch into a stale branch so
 *     it can go green (`auto-update.yml`);
 *   * `AUTO_FIX_ENABLED`    — pushes a fix onto a failing content branch, and
 *     escalates to `needs-human` when it gives up (`auto-fix.yml`).
 *
 * None of those workflows is a manifest lane, so **the console cannot toggle
 * them.** That is the whole reason this module exists as a read: an operator
 * staring at eleven open pull requests needs to know whether anything is going
 * to merge them, and the honest way to answer is to show the three switches as
 * they are set — not to offer a button that would arm the fleet's merge
 * authority from a CMS panel.
 *
 * `unknown` is a real value and the default. It means nobody asked (no
 * credential, offline, or the variable list came back `null`), and it is
 * different from `unset`, which means the repository really does not have the
 * variable and the workflow's `!= 'true'` gate therefore holds it off.
 *
 * Pure, read-only, and there is no writer here or anywhere else.
 */

import { MERGE_POLICY_SWITCHES, type MergePolicy } from '../shared/types';
import type { FleetSwitchValue } from './fleet';

/**
 * The three switches, as the repository currently reports them.
 *
 * `switches` is keyed by variable name and comes from one
 * `FleetClient.listVariables()` call — the same call that answers every lane's
 * switch, so reading the merge policy costs no extra request. A name the map
 * does not carry is `unknown`: a console that has not read a variable must say
 * so rather than draw the safe-looking answer.
 */
export function mergePolicyOf(switches: ReadonlyMap<string, FleetSwitchValue>): MergePolicy {
  const resolved = {} as MergePolicy['switches'];
  for (const name of MERGE_POLICY_SWITCHES) {
    resolved[name] = switches.get(name) ?? 'unknown';
  }
  return { switches: resolved };
}

/**
 * One sentence for the pull-request strip. The vocabulary lives here rather
 * than in the webview for the same reason `describeTriggers` does: a rendering
 * of a fleet fact is a fleet fact, and it should be testable without a DOM.
 */
export function describeMergePolicy(policy: MergePolicy): string {
  const armed = MERGE_POLICY_SWITCHES.filter((name) => policy.switches[name] === 'true');
  const unknown = MERGE_POLICY_SWITCHES.filter((name) => policy.switches[name] === 'unknown');
  if (unknown.length === MERGE_POLICY_SWITCHES.length) {
    return 'merge policy unknown — nobody has read these variables';
  }
  const head =
    armed.length === 0
      ? 'nothing merges without a human'
      : `armed: ${armed.join(', ')}`;
  return unknown.length === 0 ? head : `${head}; unknown: ${unknown.join(', ')}`;
}
