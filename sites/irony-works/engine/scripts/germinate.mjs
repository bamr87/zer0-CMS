#!/usr/bin/env node
// One germination cycle: scout → scribe → gate → nursery + compost.
// Usage: node engine/scripts/germinate.mjs [batch]
import { readdirSync, readFileSync } from "node:fs";
import { cfg, root, prompt, harness, parseJSON, slugify, today, writeVaultFile, appendCompost } from "./lib.mjs";

const batch = Number(process.argv[2] ?? cfg.batch ?? 3);
const cycle = Number(process.env.GITHUB_RUN_NUMBER ?? 0);
const domain = cfg.domains[cycle % cfg.domains.length];

// Existing titles, for dedupe and for the Linker's index.
const existing = [];
for (const dir of ["forms", "works", "figures", "instances", "mirrors", "futures", "nursery"]) {
  for (const f of readdirSync(root("vault", dir)).filter((f) => f.endsWith(".md"))) {
    const head = readFileSync(root("vault", dir, f), "utf8").slice(0, 400);
    existing.push(head.match(/^title:\s*"?(.+?)"?\s*$/m)?.[1] ?? f.replace(/\.md$/, ""));
  }
}

console.log(`Cycle ${cycle} · domain: ${domain} · batch: ${batch}\n`);

const candidates = parseJSON(
  await harness(prompt("scout"), `DOMAIN: ${domain}\nBATCH: ${batch}\nEXISTING:\n${existing.join("\n")}`, "scout")
);

const summary = [];
for (const c of candidates.slice(0, batch)) {
  const verdictRaw = await harness(
    prompt("alanis-gate"),
    `Candidate:\n${JSON.stringify(c, null, 2)}\nThreshold: ${cfg.gate.threshold}`,
    "alanis-gate"
  );
  const v = parseJSON(verdictRaw);

  if (v.score >= cfg.gate.threshold && v.verdict === "PASS") {
    let entry = await harness(prompt("scribe"), `Candidate:\n${JSON.stringify(c, null, 2)}\nGate: ${JSON.stringify(v)}\nEXISTING titles for Rhymes-with links:\n${existing.join("\n")}\nToday: ${today()}`, "scribe");
    entry = entry.replace(/^```(markdown)?\n?|```$/g, "");
    const rel = `vault/nursery/${slugify(c.title)}.md`;
    writeVaultFile(rel, entry);
    summary.push(`🌱 PASS ${v.score}/10 — ${c.title} → ${rel}`);
  } else {
    appendCompost(`| ${today()} | ${c.title} | ${v.score}/10 | ${v.verdict} | ${v.reason} |`);
    summary.push(`🍂 ${v.verdict} ${v.score}/10 — ${c.title} (composted: ${v.reason})`);
  }
}

const report = summary.join("\n");
console.log("\n" + report);
if (process.env.GITHUB_OUTPUT) {
  const fs = await import("node:fs");
  fs.appendFileSync(process.env.GITHUB_OUTPUT, `report<<EOM\n${report}\nEOM\ndomain=${domain}\n`);
}
