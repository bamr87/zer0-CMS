#!/usr/bin/env node
// Vault → Jekyll collection for zer0-mistakes publishing.
// Converts [[wikilinks]] to permalinks; writes vault/* into _entries/.
import { readdirSync, readFileSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { root, slugify } from "./lib.mjs";

const OUT = root("_entries");
mkdirSync(OUT, { recursive: true });

// Pass 1 — index every note's title → slug.
const notes = [];
const skip = new Set(["templates"]);
for (const dir of readdirSync(root("vault"))) {
  const full = root("vault", dir);
  if (!statSync(full).isDirectory()) { if (dir.endsWith(".md")) notes.push({ dir: "", file: dir }); continue; }
  if (skip.has(dir)) continue;
  for (const f of readdirSync(full).filter((f) => f.endsWith(".md"))) notes.push({ dir, file: f });
}
const index = new Map();
for (const n of notes) {
  const src = readFileSync(root("vault", n.dir, n.file), "utf8");
  const title = src.match(/^title:\s*"?(.+?)"?\s*$/m)?.[1] ?? n.file.replace(/\.md$/, "");
  const slug = n.file.replace(/\.md$/, "");
  index.set(title.toLowerCase(), slug);
  index.set(slug.toLowerCase(), slug);
  n.src = src; n.slug = slug;
}

// Pass 2 — rewrite wikilinks and emit.
const link = (target, label) => {
  const slug = index.get(target.trim().toLowerCase()) ?? slugify(target);
  return `[${label ?? target}](/entries/${slug}/)`;
};
for (const n of notes) {
  const out = n.src
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, (_, t, l) => link(t, l))
    .replace(/\[\[([^\]]+)\]\]/g, (_, t) => link(t));
  writeFileSync(join(OUT, `${n.slug}.md`), out, "utf8");
}
console.log(`Transplanted ${notes.length} notes → _entries/`);
