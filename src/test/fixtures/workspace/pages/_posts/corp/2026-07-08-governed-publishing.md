---
title: Governed publishing without a platform
description: A publish gate that lives in the repository, is re-checked host-side, and leaves a ledger record keyed by canonical URL.
slug: governed-publishing
date: 2026-07-08
lastmod: 2026-07-09
draft: false
tags:
  - governance
  - publishing
categories:
  - corp
topic: operations
audience: executives
keywords: governance, publish gate, ledger
weight: 10
featured: true
campaign: launch
preview: assets/images/governed-publishing.png
related: mcp-for-the-back-office
seo:
  title: Governed publishing
  noindex: false
authorName: Fixture Author
authorEmail: author@example.test
---

# Governed publishing without a platform

The gate is a function, not a button. Every surface — the panel, the command palette, the bundled MCP server — calls the same `evaluatePublishGates`, reads the same ledger, and refuses for the same reasons.

## Why the ledger is keyed by URL

A ledger keyed by file path forgets a page the day somebody renames the file. A ledger keyed by canonical URL survives the rename and still refuses to publish the same page twice.

```ts
const blockers = evaluatePublishGates({ cfg, draft, guard, ledgerEntry });
```

## What the panel may not do

The panel posts an intent. It never posts a decision.
