---
title: MCP for the back office
description: What the Model Context Protocol changes for small-business systems, and why the publish gate travels with it.
slug: mcp-for-the-back-office
date: 2026-07-06
lastmod: 2026-07-11
draft: false
tags:
  - mcp
  - governance
categories:
  - tech
topic: engineering
audience: practitioners
keywords: mcp, back office, tools
weight: 30
featured: false
preview: assets/images/mcp.png
---

# MCP for the back office

A tool server is a contract. It says what a model may do, and the answer is enforced where the work happens rather than in the prompt that asked for it.

## The eight tools

Eight tools, one of which can write, and that one is gated on an environment variable the extension host sets from the same config key the palette reads.

Small businesses do not have a platform team. They have a repository, a laptop, and somebody who is also the person answering the phone. MCP fits there because the server is a file, and the gate is a file, and both are reviewable.
