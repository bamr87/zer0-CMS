<!-- kit: governance v0.1.0 -->
# 0003 — Missions

- **Status:** proposed
- **Date:** 2026-11-16
- **Proposed by:** Grok Bot (agent), at the maintainer's request
- **Ratified by:**
- **Affects:** constitution §1; PRD.md §1.1; ZER0-048
- **Supersedes:** none
- **Related:** [PRD.md](../../PRD.md) §1.1

## Context

Constitution §1 was a single mission sentence or short paragraph, not one direction statement with exactly three numbered missions. The fleet rule is that every repo's constitution §1 uses that form, adopted through a numbered amendment the maintainer ratifies by merging. Mission 1 is the maintainer's own wording, adapted to this repo: provide data, tools, resources and transparency for all stakeholders, practitioners in the domain, and the general public. The ambition is the direction, not a claim that the work is already finished.

The earlier §1 text was:

> zer0-CMS turns a repository of markdown into something you can actually operate:

## Amendment

Retitle constitution §1 **Missions**. Replace the body of §1 with the following. Any invariants or other normative rules that already lived outside §1 are unchanged.

zer0-CMS's direction is to become the ultimate open home for all things markdown site operations — data, tools, resources and transparency, gathered in one place that anyone can inspect and reuse.

1. **Provide data, tools, resources and transparency for all stakeholders, content operators, CMS practitioners and the general public.** Editors, reviewers, site operators, agent authors, and the general public are first-class audiences. The aim is a shared, open commons: the same sources, the same tools, and the same trail of evidence for everyone.
2. **Turn a repository of markdown into something you can actually operate: a governed CMS with a studio, a site renderer and a VS Code extension, where publishing goes through a gate a human has to walk through.** Agents declare their effect and permissions; page content and user input are treated as untrusted. The path is one Python platform (Django, with Wagtail as a headless library), a React studio, and a VS Code extension with the studio's capabilities.
3. **Put that platform in every editor's, agent's and builder's hands.** Serve it so zer0-themed markdown sites can be drafted, reviewed and published in the open — an open toolkit for working with all things markdown site operations.

These missions set the course; they do not claim the work is finished. They serve the README and PRD: an agent-native CMS for markdown sites, with a human publish gate. The earlier incomplete §1 sentence — "zer0-CMS turns a repository of markdown into something you can actually operate" — is absorbed into mission 2. Invariants in §2 (headless frontends, declared effects, suggest-by-default, no live LLMs in tests, and the rest) are unchanged. Every feature must trace to them.

_Source: [../PRD.md](../PRD.md) §1.1._

## Consequences

Agents and reviewers judge fit against these three missions before inventing scope, treating them as the direction of the repo rather than a description of what already ships. The same text is added as PRD.md §1.1 so the constitution's `_Source:` line stays accurate. The PRD purpose, goals, feature catalog and invariants outside this addition are unchanged except for a new catalog entry (ZER0-048) and a regenerated feature-catalog block where the repo already has one. This PR also aligns the README and AGENTS.md one-liners with the missions and links them to constitution §1.
