/**
 * Preflight — the house rules, checked against a lane spec before anything is
 * rendered, let alone written.
 *
 * Every rule here exists because it was got wrong somewhere in this fleet, and
 * every one of them is cheaper to catch in a spec than in a workflow that has
 * already been committed and scheduled:
 *
 *  - **A lane with no `*_ENABLED` switch** has its kill switch hosted nowhere.
 *    The whole fleet's posture is "every loop is OFF until somebody sets its
 *    variable"; a generated lane that skips that is a loop nobody can stop
 *    without editing a file.
 *  - **A cron minute of `:00`.** GitHub schedules the whole world on the hour;
 *    a fleet that also does queues behind itself, and the runs that lose the
 *    race are the ones that look "flaky" three weeks later.
 *  - **A `secrets.X || github.token` chain.** It reads as a graceful fallback
 *    and behaves as a trap: an expired PAT is *present*, so it wins the `||` and
 *    fails later as `could not read Username`, and an absent one degrades to a
 *    token GitHub forbids from opening a pull request. Probe, do not chain.
 *  - **A prompt that never names the result file.** The lane fails when the file
 *    is empty — that is how a crashed agent shows RED instead of a green skip —
 *    so an agent that was never told to write it turns the assertion into noise.
 *  - **A fan-out whose legs are indistinguishable.** A matrix over five items
 *    with a prompt that never names `${{ matrix.item }}` is five agents given
 *    the same instruction, racing each other's "is one already open?" check.
 *  - **A `factory--*` lane id.** Those files are GitFactory's compiled output.
 *    This console does not own them (`docs/ARCHITECTURE.md`, "What this console
 *    will never do").
 *
 * Engines-free on purpose: `zer0_lane_preview` runs inside `dist/mcp-server.js`,
 * which may not bundle a bare import at all, and a preview that could not tell
 * you the lane has no kill switch would not be worth previewing.
 *
 * **Each check has its own `kind`.** They were briefly reported as
 * `manifest-drift` because `HarnessFindingKind` had been declared for the
 * inventory alone, and a person reading "manifest drift" when the real problem
 * is a cron on the hour has been told the wrong thing. The union now carries
 * `no-trigger`, `cron-on-the-hour`, `matrix-without-item`, `factory-owned-path`
 * and `prompt-missing-result-file`, so the badge and the message agree.
 */

import type { HarnessFinding, LaneSpec, Severity } from '../shared/types';

import { workflowPathFor } from './render';

/** A file stem safe to write and safe to name in a `uses:`/`agent:` input. */
const SAFE_STEM = /^[a-z0-9][a-z0-9._-]*$/;

/** `SOMETHING_ENABLED` — the fleet's kill-switch variable naming, exactly. */
export const SWITCH_NAME = /^[A-Z][A-Z0-9_]*_ENABLED$/;

/** `${{ secrets.FLEET_TOKEN || github.token }}` and every spelling of it. */
export const TOKEN_PRESENCE_CHAIN = /secrets\.[A-Z_][A-Z0-9_]*\s*\|\|/;

/** GitFactory's compiled output, which this console never writes. */
export const FACTORY_OWNED = /^factory--/;

function finding(
  kind: HarnessFinding['kind'],
  severity: Severity,
  path: string | null,
  message: string,
): HarnessFinding {
  return { kind, severity, path, message };
}

/**
 * Everything wrong with a spec, before a byte of it is rendered. An empty array
 * means the house rules are satisfied — not that the lane is a good idea.
 */
export function preflightLaneSpec(spec: LaneSpec): HarnessFinding[] {
  const out: HarnessFinding[] = [];
  const workflow = workflowPathFor(spec);

  // 1 — the kill switch.
  if (spec.switch === null || spec.switch === '') {
    out.push(
      finding(
        'switch-hosted-elsewhere',
        'error',
        workflow,
        'this lane declares no `*_ENABLED` variable, so its kill switch is hosted nowhere — every loop in this fleet is off until somebody sets its own variable, and a generated one may not be the exception',
      ),
    );
  } else if (!SWITCH_NAME.test(spec.switch)) {
    out.push(
      finding(
        'switch-hosted-elsewhere',
        'error',
        workflow,
        `\`${spec.switch}\` is not a kill-switch name: the fleet reads \`vars.<SOMETHING>_ENABLED\`, and a variable outside that shape is one no other tool will find`,
      ),
    );
  }

  // 2 — the schedule.
  if (spec.cron === null && spec.events.length === 0) {
    out.push(
      finding(
        'no-trigger',
        'error',
        workflow,
        'this lane has no trigger at all — no schedule and no event, so nothing but a manual dispatch would ever run it',
      ),
    );
  }
  if (spec.cron !== null) {
    const fields = spec.cron.trim().split(/\s+/);
    if (fields.length !== 5) {
      out.push(
        finding(
          'cron-on-the-hour',
          'error',
          workflow,
          `\`${spec.cron}\` is not a five-field cron expression`,
        ),
      );
    } else if (fields[0] === '0') {
      out.push(
        finding(
          'cron-on-the-hour',
          'error',
          workflow,
          `\`${spec.cron}\` fires on the hour — pick an odd minute. Every lane in a fleet scheduled at :00 queues behind the rest of GitHub, and the legs that lose that race are the ones that look flaky later`,
        ),
      );
    }
  }

  // 3 — the token chain.
  for (const [label, text] of [
    ['prompt', spec.prompt],
    ['system', spec.system],
    ['pre-run', spec.preRun ?? ''],
    ['post-run', spec.postRun ?? ''],
  ] as const) {
    if (TOKEN_PRESENCE_CHAIN.test(text)) {
      out.push(
        finding(
          'token-presence-chain',
          'error',
          workflow,
          `the ${label} carries a \`secrets.X || …\` presence chain — an expired token is present, so it wins the \`||\` and fails later at push time. Probe the token and export the winner instead`,
        ),
      );
    }
  }

  // 4 — the result file the lane asserts on.
  if (spec.resultFile !== '' && !spec.prompt.includes(spec.resultFile)) {
    out.push(
      finding(
        'unmetered-model-call',
        'warning',
        workflow,
        `the lane fails when \`${spec.resultFile}\` is empty, but the prompt never tells the agent to write it — so the assertion that makes a crashed run show RED would fire on every successful one too`,
      ),
    );
  }

  // 5 — a fan-out whose legs are indistinguishable.
  if (
    spec.matrix !== null &&
    'static' in spec.matrix &&
    spec.matrix.static.length > 1 &&
    !spec.prompt.includes('matrix.')
  ) {
    out.push(
      finding(
        'matrix-without-item',
        'warning',
        workflow,
        `this lane fans out over ${spec.matrix.static.length} items but the prompt never names \`\${{ matrix.item }}\` — every leg would run the same instruction, and ${spec.matrix.static.length} identical agents racing each other's "is one already open?" check is how a fan-out produces one result and four duplicates`,
      ),
    );
  }

  // 6 — files this console does not own.
  if (FACTORY_OWNED.test(spec.id)) {
    out.push(
      finding(
        'factory-owned-path',
        'error',
        workflow,
        `\`${workflow}\` is GitFactory's compiled output — this console operates lanes in the editor, it does not own the compiler's files`,
      ),
    );
  }

  // 7 — names that have to survive being a filename and an input value.
  if (!SAFE_STEM.test(spec.id)) {
    out.push(
      finding(
        'agent-name-mismatch',
        'error',
        workflow,
        `\`${spec.id}\` is not a usable lane id: it becomes a filename, a concurrency group and a metering role, so it has to be lowercase letters, digits, \`.\`, \`_\` and \`-\``,
      ),
    );
  }
  if (!SAFE_STEM.test(spec.agent)) {
    out.push(
      finding(
        'agent-name-mismatch',
        'error',
        `.claude/agents/${spec.agent}.md`,
        `\`${spec.agent}\` is not a usable agent name: the runner resolves \`.claude/agents/<name>.md\` literally, and the file's own \`name:\` must equal its stem`,
      ),
    );
  }
  if (spec.skill !== null && spec.skill !== '' && !SAFE_STEM.test(spec.skill)) {
    out.push(
      finding(
        'dangling-skill',
        'error',
        `.claude/skills/${spec.skill}/SKILL.md`,
        `\`${spec.skill}\` is not a usable skill name: it becomes a directory under \`.claude/skills/\``,
      ),
    );
  }

  return out;
}
