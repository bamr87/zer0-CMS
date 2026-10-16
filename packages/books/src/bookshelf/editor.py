"""The studio's single-page editor.

One self-contained HTML document: no bundler, no CDN, no external assets. It
talks to the JSON API in ``server.py`` and edits the markdown on disk directly.

Colour comes from the same reference palette as the dashboard, so the two
surfaces read as one product. The editor adds no chart colours -- only the
sequential blue accent and the reserved status palette for validation state.
"""

from __future__ import annotations

_STYLE = """
:root {
  color-scheme: light;
  --plane: #f9f9f7;
  --surface: #fcfcfb;
  --sunken: #f2f1ec;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --rule: #e1e0d9;
  --border: rgba(11, 11, 11, 0.10);
  --accent: #2a78d6;
  --accent-soft: #9ec5f4;
  --good: #0ca30c;
  --warning: #fab219;
  --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --plane: #0d0d0d;
    --surface: #1a1a19;
    --sunken: #141413;
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --rule: #2c2c2a;
    --border: rgba(255, 255, 255, 0.10);
    --accent: #3987e5;
    --accent-soft: #184f95;
  }
}

* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  background: var(--plane);
  color: var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.5;
  overflow: hidden;
}
button, input, select, textarea { font: inherit; color: inherit; }

#app {
  display: grid;
  grid-template-columns: 15rem minmax(0, 1fr) 23rem;
  grid-template-rows: 100vh;
}
@media (max-width: 60rem) {
  body { overflow: auto; }
  #app { grid-template-columns: 1fr; grid-template-rows: auto auto auto; }
}

aside, main, section.panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
aside { background: var(--sunken); border-right: 1px solid var(--border); }
section.panel { background: var(--sunken); border-left: 1px solid var(--border); }

.bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 0.85rem;
  border-bottom: 1px solid var(--border);
  min-height: 2.9rem;
  flex: none;
}
.bar h1 { font-size: 0.9375rem; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
.bar .spacer { flex: 1; }
.scroll { overflow-y: auto; flex: 1; padding: 0.5rem; }

button {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  padding: 0.25rem 0.6rem;
  cursor: pointer;
  white-space: nowrap;
}
button:hover:not(:disabled) { border-color: var(--accent); }
button:disabled { opacity: 0.45; cursor: default; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.ghost { background: none; border-color: transparent; color: var(--ink-2); }
button.ghost:hover { background: var(--surface); }

.book { margin-bottom: 0.35rem; }
.book > summary {
  list-style: none;
  cursor: pointer;
  padding: 0.35rem 0.5rem;
  border-radius: 0.375rem;
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
}
.book > summary::-webkit-details-marker { display: none; }
.book > summary:hover { background: var(--surface); }
.book .name { font-weight: 600; font-size: 0.875rem; }
.book .count { color: var(--muted); font-size: 0.75rem; margin-left: auto; font-variant-numeric: tabular-nums; }
.chapters { list-style: none; margin: 0.15rem 0 0.4rem; padding: 0; }
.chapters li a {
  display: flex;
  gap: 0.45rem;
  padding: 0.22rem 0.5rem 0.22rem 1.1rem;
  border-radius: 0.375rem;
  color: var(--ink-2);
  text-decoration: none;
  font-size: 0.8125rem;
}
.chapters li a:hover { background: var(--surface); color: var(--ink); }
.chapters li a.active { background: var(--accent); color: #fff; }
.chapters .num { font-variant-numeric: tabular-nums; opacity: 0.75; min-width: 1.4rem; }
.chapters .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0.5rem 0.85rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex: none;
}
.meta label { display: flex; align-items: center; gap: 0.3rem; font-size: 0.75rem; color: var(--muted); }
.meta input, .meta select {
  background: var(--plane);
  border: 1px solid var(--border);
  border-radius: 0.3rem;
  padding: 0.12rem 0.35rem;
  font-size: 0.8125rem;
}
.meta input.title { min-width: 14rem; font-weight: 600; }
.meta input.num { width: 3rem; text-align: right; font-variant-numeric: tabular-nums; }

#body {
  flex: 1;
  width: 100%;
  border: 0;
  resize: none;
  padding: 1.5rem clamp(1rem, 6vw, 5rem);
  background: var(--surface);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.875rem;
  line-height: 1.75;
  tab-size: 2;
}
#body:focus { outline: none; }

.status {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.35rem 0.85rem;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.75rem;
  background: var(--surface);
  flex: none;
}
.status .num { font-variant-numeric: tabular-nums; }

.tabs { display: flex; gap: 0.25rem; padding: 0.5rem 0.5rem 0; flex: none; }
.tabs button { border-radius: 0.375rem 0.375rem 0 0; border-bottom-color: transparent; }
.tabs button[aria-selected="true"] { background: var(--surface); color: var(--ink); border-color: var(--border); }

.field { padding: 0.5rem; }
.field textarea {
  width: 100%;
  min-height: 4.5rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  padding: 0.45rem 0.55rem;
  resize: vertical;
  font-size: 0.8125rem;
}
.actions { display: flex; flex-wrap: wrap; gap: 0.3rem; padding: 0 0.5rem 0.5rem; }

#out {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  padding: 0.6rem 0.7rem;
  font-size: 0.8125rem;
  min-height: 3rem;
  margin: 0 0.5rem;
}

.finding {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  padding: 0.5rem 0.6rem;
  margin-bottom: 0.4rem;
  font-size: 0.8125rem;
}
.finding .head { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.2rem; }
.finding .kind { color: var(--muted); font-size: 0.75rem; }
.finding blockquote {
  margin: 0.3rem 0;
  padding-left: 0.5rem;
  border-left: 2px solid var(--accent-soft);
  color: var(--ink-2);
  font-style: italic;
}
.finding .fix { color: var(--ink-2); }
.dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; flex: none; }
.dot.good { background: var(--good); }
.dot.warning { background: var(--warning); }
.dot.critical { background: var(--critical); }
.loc { color: var(--muted); font-size: 0.75rem; font-family: ui-monospace, monospace; }

.empty { color: var(--muted); font-style: italic; padding: 0.5rem; font-size: 0.8125rem; }
.err { color: var(--critical); }
dialog {
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  background: var(--surface);
  color: var(--ink);
  padding: 1rem;
  min-width: 20rem;
}
dialog::backdrop { background: rgba(0, 0, 0, 0.4); }
dialog label { display: block; margin-bottom: 0.5rem; font-size: 0.8125rem; }
dialog input { width: 100%; padding: 0.3rem 0.4rem; border: 1px solid var(--border);
  border-radius: 0.3rem; background: var(--plane); margin-top: 0.15rem; }
"""

_BODY = """
<div id="app">
  <aside>
    <div class="bar">
      <h1>Bookshelf</h1>
      <span class="spacer"></span>
      <button class="ghost" id="new-book" title="Start a new book">+ Book</button>
    </div>
    <div class="scroll" id="library"><p class="empty">Loading…</p></div>
  </aside>

  <main>
    <div class="meta" id="meta" hidden>
      <label>Title <input class="title" id="m-title"></label>
      <label>#<input class="num" id="m-number" type="number" min="1"></label>
      <label>Act <input class="num" id="m-act" type="number" min="1"></label>
      <label>Status
        <select id="m-status">
          <option>stub</option><option>outline</option><option>draft</option>
          <option>revised</option><option>final</option>
        </select>
      </label>
      <label>POV <input id="m-pov"></label>
      <span class="spacer"></span>
      <button id="save" class="primary">Save</button>
    </div>
    <textarea id="body" spellcheck="true" placeholder="Pick a chapter from the shelf, or start a new book."></textarea>
    <div class="status">
      <span class="num" id="words">—</span>
      <span id="dirty"></span>
      <span class="spacer" style="flex:1"></span>
      <span class="loc" id="path"></span>
    </div>
  </main>

  <section class="panel">
    <div class="tabs" role="tablist">
      <button role="tab" id="tab-assist" aria-selected="true">Assist</button>
      <button role="tab" id="tab-checks" aria-selected="false">Checks</button>
    </div>

    <div id="pane-assist" style="display:flex;flex-direction:column;flex:1;overflow:hidden">
      <div class="actions" id="tasks"></div>
      <div class="field">
        <textarea id="instruction"
          placeholder="Optional instruction — e.g. tighten the dialogue, or cut the layoff scene."></textarea>
      </div>
      <div class="actions">
        <button id="insert" disabled>Insert at cursor</button>
        <button id="replace" disabled>Replace selection</button>
        <button id="stop" disabled>Stop</button>
      </div>
      <div class="scroll"><div id="out" class="empty">Choose a chapter, then pick a task.</div></div>
    </div>

    <div id="pane-checks" style="display:none;flex-direction:column;flex:1;overflow:hidden">
      <div class="actions">
        <button id="run-check">Continuity check</button>
        <button id="reload-issues" class="ghost">Refresh</button>
      </div>
      <div class="scroll" id="checks"><p class="empty">No checks run yet.</p></div>
    </div>
  </section>
</div>

<dialog id="prompt-dialog">
  <form method="dialog">
    <p id="prompt-title" style="margin:0 0 .6rem;font-weight:600"></p>
    <label>Title <input id="prompt-title-input" required></label>
    <label id="prompt-logline-wrap">Logline <input id="prompt-logline"></label>
    <div style="display:flex;gap:.4rem;justify-content:flex-end;margin-top:.8rem">
      <button value="cancel" class="ghost">Cancel</button>
      <button value="ok" class="primary">Create</button>
    </div>
  </form>
</dialog>
"""

_SCRIPT = r"""
const $ = (id) => document.getElementById(id);
const state = { library: null, slug: null, number: null, meta: {}, dirty: false, controller: null };

const api = async (path, options) => {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
};

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Mirrors models.prose_spans so the count in the status bar means the same
// thing as `books stats` and the dashboard: narrative prose, not scaffolding.
const SCAFFOLD = ["outline and contextual alignment", "references & contextual alignment",
                  "references and contextual alignment", "links and references",
                  "suggested minor updates", "suggested updates"];
const PROSE = ["chapter body", "body"];

function proseOf(text) {
  const headings = [...text.matchAll(/^(#{1,6})[ \t]+(.*?)[ \t]*#*$/gm)];
  if (!headings.length) return text;
  const level = (h) => h[1].length;
  const title = (h) => h[2].trim().toLowerCase();
  const starts = (h, list) => list.some((p) => title(h).startsWith(p));
  const subtreeEnd = (i) => {
    for (let j = i + 1; j < headings.length; j++)
      if (level(headings[j]) <= level(headings[i])) return headings[j].index;
    return text.length;
  };
  const contentStart = (h) => h.index + h[0].length;

  const named = headings.map((h, i) => [h, i]).filter(([h]) => starts(h, PROSE));
  if (named.length) return named.map(([h, i]) => text.slice(contentStart(h), subtreeEnd(i))).join("\n");

  const spans = [];
  for (let i = 0; i < headings.length; ) {
    if (starts(headings[i], SCAFFOLD)) {
      const end = subtreeEnd(i);
      while (i < headings.length && headings[i].index < end) i++;
      continue;
    }
    const next = i + 1 < headings.length ? headings[i + 1].index : text.length;
    spans.push(text.slice(contentStart(headings[i]), next));
    i++;
  }
  return spans.join("\n");
}

const countWords = (text) => (proseOf(text).match(/[A-Za-z0-9'’-]+/g) || []).length;

// -- library ---------------------------------------------------------------
async function loadLibrary() {
  state.library = await api("/api/library");
  renderLibrary();
  renderTasks();
  renderIssues();
}

function renderLibrary() {
  const host = $("library");
  const books = state.library.books;
  if (!books.length) { host.innerHTML = '<p class="empty">No books yet.</p>'; return; }
  host.innerHTML = books.map((book) => `
    <details class="book" ${book.slug === state.slug ? "open" : ""}>
      <summary>
        <span class="name">${escapeHtml(book.title)}</span>
        <span class="count">${book.chapters.length}</span>
      </summary>
      <ul class="chapters">
        ${book.chapters.map((chapter) => `
          <li><a href="#" data-slug="${escapeHtml(book.slug)}" data-number="${chapter.number}"
                 class="${book.slug === state.slug && chapter.number === state.number ? "active" : ""}">
            <span class="num">${chapter.number}</span>
            <span class="t">${escapeHtml(chapter.title)}</span>
          </a></li>`).join("")}
        <li><a href="#" data-new-chapter="${escapeHtml(book.slug)}"><span class="num">+</span>
          <span class="t">New chapter</span></a></li>
      </ul>
    </details>`).join("");

  host.querySelectorAll("a[data-slug]").forEach((link) =>
    link.addEventListener("click", (event) => {
      event.preventDefault();
      openChapter(link.dataset.slug, Number(link.dataset.number));
    }));
  host.querySelectorAll("a[data-new-chapter]").forEach((link) =>
    link.addEventListener("click", (event) => {
      event.preventDefault();
      createChapter(link.dataset.newChapter);
    }));
}

// -- chapter ---------------------------------------------------------------
async function openChapter(slug, number) {
  if (state.dirty && !confirm("Discard unsaved changes?")) return;
  const chapter = await api(`/api/chapter?slug=${encodeURIComponent(slug)}&number=${number}`);
  state.slug = slug;
  state.number = number;
  state.meta = chapter.meta || {};
  $("body").value = chapter.body;
  $("meta").hidden = false;
  $("m-title").value = state.meta.title || "";
  $("m-number").value = state.meta.number ?? number;
  $("m-act").value = state.meta.act ?? "";
  $("m-status").value = state.meta.status || "draft";
  $("m-pov").value = state.meta.pov || "";
  $("path").textContent = chapter.path;
  setDirty(false);
  updateWords();
  renderLibrary();
  renderIssues();
}

function collectMeta() {
  const meta = { ...state.meta };
  meta.title = $("m-title").value;
  meta.status = $("m-status").value;
  meta.pov = $("m-pov").value;
  const number = parseInt($("m-number").value, 10);
  if (!Number.isNaN(number)) meta.number = number;
  const act = parseInt($("m-act").value, 10);
  meta.act = Number.isNaN(act) ? "" : act;
  return meta;
}

async function save() {
  if (state.slug === null) return;
  $("dirty").textContent = "saving…";
  try {
    const saved = await api("/api/chapter", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: state.slug, number: state.number, meta: collectMeta(), body: $("body").value }),
    });
    state.meta = saved.meta;
    setDirty(false);
    await loadLibrary();
  } catch (error) {
    $("dirty").innerHTML = `<span class="err">${escapeHtml(error.message)}</span>`;
  }
}

let saveTimer = null;
function setDirty(value) {
  state.dirty = value;
  $("dirty").textContent = value ? "unsaved" : "saved";
  clearTimeout(saveTimer);
  if (value) saveTimer = setTimeout(save, 2000);
}

function updateWords() {
  $("words").textContent = `${countWords($("body").value).toLocaleString()} words`;
}

// -- assistant -------------------------------------------------------------
function renderTasks() {
  $("tasks").innerHTML = state.library.tasks
    .map((task) => `<button data-task="${escapeHtml(task.key)}" title="${escapeHtml(task.description)}">`
                 + `${escapeHtml(task.label)}</button>`)
    .join("");
  $("tasks").querySelectorAll("button[data-task]").forEach((button) =>
    button.addEventListener("click", () => runTask(button.dataset.task)));
}

function selection() {
  const area = $("body");
  return area.value.slice(area.selectionStart, area.selectionEnd);
}

async function runTask(key) {
  if (!state.slug) { $("out").textContent = "Open a chapter first."; return; }
  if (key === "check") { switchTab("checks"); return runCheck(); }

  const out = $("out");
  out.className = "";
  out.textContent = "";
  $("stop").disabled = false;
  state.controller = new AbortController();

  const payload = {
    slug: state.slug, number: state.number, task: key,
    instruction: $("instruction").value, selection: selection(),
  };

  try {
    const response = await fetch("/api/ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: state.controller.signal,
    });
    if (!response.ok || !response.body) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.error || response.statusText);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop();
      for (const frame of frames) {
        const name = (frame.match(/^event: (.*)$/m) || [])[1];
        const raw = (frame.match(/^data: (.*)$/m) || [])[1];
        if (!name || raw === undefined) continue;
        const data = JSON.parse(raw);
        if (name === "text") out.textContent += data;
        else if (name === "error") { out.innerHTML += `<span class="err">${escapeHtml(data.message)}</span>`; }
      }
    }
  } catch (error) {
    if (error.name !== "AbortError") out.innerHTML = `<span class="err">${escapeHtml(error.message)}</span>`;
  } finally {
    $("stop").disabled = true;
    state.controller = null;
    const hasText = out.textContent.trim().length > 0;
    $("insert").disabled = !hasText;
    $("replace").disabled = !hasText;
  }
}

function insertText(replaceSelection) {
  const area = $("body");
  const text = $("out").textContent;
  const start = replaceSelection ? area.selectionStart : area.selectionEnd;
  const end = area.selectionEnd;
  area.value = area.value.slice(0, start) + text + area.value.slice(end);
  area.focus();
  area.selectionStart = area.selectionEnd = start + text.length;
  setDirty(true);
  updateWords();
}

// -- checks ----------------------------------------------------------------
function renderIssues(extra) {
  const host = $("checks");
  const all = (state.library?.issues || []).filter(
    (issue) => !state.slug || issue.path.includes(`/${state.slug}/`));
  // The open chapter first: a book-wide list buries the findings you can act
  // on right now under a hundred from chapters you are not looking at.
  const here = state.number === null
    ? null
    : `/chapters/ch${String(state.number).padStart(2, "0")}.md`;
  const issues = here ? all.filter((issue) => issue.path.endsWith(here)) : all;
  const elsewhere = all.length - issues.length;
  const parts = [];

  if (extra) {
    parts.push(`<p class="empty">${escapeHtml(extra.summary || "")}</p>`);
    for (const finding of extra.findings || []) {
      const level = finding.severity === "high" ? "critical" : finding.severity === "medium" ? "warning" : "good";
      parts.push(`<div class="finding">
        <div class="head"><span class="dot ${level}"></span><strong>${escapeHtml(finding.problem)}</strong></div>
        <div class="kind">${escapeHtml(finding.kind)} · ${escapeHtml(finding.severity)}</div>
        ${finding.quote ? `<blockquote>${escapeHtml(finding.quote)}</blockquote>` : ""}
        <div class="fix">${escapeHtml(finding.suggestion)}</div>
      </div>`);
    }
  }

  if (issues.length) {
    const scope = here ? "this chapter" : "this book";
    parts.push(`<p class="kind" style="margin:.6rem 0 .3rem">From <code>books validate</code> — ${scope}</p>`);
    for (const issue of issues) {
      parts.push(`<div class="finding">
        <div class="head"><span class="dot ${issue.level === "error" ? "critical" : "warning"}"></span>
          <strong>${escapeHtml(issue.message)}</strong></div>
        <div class="loc">${escapeHtml(issue.path)}${issue.line ? ":" + issue.line : ""}
          · ${escapeHtml(issue.code)}</div>
      </div>`);
    }
  }
  if (elsewhere > 0) {
    const plural = elsewhere === 1 ? "" : "s";
    parts.push(`<p class="empty">${elsewhere} more finding${plural} in other chapters of this book.</p>`);
  }

  host.innerHTML = parts.length ? parts.join("") : '<p class="empty">Nothing to report.</p>';
}

async function runCheck() {
  if (!state.slug) return;
  $("checks").innerHTML = '<p class="empty">Reading the chapter against the brief…</p>';
  try {
    const result = await api("/api/ai/structured", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: state.slug, number: state.number, task: "check",
                             instruction: $("instruction").value }),
    });
    renderIssues(result);
  } catch (error) {
    $("checks").innerHTML = `<p class="err">${escapeHtml(error.message)}</p>`;
  }
}

// -- creation --------------------------------------------------------------
function ask(title, withLogline) {
  return new Promise((resolve) => {
    const dialog = $("prompt-dialog");
    $("prompt-title").textContent = title;
    $("prompt-title-input").value = "";
    $("prompt-logline").value = "";
    $("prompt-logline-wrap").hidden = !withLogline;
    dialog.returnValue = "";
    dialog.showModal();
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "ok" && $("prompt-title-input").value.trim()
        ? { title: $("prompt-title-input").value.trim(), logline: $("prompt-logline").value.trim() }
        : null);
    }, { once: true });
  });
}

async function createBook() {
  const answer = await ask("New book", true);
  if (!answer) return;
  try {
    const book = await api("/api/book", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(answer),
    });
    await loadLibrary();
    state.slug = book.slug;
    renderLibrary();
  } catch (error) { alert(error.message); }
}

async function createChapter(slug) {
  const answer = await ask("New chapter", false);
  if (!answer) return;
  try {
    const book = await api("/api/chapter", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, title: answer.title }),
    });
    await loadLibrary();
    const last = book.chapters[book.chapters.length - 1];
    if (last) await openChapter(slug, last.number);
  } catch (error) { alert(error.message); }
}

// -- wiring ----------------------------------------------------------------
function switchTab(name) {
  const assist = name === "assist";
  $("pane-assist").style.display = assist ? "flex" : "none";
  $("pane-checks").style.display = assist ? "none" : "flex";
  $("tab-assist").setAttribute("aria-selected", String(assist));
  $("tab-checks").setAttribute("aria-selected", String(!assist));
}

$("body").addEventListener("input", () => { setDirty(true); updateWords(); });
["m-title", "m-number", "m-act", "m-status", "m-pov"].forEach((id) =>
  $(id).addEventListener("input", () => setDirty(true)));
$("save").addEventListener("click", save);
$("insert").addEventListener("click", () => insertText(false));
$("replace").addEventListener("click", () => insertText(true));
$("stop").addEventListener("click", () => state.controller?.abort());
$("new-book").addEventListener("click", createBook);
$("run-check").addEventListener("click", runCheck);
$("reload-issues").addEventListener("click", async () => { await loadLibrary(); renderIssues(); });
$("tab-assist").addEventListener("click", () => switchTab("assist"));
$("tab-checks").addEventListener("click", () => switchTab("checks"));

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "s") { event.preventDefault(); save(); }
});
window.addEventListener("beforeunload", (event) => {
  if (state.dirty) { event.preventDefault(); event.returnValue = ""; }
});

loadLibrary().catch((error) => {
  document.getElementById("library").innerHTML = `<p class="err">${escapeHtml(error.message)}</p>`;
});
"""


def page() -> str:
    """The whole editor as one HTML document."""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Bookshelf Studio</title>\n"
        f"<style>{_STYLE}</style>\n"
        "</head>\n<body>\n"
        f"{_BODY}\n"
        f"<script>{_SCRIPT}</script>\n"
        "</body>\n</html>\n"
    )
