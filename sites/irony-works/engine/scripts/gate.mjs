#!/usr/bin/env node
// Standalone Alanis Gate for PR checks: scores changed vault entries.
// Usage: node engine/scripts/gate.mjs file1.md file2.md ...
import { readFileSync } from "node:fs";
import { cfg, prompt, harness, parseJSON } from "./lib.mjs";

const files = process.argv.slice(2).filter((f) => f.endsWith(".md"));
if (!files.length) { console.log("No entry files to gate."); process.exit(0); }

const rows = ["| Entry | Score | Verdict | Reason |", "|---|---|---|---|"];
for (const f of files) {
  try {
    const v = parseJSON(await harness(prompt("alanis-gate"),
      `Candidate entry (full file, score the frontmatter expectation/reversal against the body):\n\n${readFileSync(f, "utf8")}\nThreshold: ${cfg.gate.threshold}`, "alanis-gate-pr"));
    rows.push(`| \`${f}\` | ${v.score}/10 | ${v.verdict} | ${v.reason} |`);
  } catch (e) {
    rows.push(`| \`${f}\` | — | UNGATED | ${String(e.message).slice(0, 120)} |`);
  }
}
console.log(["## 🚪 Alanis Gate report", "", ...rows, "", "_Advisory: the gate scores; humans merge._"].join("\n"));
