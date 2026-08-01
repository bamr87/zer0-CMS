/**
 * The bundled MCP server, exercised the way a client exercises it.
 *
 * These tests spawn `dist/mcp-server.js` — the **shipped** artifact, not the
 * sources — with nothing but a `cwd`, and speak newline-delimited JSON-RPC to
 * it over stdio. That is the whole contract: an MCP client hands the server a
 * working directory and a pipe, and everything else has to come from disk.
 *
 * Three sessions are scripted in `suiteSetup`, because the interesting
 * properties are about a *session* rather than a single frame:
 *
 *   A. publish disabled (the default) — the full frame vocabulary, plus a
 *      garbage line in the middle to prove the loop survives it.
 *   B. publish enabled via `ZER0_CMS_MCP_ALLOW_PUBLISH=1` — so the two publish
 *      gates can be shown to refuse *independently*, with different prose.
 *   C. a stubbed handler that throws — see `runBoomSession` for why this one
 *      session runs the `out/` build instead of the bundle.
 *
 * Every child gets a scrubbed environment: every `ZER0_*` and `ANTHROPIC_*`
 * variable is dropped, so a developer who has the publish flag exported in
 * their shell still sees the same result as CI.
 */

import * as assert from 'assert';
import { spawn, spawnSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

const REPO_ROOT = path.resolve(__dirname, '../..');
const SERVER = path.join(REPO_ROOT, 'dist', 'mcp-server.js');
const OUT_MCP = path.resolve(__dirname, '../mcp');
const WORKSPACE = path.join(REPO_ROOT, 'src', 'test', 'fixtures', 'workspace');

const PUBLISH_ENV_VAR = 'ZER0_CMS_MCP_ALLOW_PUBLISH';

/** The eight tools, in the order `tools/list` must report them. */
const EXPECTED_TOOLS = [
  'zer0_status',
  'zer0_list_content',
  'zer0_get_content',
  'zer0_preview',
  'zer0_draft',
  'zer0_publish',
  'zer0_worklist',
  'zer0_contract',
];

// ---------------------------------------------------------------------------
// Wire shapes
// ---------------------------------------------------------------------------

interface ToolResult {
  content?: Array<{ type: string; text: string }>;
  isError?: boolean;
}

interface RpcResponse {
  jsonrpc?: string;
  id?: number;
  result?: ToolResult & {
    protocolVersion?: string;
    tools?: Array<{ name: string; description?: string; inputSchema?: unknown }>;
  };
  error?: { code: number; message: string };
}

interface SessionResult {
  /** Non-empty stdout lines, in order. */
  stdout: string[];
  stderr: string;
  code: number | null;
  responses: RpcResponse[];
}

/** A frame to write: an object is stringified, a string is sent verbatim. */
type Frame = Record<string, unknown> | string;

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

/**
 * The environment every spawned server gets.
 *
 * `ELECTRON_RUN_AS_NODE` is set deliberately. This suite runs inside the
 * extension host, where `process.execPath` is VS Code's Electron binary rather
 * than a node binary; that variable is what makes it behave as node. Outside
 * the host — a plain `mocha out/test/mcp.test.js` — node has no such feature
 * and ignores the variable, so setting it unconditionally is safe.
 */
function childEnv(extra: Record<string, string> = {}): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined || key.startsWith('ZER0_') || key.startsWith('ANTHROPIC_')) {
      continue;
    }
    env[key] = value;
  }
  env.ELECTRON_RUN_AS_NODE = '1';
  for (const [key, value] of Object.entries(extra)) {
    env[key] = value;
  }
  return env;
}

/**
 * `npm run pretest` builds the bundle, but a bare `mocha out/test` does not.
 * Build it rather than fail with a confusing ENOENT out of `spawn`.
 */
function ensureServerBuilt(): void {
  if (fs.existsSync(SERVER)) {
    return;
  }
  const built = spawnSync(process.execPath, ['esbuild.js'], {
    cwd: REPO_ROOT,
    env: childEnv(),
    encoding: 'utf8',
  });
  assert.strictEqual(
    built.status,
    0,
    `could not build ${SERVER}: ${built.stderr || built.error?.message || 'unknown failure'}`,
  );
  assert.ok(fs.existsSync(SERVER), `esbuild reported success but ${SERVER} is missing`);
}

/** Write every frame, close stdin, and collect what came back. */
function runSession(
  script: string,
  frames: readonly Frame[],
  extraEnv: Record<string, string> = {},
): Promise<SessionResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script], { cwd: WORKSPACE, env: childEnv(extraEnv) });
    let out = '';
    let err = '';
    child.stdout.on('data', (chunk: Buffer) => {
      out += chunk.toString('utf8');
    });
    child.stderr.on('data', (chunk: Buffer) => {
      err += chunk.toString('utf8');
    });
    child.on('error', reject);
    child.on('close', (code) => {
      const stdout = out.split('\n').filter((line) => line.trim() !== '');
      const responses: RpcResponse[] = [];
      for (const line of stdout) {
        // A non-JSON line is a failure the `pure NDJSON` test reports with the
        // offending text; do not let it take the whole suite down here.
        try {
          responses.push(JSON.parse(line) as RpcResponse);
        } catch {
          responses.push({});
        }
      }
      resolve({ stdout, stderr: err, code, responses });
    });
    for (const frame of frames) {
      child.stdin.write(`${typeof frame === 'string' ? frame : JSON.stringify(frame)}\n`);
    }
    child.stdin.end();
  });
}

function byId(session: SessionResult, id: number): RpcResponse | undefined {
  return session.responses.find((response) => response.id === id);
}

function textOf(response: RpcResponse | undefined): string {
  return response?.result?.content?.[0]?.text ?? '';
}

/**
 * Session C: prove that an exception *inside a tool handler* is answered with
 * `isError: true` instead of ending the session.
 *
 * No argument reaches that catch through the front door — every handler in
 * `tools.ts` is defensive, which is the point of them, and a fuzz of hostile
 * `zer0.json` shapes against all eight produced no throw. So the throw is
 * injected: a generated harness requires `out/mcp/tools.js`, adds one
 * deliberately-throwing tool to `TOOLS_BY_NAME`, and only then requires
 * `out/mcp/server.js`, whose `await import('./tools.js')` resolves through the
 * same module cache and therefore sees the stub.
 *
 * This is the one session that runs the `out/` build rather than the bundle,
 * because a bundle has no module boundary to reach into. Both are compiled
 * from the same `src/mcp/server.ts`, and the code under test — `callTool`'s
 * try/catch — is identical in each.
 */
async function runBoomSession(frames: readonly Frame[]): Promise<SessionResult> {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zer0-cms-mcp-'));
  const harness = [
    `const tools = require(${JSON.stringify(path.join(OUT_MCP, 'tools.js'))});`,
    "tools.TOOLS_BY_NAME.set('zer0_boom', {",
    "  name: 'zer0_boom',",
    "  description: 'a stub that throws, injected by mcp.test.ts',",
    "  inputSchema: { type: 'object', properties: {} },",
    "  handler: () => { throw new TypeError('boom from a stubbed handler'); },",
    '});',
    `require(${JSON.stringify(path.join(OUT_MCP, 'server.js'))});`,
    '',
  ].join('\n');
  const harnessPath = path.join(dir, 'boom-harness.js');
  fs.writeFileSync(harnessPath, harness, 'utf8');
  try {
    return await runSession(harnessPath, frames);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------------
// Session A — the default posture: publish disabled
// ---------------------------------------------------------------------------

suite('mcp: a scripted stdio session against the shipped server', function () {
  this.timeout(60000);

  let session: SessionResult;

  suiteSetup(async () => {
    ensureServerBuilt();
    session = await runSession(SERVER, [
      {
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
          // Deliberately not the server's own default (2025-06-18): echoing
          // this back is only evidence of an echo if it differs.
          protocolVersion: '2025-03-26',
          capabilities: {},
          clientInfo: { name: 'zer0-cms-test', version: '0' },
        },
      },
      { jsonrpc: '2.0', method: 'notifications/initialized' },
      { jsonrpc: '2.0', id: 2, method: 'tools/list' },
      'this is not json {{{',
      { jsonrpc: '2.0', id: 3, method: 'ping' },
      { jsonrpc: '2.0', id: 4, method: 'no/such/method' },
      { jsonrpc: '2.0', id: 5, method: 'tools/call', params: { name: 'zer0_no_such_tool', arguments: {} } },
      { jsonrpc: '2.0', id: 6, method: 'tools/call', params: { name: 'zer0_publish', arguments: { confirm: true } } },
      { jsonrpc: '2.0', id: 7, method: 'tools/call', params: { name: 'zer0_status', arguments: {} } },
      { jsonrpc: '2.0', method: 'notifications/cancelled', params: { requestId: 7 } },
      // Last, so a pass means every frame above left the loop alive.
      { jsonrpc: '2.0', id: 8, method: 'ping' },
    ]);
  });

  test('stdout is pure NDJSON and the banner goes to stderr', () => {
    assert.ok(session.stdout.length > 0, 'the server wrote nothing at all');
    for (const line of session.stdout) {
      let parsed: unknown;
      assert.doesNotThrow(() => {
        parsed = JSON.parse(line);
      }, `non-JSON on the protocol channel: ${line.slice(0, 120)}`);
      assert.ok(
        typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed),
        `not a JSON-RPC object: ${line.slice(0, 120)}`,
      );
      assert.strictEqual((parsed as RpcResponse).jsonrpc, '2.0', 'every frame is tagged jsonrpc 2.0');
    }
    assert.ok(session.stderr.includes('[zer0-cms] ready'), `banner missing from stderr: ${session.stderr}`);
    assert.ok(session.stderr.includes('publish disabled'), 'the banner reports the publish gate');
    assert.ok(!session.stdout.some((line) => line.includes('[zer0-cms] ready')), 'the banner never reaches stdout');
  });

  test('the session ends cleanly when stdin closes', () => {
    assert.strictEqual(session.code, 0, `server exited ${session.code}; stderr: ${session.stderr}`);
  });

  test('initialize echoes the protocol version the client asked for', () => {
    assert.strictEqual(byId(session, 1)?.result?.protocolVersion, '2025-03-26');
  });

  test('tools/list reports exactly the eight tools, in order', () => {
    const tools = byId(session, 2)?.result?.tools ?? [];
    assert.deepStrictEqual(
      tools.map((tool) => tool.name),
      EXPECTED_TOOLS,
    );
    for (const tool of tools) {
      assert.ok((tool.description ?? '').length > 0, `${tool.name} has no description`);
      assert.ok(tool.inputSchema !== undefined, `${tool.name} has no inputSchema`);
    }
  });

  test('a garbage line does not kill the loop', () => {
    assert.deepStrictEqual(byId(session, 3)?.result, {}, 'ping right after the garbage line');
    assert.deepStrictEqual(byId(session, 8)?.result, {}, 'ping after every other frame');
  });

  test('an unknown method is -32601', () => {
    const response = byId(session, 4);
    assert.strictEqual(response?.error?.code, -32601);
    assert.ok(response?.error?.message.includes('no/such/method'), 'the error names the method');
    assert.strictEqual(response?.result, undefined, 'an error frame carries no result');
  });

  test('an unknown tool is -32602', () => {
    const response = byId(session, 5);
    assert.strictEqual(response?.error?.code, -32602);
    assert.ok(response?.error?.message.includes('zer0_no_such_tool'), 'the error names the tool');
  });

  test('a notification draws no response at all', () => {
    // Two notifications went in (`initialized` and `cancelled`); eight frames
    // carried an id. Exactly eight answers came back, and none of them is
    // missing an id — a notification is neither answered nor mis-answered.
    assert.strictEqual(session.responses.length, 8, `unexpected frames: ${session.stdout.join(' | ')}`);
    for (const response of session.responses) {
      assert.ok(typeof response.id === 'number', `a response with no id: ${JSON.stringify(response)}`);
    }
  });

  test('a read-only tool answers and reports the publish gate as off', () => {
    const status = byId(session, 7);
    assert.strictEqual(status?.result?.isError, false, textOf(status));
    const text = textOf(status);
    assert.ok(text.includes('workspace   :'), text.slice(0, 200));
    assert.ok(text.includes('publish tool enabled: false'), 'zer0_status reports the gate');
  });

  // --- gate one: the environment -------------------------------------------

  test('zer0_publish refuses on the environment gate, even with confirm=true', () => {
    const publish = byId(session, 6);
    const text = textOf(publish);
    assert.strictEqual(publish?.result?.isError, true, text);
    assert.ok(text.startsWith('publishing is disabled'), text.slice(0, 120));
    assert.ok(text.includes(PUBLISH_ENV_VAR), 'the refusal names the variable to set');
    // The call passed confirm=true, so this can only be the environment gate.
    assert.ok(!text.includes('confirm=true to publish'), 'this is not the confirm refusal');
  });
});

// ---------------------------------------------------------------------------
// Session B — the environment gate opened, the call gate still shut
// ---------------------------------------------------------------------------

suite('mcp: the second publish gate refuses on its own', function () {
  this.timeout(60000);

  let session: SessionResult;

  suiteSetup(async () => {
    ensureServerBuilt();
    session = await runSession(
      SERVER,
      [
        { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'zer0_publish', arguments: {} } },
        { jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'zer0_status', arguments: {} } },
        { jsonrpc: '2.0', id: 3, method: 'ping' },
      ],
      { [PUBLISH_ENV_VAR]: '1' },
    );
  });

  test('the banner reports the opened gate', () => {
    assert.ok(session.stderr.includes('publish ENABLED'), session.stderr);
  });

  test('zer0_publish still refuses, with different prose, when confirm is absent', () => {
    const publish = byId(session, 1);
    const text = textOf(publish);
    assert.strictEqual(publish?.result?.isError, true, text);
    assert.ok(text.startsWith('refused: pass confirm=true'), text.slice(0, 120));
    // The two gates are independent and say so: this refusal is not the other
    // refusal with the variable name swapped out.
    assert.ok(!text.includes('publishing is disabled'), 'the two refusals are distinct');
    assert.ok(!text.includes(PUBLISH_ENV_VAR), 'the environment gate is already satisfied');
    assert.ok(text.includes('zer0_preview'), 'the refusal names the safe alternative');
  });

  test('zer0_status agrees that the environment gate is open', () => {
    assert.ok(textOf(byId(session, 2)).includes('publish tool enabled: true'));
  });

  test('the session survives a refusal', () => {
    assert.deepStrictEqual(byId(session, 3)?.result, {});
    assert.strictEqual(session.code, 0);
  });
});

// ---------------------------------------------------------------------------
// Session C — a handler that throws
// ---------------------------------------------------------------------------

suite('mcp: a throwing handler is a flagged result, not a dead server', function () {
  this.timeout(60000);

  let session: SessionResult;

  suiteSetup(async () => {
    session = await runBoomSession([
      { jsonrpc: '2.0', id: 1, method: 'tools/list' },
      { jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'zer0_boom', arguments: {} } },
      { jsonrpc: '2.0', id: 3, method: 'ping' },
    ]);
  });

  test('the exception comes back as isError with the type and message', () => {
    const boom = byId(session, 2);
    const text = textOf(boom);
    assert.strictEqual(boom?.result?.isError, true, text);
    assert.ok(text.startsWith('tool error:'), text.slice(0, 120));
    assert.ok(text.includes('TypeError'), 'the error class survives');
    assert.ok(text.includes('boom from a stubbed handler'), 'the message survives');
    assert.strictEqual(boom?.error, undefined, 'a handler bug is a result, not a protocol error');
  });

  test('the process is still alive afterwards and still pure NDJSON', () => {
    assert.deepStrictEqual(byId(session, 3)?.result, {}, 'ping after the throw');
    assert.strictEqual(session.code, 0, `server exited ${session.code}; stderr: ${session.stderr}`);
    for (const line of session.stdout) {
      assert.doesNotThrow(() => JSON.parse(line), `non-JSON on stdout: ${line.slice(0, 120)}`);
    }
  });

  test('the stub did not disturb the advertised tool list', () => {
    assert.deepStrictEqual(
      (byId(session, 1)?.result?.tools ?? []).map((tool) => tool.name),
      EXPECTED_TOOLS,
    );
  });
});
