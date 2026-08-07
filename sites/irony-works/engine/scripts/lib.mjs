// Irony Works engine library — harness, config, guardrails.
import { readFileSync, appendFileSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
const yaml = createRequire(import.meta.url)("js-yaml"); // installed in-workflow: npm i js-yaml --no-save

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const cfg = yaml.load(readFileSync(join(ROOT, "engine", "seed.config.yml"), "utf8"));
export const root = (...p) => join(ROOT, ...p);

// ---------- guardrails: the engine's entire writable filesystem ----------
export function assertWritable(relPath) {
  const ok = (cfg.guardrails?.writable ?? []).some((w) =>
    w.endsWith("/") ? relPath.startsWith(w) : relPath === w
  );
  if (!ok) throw new Error(`GUARDRAIL: engine may not write "${relPath}". ${cfg.guardrails?.immutable_reason ?? ""}`);
  return relPath;
}
export function writeVaultFile(relPath, content) {
  assertWritable(relPath);
  mkdirSync(dirname(root(relPath)), { recursive: true });
  writeFileSync(root(relPath), content, "utf8");
}
export function appendCompost(row) {
  const rel = cfg.gate.compost;
  assertWritable(rel);
  appendFileSync(root(rel), row.endsWith("\n") ? row : row + "\n", "utf8");
}

// ---------- prompts ----------
export const prompt = (name) => readFileSync(root("engine", "prompts", `${name}.md`), "utf8");

// ---------- harness ----------
// Default wire: the Claude Code CLI, which carries its own OAuth credentials
// (keychain locally, CLAUDE_CODE_OAUTH_TOKEN in CI). Fallback: the Anthropic
// API with ANTHROPIC_API_KEY. Prompts are the contract; the wire is a detail.
function claudeCodeAvailable() {
  try { execFileSync("claude", ["--version"], { stdio: "ignore" }); return true; } catch { return false; }
}

function harnessClaudeCode(system, user, h) {
  return execFileSync(
    "claude",
    ["-p", "--model", h.model ?? "claude-sonnet-4-6", "--append-system-prompt", system],
    { input: user, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 }
  ).trim();
}

async function harnessAnthropicAPI(system, user, h) {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) throw new Error("no harness available: claude CLI not found and ANTHROPIC_API_KEY is not set");
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({
      model: h.model ?? "claude-sonnet-4-6",
      max_tokens: h.max_tokens ?? 4000,
      system,
      messages: [{ role: "user", content: user }],
    }),
  });
  if (!res.ok) throw new Error(`harness ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return data.content.filter((b) => b.type === "text").map((b) => b.text).join("\n");
}

export async function harness(system, user) {
  const h = cfg.harness ?? {};
  if (h.provider === "lifehacker") {
    // HARNESS ADAPTER — lifehacker.dev
    // Point at the lifehacker.dev endpoint; prompts flow through unchanged.
    // const res = await fetch(h.endpoint, { method: "POST",
    //   headers: { "content-type": "application/json",
    //              authorization: `Bearer ${process.env[h.auth_env]}` },
    //   body: JSON.stringify({ system, prompt: user, model: h.model }) });
    // return (await res.json()).text;
    throw new Error("lifehacker harness adapter not configured — see engine/README.md");
  }
  if (h.provider === "anthropic") return harnessAnthropicAPI(system, user, h);
  // default: claude-code, falling back to the API key if the CLI is missing or can't auth
  if (claudeCodeAvailable()) {
    try {
      return harnessClaudeCode(system, user, h);
    } catch (e) {
      if (!process.env.ANTHROPIC_API_KEY) throw e;
      console.error(`claude CLI failed (${String(e.message).split("\n")[0]}); falling back to ANTHROPIC_API_KEY`);
    }
  }
  return harnessAnthropicAPI(system, user, h);
}

// ---------- helpers ----------
export const parseJSON = (text) => JSON.parse(text.replace(/```json|```/g, "").trim());
export const slugify = (s) =>
  s.toLowerCase().replace(/['".:,!?()]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
export const today = () => new Date().toISOString().slice(0, 10);
