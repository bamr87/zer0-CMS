#!/usr/bin/env node
// Vault → Jekyll collection for zer0-mistakes publishing.
// Resolves [[wikilinks]] to permalinks *labelled with the target's title*,
// de-duplicates the H1 the layout already renders, and derives the frontmatter
// the theme and search engines expect. Writes vault/* into _entries/.
import { readdirSync, readFileSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { createRequire } from "node:module";
import { root, slugify } from "./lib.mjs";

const yaml = createRequire(import.meta.url)("js-yaml");
const config = yaml.load(readFileSync(root("_config.yml"), "utf8"));
const base = (config.baseurl ?? "").replace(/\/$/, "");

const OUT = root("_entries");
mkdirSync(OUT, { recursive: true });

// ---------- pass 1: read every note, parse frontmatter, build the title index ----------
const notes = [];
const skip = new Set(["templates"]);
for (const dir of readdirSync(root("vault"))) {
  const full = root("vault", dir);
  if (!statSync(full).isDirectory()) {
    if (dir.endsWith(".md")) notes.push({ dir: "", file: dir });
    continue;
  }
  if (skip.has(dir) || dir.startsWith(".")) continue;
  for (const f of readdirSync(full).filter((f) => f.endsWith(".md"))) notes.push({ dir, file: f });
}

const splitFrontmatter = (src) => {
  const m = src.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!m) return { data: {}, body: src };
  let data = {};
  try { data = yaml.load(m[1]) ?? {}; } catch { data = {}; }
  return { data, body: m[2] };
};

const bySlug = new Map();   // slug -> note
const index = new Map();    // lowercased title OR slug -> slug
for (const n of notes) {
  const src = readFileSync(root("vault", n.dir, n.file), "utf8");
  const { data, body } = splitFrontmatter(src);
  n.slug = n.file.replace(/\.md$/, "");
  n.data = data;
  n.body = body;
  n.title = String(data.title ?? n.slug);
  index.set(n.title.toLowerCase(), n.slug);
  index.set(n.slug.toLowerCase(), n.slug);
  bySlug.set(n.slug, n);
}

// ---------- helpers ----------
const isHome = (n) => n.slug === "Home";
const hrefFor = (slug) => (slug === "Home" ? `${base}/` : `${base}/entries/${slug.toLowerCase()}/`);

// A bare [[target]] used to render as its raw slug ("the-kodak-moment"). Label it
// with the target's real title instead; explicit [[target|label]] always wins.
const link = (target, label) => {
  const key = target.trim().toLowerCase();
  const slug = index.get(key) ?? slugify(target);
  const text = label ?? bySlug.get(slug)?.title ?? target;
  return `[${text}](${hrefFor(slug)})`;
};

const oneLine = (s) => String(s ?? "").replace(/\s+/g, " ").trim();
const clip = (s, n = 155) => (s.length <= n ? s : s.slice(0, s.lastIndexOf(" ", n)).trim() + "…");

// Reduce Markdown to plain prose for the description: drop callouts, quotes and
// headings, unwrap [text](url) to text, then strip emphasis markers only —
// never a bare hyphen, which lives inside slugs and prose alike.
const plainProse = (md) =>
  oneLine(
    md
      .replace(/^\s*>.*$/gm, "")
      .replace(/^\s*#{1,6}\s.*$/gm, "")
      .replace(/```[\s\S]*?```/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/[*_`]/g, "")
  );

// ---------- pass 2: rewrite and emit ----------
let count = 0;
for (const n of notes) {
  let body = n.body
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, (_, t, l) => link(t, l))
    .replace(/\[\[([^\]]+)\]\]/g, (_, t) => link(t));

  // The layout already prints the title as the page H1 — drop the body's leading
  // H1 so entries don't render the same heading twice.
  body = body.replace(/^\s*#\s+.+?\r?\n+/, "");

  const fm = { ...n.data };
  fm.title = isHome(n) ? "Irony Works" : n.title;
  fm.layout = fm.layout ?? "default";
  if (isHome(n)) fm.permalink = "/";

  // Section drives the browse page's grouping.
  fm.section = n.dir || "root";

  // Search engines and the theme's cards both want a description; the
  // expectation is the best one-line summary an entry already contains.
  if (!fm.description) {
    const summary = oneLine(fm.expectation) || plainProse(body);
    if (summary) fm.description = clip(summary);
  }

  // `planted` is the vault's word for a publication date.
  if (!fm.date && fm.planted) fm.date = fm.planted;

  const out = `---\n${yaml.dump(fm, { lineWidth: 100, noRefs: true }).trimEnd()}\n---\n\n${body.trimStart()}`;
  writeFileSync(join(OUT, `${n.slug}.md`), out, "utf8");
  count++;
}
console.log(`Transplanted ${count} notes → _entries/`);
