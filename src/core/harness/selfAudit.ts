/**
 * The self-audit — the fleet's own rulebook, run over the files this console is
 * about to propose writing.
 *
 * The point is symmetry. The Fleet tab grades other repositories' workflows with
 * `@bamr87/fleet-engines`' fifteen rules: does it have a kill switch, does it
 * declare a timeout, does it pin what it uses, does it name its concurrency
 * group, does it try OAuth before an API key. A generator that exempted its own
 * output from that rulebook would be a generator whose output nobody could trust
 * — so a lane this console writes passes the same audit it would apply to a lane
 * somebody else wrote, and when it does not, the plan says so *before* the files
 * are written rather than a week later on a dashboard.
 *
 * **This is the one file in `src/core/harness/` allowed to import the engines
 * seam, and it is deliberately not barrel-exported.** `dist/mcp-server.js` is
 * built with an empty bare-import allow-list, and esbuild resolves the whole
 * import graph before it tree-shakes, so "the MCP server never calls it" is not
 * a defence — reachability is. eslint bans this path from
 * `src/mcp` for the same reason it bans the seam itself. `planScaffold` takes
 * this function as an injected `ctx.audit`, which is what lets the same planner
 * serve the extension host (with the audit) and the MCP preview (without it,
 * carrying the preflight findings alone and saying which it has).
 *
 * **Three findings are expected, and none of them is suppressed.** All three are
 * the same blind spot: the rulebook's workflow-scoped rules read one file, and
 * they cannot follow a `uses:` into the hub to see what it already declares.
 *
 *   - `pin-branch` on `bamr87/bamr87/.github/actions/claude-run@main`. The rule
 *     cannot tell a floating third-party tag from this fleet's own runner, which
 *     is consumed by reference on purpose — pinning it would be the thing the
 *     house rule forbids.
 *   - `concurrency` on a caller of the reusable lane. The group is declared
 *     inside `ai-lane.yml` (`ai-lane-<repo>-<lane>`, never cancelling a writer),
 *     one repository over, where this rule cannot see it. A duplicate block at
 *     the call site would satisfy the rule and mean nothing.
 *   - `top-level-write` on the same file. The permissions are at the top level
 *     because a called workflow inherits the caller's and may only narrow them;
 *     that is the hub's design, stated in the template's own comment.
 *
 * Silencing any of them here would be the console grading itself on a curve, so
 * they are reported like any other finding and the fixes are upstream asks. What
 * the console does assert about itself is stronger and testable: **no file it
 * generates trips a `fail`-severity rule** — not the kill switch, not loop
 * safety, and not the timeout.
 */

import { auditWorkflow, extractFacts } from '../fleet/engines';
import type { AuditFinding } from '../fleet/engines';
import type { AuditFindingView, ScaffoldPlan } from '../shared/types';

/** Only the workflow files are auditable; the rulebook is about workflows. */
function isWorkflow(rel: string): boolean {
  return /^\.github\/workflows\/[^/]+\.ya?ml$/.test(rel);
}

/**
 * Every applicable rule, over every workflow the plan would write.
 *
 * The `fix` sentence is carried into the message rather than dropped: a finding
 * that says what is wrong and not what to do about it is a finding a person has
 * to go and look up, and `AuditFindingView` — which exists so that neither the
 * webview protocol nor the core barrel has to name a package type — has nowhere
 * else to put it.
 */
export function selfAudit(plan: ScaffoldPlan): AuditFindingView[] {
  const out: AuditFindingView[] = [];
  for (const file of plan.files) {
    if (!isWorkflow(file.rel)) {
      continue;
    }
    for (const finding of auditWorkflow(extractFacts(file.rel, file.contents))) {
      out.push(toView(finding, file.rel));
    }
  }
  return out;
}

function toView(finding: AuditFinding, fallbackPath: string): AuditFindingView {
  const fix = finding.fix.trim();
  return {
    rule: finding.ruleId,
    severity: finding.severity,
    message: fix === '' ? finding.message : `${finding.message} — ${fix}`,
    path: finding.path ?? fallbackPath,
  };
}
