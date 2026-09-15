# `multi/` — the two-folder fixture

`../multi.code-workspace` opens both of these as one multi-root window, and `src/test/multiroot.test.ts` runs against it through the second `defineConfig` entry in `.vscode-test.mjs`.

They are deliberately **different platforms** — `site-a` is Jekyll, `site-b` is MkDocs — because half of what the registry has to get right is that two folders resolve two different profiles, two different content roots and two different serve commands. A pair of identical folders would pass a test that a single shared config would also pass.

Both carry a `zer0.json`, so both are "configured" and both get their own MCP server definition. `site-a` sets `zer0Cms.governance.publishAllow` to `true` in its own `.vscode/settings.json` — the folder scope of a `resource`-scoped setting — and `site-b` sets the same key to `true` in its **`zer0.json`**. That asymmetry is the whole of the "a folder-scoped publishAllow arms only its own server" test: the setting arms site-a's server, the file arms nothing at all, and both folders have governance enabled so nothing else can account for the difference.

Keep these small. They exist to prove routing, not content behaviour; the content suites all run against `../workspace/`.
