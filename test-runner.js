/**
 * `npm test` — run the suite, with a display if one is needed and missing.
 *
 * `vscode-test` downloads and launches a real VS Code. On a headless Linux box
 * that dies with `Missing X server or $DISPLAY` and then SIGSEGV, which is what
 * CI hit: the shared `standard-ci.yml` runs `npm test` directly, and it is a
 * hub-seeded thin caller we do not edit. So the wrapper lives here instead —
 * `npm test` is now correct on a developer's Mac, in a Linux desktop session,
 * and on a bare runner alike, without every caller having to know about xvfb.
 *
 * Set ZER0_CMS_NO_XVFB=1 to force the plain path.
 */

const { spawnSync } = require('node:child_process');

const args = process.argv.slice(2);
const bin = process.platform === 'win32' ? 'vscode-test.cmd' : 'vscode-test';

/** Whether this process could talk to an X server if it tried. */
function hasDisplay() {
  return process.platform !== 'linux' || Boolean(process.env.DISPLAY || process.env.WAYLAND_DISPLAY);
}

/** Whether `xvfb-run` is on PATH — present by default on GitHub's Linux runners. */
function hasXvfb() {
  return spawnSync('xvfb-run', ['--help'], { stdio: 'ignore' }).status === 0;
}

let command = bin;
let commandArgs = args;

if (!hasDisplay() && !process.env.ZER0_CMS_NO_XVFB) {
  if (hasXvfb()) {
    // -a picks a free server number instead of failing on a collision.
    command = 'xvfb-run';
    commandArgs = ['-a', bin, ...args];
  } else {
    console.error(
      'zer0-CMS: no DISPLAY and no xvfb-run on PATH. The integration tests launch a real\n' +
        'VS Code and need one of the two. On Debian/Ubuntu: sudo apt-get install -y xvfb',
    );
    process.exit(1);
  }
}

const result = spawnSync(command, commandArgs, {
  stdio: 'inherit',
  shell: process.platform === 'win32',
  env: process.env,
});

if (result.error) {
  console.error(`zer0-CMS: could not start ${command} — ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
