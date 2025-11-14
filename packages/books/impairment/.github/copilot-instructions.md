Copilot / AI Agent Instructions for 'The Impairment'
---

This repository is a content-first book project (no app code). The goal for AI agents is to help author and maintain high-quality chapter files and book outline documents without changing the project structure.

Key locations
- `README.md` – main outline (three-act structure, themes, suggested chapters).
- `book/chapters/*.md` – chapter files (numbered: `ch1.md` … `ch14.md`). Each chapter follows a strict markdown + YAML front matter schema.
- `.github/instructions/*.instructions.md` – repository-native guidance; prefer these rules when writing/edits.

Primary conventions
- Each chapter file uses YAML front matter with these fields: `title`, `subtitle`, `character`, `setting`, `era`, `tone`, `style`.
- A chapter must contain an **Outline and Contextual Alignment** section followed by the chapter body and a **References & Contextual Alignment** section.
- Always add `Links and References` with relative links to the main `README.md` and prev/next chapters (e.g., `../README.md`, `ch2.md`).

AI agent workflow for edits
1. Read `README.md` and the target chapter + 1–2 surrounding chapters to maintain continuity.
2. Follow the `.github/instructions/*.instructions.md` templates:
   - Use `book-chapter-structure.instructions.md` when creating a chapter file from a title/summary.
   - Use `book-chapter-create.instructions.md` when drafting or updating a chapter; include suggested updates to other chapters if continuity is affected.
   - Use `README.instructions.md` when producing or updating the main outline.
3. When adding or changing plot/character beats, list explicit file suggestions that must be edited for continuity (e.g., add a callback line to `ch3.md`).

Formatting and tone
- Keep the voice consistent: chapters tend to be first-person, observational, and often darkly humorous / satirical.
- Front matter keys should be present and accurate; provide short descriptive values.
- Use the provided chapter skeleton and section headings; do not add custom shapes unless required for a new creative feature.

Commit & PR conventions
- Branch name: `chapter/<number>-<short-slug>` or `outline/<brief-change>`.
- Commit message: short imperative line + scope. e.g., `ch3: add scene showing CFO’s background`.
- PR body: short summary, list of modified files, and any recommended changes to other chapters for continuity.

Local preview / QA
- There is no automated build. Use markdown preview in VS Code or a markdown server (e.g., `grip`) to preview edits.
- If you add or update a character or cross-chapter fact, create a comment in the PR describing where to update earlier/later chapters.

Edge cases & constraints
- Do not introduce new global assets, scripts, or build configs in this repository without an explicit design intent—it's primarily a text repository.
- Keep chapter order consistent: file naming (`chN.md`) defines the sequence; only rename files when re-ordering content.

Examples
- Front matter short example:
  ```yaml
  ---
  title: The Last Day in the Plant
  subtitle: The End of an Era in American Manufacturing
  character: Kareem
  setting: Midwestern U.S. manufacturing plant
  era: Early 2020s
  tone: Darkly Humorous, Satirical
  style: First-Person, Observational
  ---
  ```

If anything in these rules is unclear or if you need more project-specific guardrails, leave a short PR comment asking which chapters to cross-check and why. Thank you.
