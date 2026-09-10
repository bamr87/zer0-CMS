/**
 * The route registry: `DASHBOARD_ROUTES` and `DASHBOARD_TABS` are one table
 * seen twice, and this file is what makes that true rather than intended.
 *
 * `DASHBOARD_ROUTES` is every route the dashboard *can* render, in final
 * display order — eleven, of which six are served today. `DASHBOARD_TABS` is
 * the list the host is willing to route to, and it grows one PR at a time as
 * each package lands the screen behind it. The invariant that keeps those two
 * from drifting is: **the tabs' ids are a subset of the routes, in the same
 * relative order.** Subset without order gives you a tab bar whose sequence
 * depends on merge order; order without subset gives you a tab that routes
 * nowhere.
 *
 * No DOM here. The route table is data, and asserting against data is cheaper
 * and more durable than asserting against a rendered tab bar.
 */

import { strict as assert } from 'node:assert';

import {
  DASHBOARD_ROUTES,
  DASHBOARD_TABS,
  type DashboardRoute,
} from '../webview/shared/protocol';

suite('dashboard route registry', () => {
  test('the eleven routes are unique and in the declared display order', () => {
    // The compile-time half: a route added to the union and forgotten in the
    // array — or the reverse — fails to type-check on this assignment, which is
    // what lets `main.ts` derive its route set and its renderer table from one.
    const fromUnion: readonly DashboardRoute[] = DASHBOARD_ROUTES;
    assert.equal(fromUnion.length, 11);
    assert.equal(DASHBOARD_ROUTES.length, 11);
    assert.equal(new Set(DASHBOARD_ROUTES).size, DASHBOARD_ROUTES.length);
    // The order is a decision taken once, not an accident of merge sequence.
    assert.deepEqual(
      [...DASHBOARD_ROUTES],
      [
        'sites',
        'contents',
        'drafts',
        'audit',
        'catering',
        'fleet',
        'harness',
        'workflows',
        'monitor',
        'settings',
        'welcome',
      ],
    );
  });

  test('every tab id is a route, and no id repeats', () => {
    const ids = DASHBOARD_TABS.map((tab) => tab.id);
    assert.equal(new Set(ids).size, ids.length, 'a tab id appears twice');
    for (const id of ids) {
      assert.ok(
        DASHBOARD_ROUTES.includes(id),
        `tab "${id}" is not in DASHBOARD_ROUTES — it would route nowhere`,
      );
    }
  });

  test('the tabs are a subset of the routes in the same relative order', () => {
    const ids = DASHBOARD_TABS.map((tab) => tab.id);
    const positions = ids.map((id) => DASHBOARD_ROUTES.indexOf(id));
    const sorted = [...positions].sort((a, b) => a - b);
    assert.deepEqual(
      positions,
      sorted,
      `DASHBOARD_TABS is out of display order: ${ids.join(', ')}`,
    );
  });

  test('every tab carries a label and a codicon name', () => {
    for (const tab of DASHBOARD_TABS) {
      assert.ok(tab.label.trim() !== '', `tab "${tab.id}" has no label`);
      assert.ok(tab.icon.trim() !== '', `tab "${tab.id}" has no icon`);
      // A codicon name, not a class or a path: `icon()` prefixes `codicon-`.
      assert.match(tab.icon, /^[a-z0-9-]+$/, `tab "${tab.id}" icon looks like a class`);
    }
  });
});
