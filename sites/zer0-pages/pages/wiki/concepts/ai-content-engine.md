---
title: "AI Content Engine"
type: concept
complexity: intermediate
domain: "content management / AI tooling"
description: "The PRD's name for AI-driven content generation, enhancement, and analysis across a CMS; in this repo the same goal is achieved through claude-obsidian's skills rather than a dedicated backend service."
aliases:
  - "AI Layer"
created: 2026-07-05
updated: 2026-07-05
tags:
  - concept
  - ai
  - content-generation
status: seed
related:
  - "[[wiki/entities/zer0-pages]]"
  - "[[wiki/entities/claude-obsidian]]"
  - "[[wiki/concepts/prd-machine]]"
sources:
  - "[[wiki/sources/zer0-pages-prd]]"
---

# AI Content Engine

## Definition

The AI Content Engine is the [[wiki/sources/zer0-pages-prd|zer0-pages PRD]]'s (§5.1) name for a subsystem that generates and enhances content using large language models: blog posts from prompts, documentation from repository analysis, PRDs from repo scans, code-quality analysis, and content enhancement, with multi-provider fallback across OpenAI, Anthropic, and xAI models.

## How It Works

Per the PRD, the engine is a Django-side service exposed via REST endpoints (`/api/ai/generate/`, `/api/ai/enhance/`, `/api/ai/analyze/`, `/api/ai/chat/`), with retry/backoff, model fallback on quota exhaustion, response caching, and per-provider timeout handling. **This is aspirational** — no such API exists in this repository. The functional equivalent that actually exists here is [[wiki/entities/claude-obsidian|claude-obsidian]]'s skill set: `/wiki-ingest` turns a dropped source into structured notes, `/save` captures a conversation as a note, `/autoresearch` runs a web-research loop and files its findings, and `/wiki-query` answers questions from the vault. These are invoked conversationally inside Claude Code, not called as a REST API, and they operate on Markdown files in an Obsidian vault rather than database rows.

## Why It Matters

The gap between the PRD's imagined engine and claude-obsidian's actual skills is the central "vision vs. reality" tension of this ingestion: the PRD describes a productized, API-driven AI backend; what this repo actually runs is an agent (Claude Code + claude-obsidian) operating directly on a file-based vault that is simultaneously the Jekyll site source. Understanding this distinction matters for anyone reading the PRD literally and expecting to find a `/api/ai/generate/` endpoint, a Django admin, or a hosted AI service in this codebase — none exists.

## Examples

- PRD's imagined capability: "PRD Generation: Analyze GitHub repos and produce comprehensive PRDs" — see [[wiki/concepts/prd-machine|PRD Machine]] for the PRD's own (also unimplemented) framing of this.
- Real capability in this repo: this very page was produced by exactly the kind of process the PRD describes (AI reads a source, extracts entities/concepts, files structured notes) — but performed by claude-obsidian's `/wiki-ingest` skill acting on Markdown, not a Django "AI Layer" acting on a database.

## Connections

- [[wiki/entities/claude-obsidian|claude-obsidian]] — the real implementation of "AI-generates-content-into-the-vault."
- [[wiki/entities/zer0-pages|zer0-pages]] — the product name under which the PRD's vision (and the repo's reality) both live.
- [[wiki/concepts/prd-machine|PRD Machine]] — a narrower, PRD-specific instance of the same "AI generates structured documents" idea.
- [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]] — the actual substrate the AI-authored content is written into and published from.

## Sources

- [[wiki/sources/zer0-pages-prd|zer0-pages PRD]], §5.1 "AI Content Engine."
