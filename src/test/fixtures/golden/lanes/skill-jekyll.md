---
# kit: ai-runner v0.1.0
name: grow-lifehacker
description: "Produce ONE on-voice, tested piece from the backlog, verify it with the repository harness, and open ONE pull request. Never merges."
---
<!-- kit: ai-runner v0.1.0 -->

# grow-lifehacker — the routine the `content-factory` lane runs

> **This is a stub.** The steps below are the shape, not the procedure. Fill
> them in from what the work actually takes; a routine nobody has run is
> worse than no routine at all.

## When to use

Use when asked to create for **lifehacker.dev**, or on the `content-factory` lane's own schedule.

## The routine

1. **Read first.** The repository's own instructions (`CLAUDE.md`, the nearest `README.md`), then whatever data this routine works from.
2. **Do exactly one unit of work.** Name what it is before starting it, so "done" has a definition.
3. **Verify with the repository's own harness.** Not a claim — a command, and its output.
4. **Open ONE pull request** and write its URL to `pr-result.txt`.

## What it never does

- Never merges, never self-approves, never pushes to the default branch.
- Never disables a kill switch or removes an `*_ENABLED` gate.
- Never reports a check it did not run.

Guardrails: `.claude/skills/_shared/quarantine.md` — all sections apply.
