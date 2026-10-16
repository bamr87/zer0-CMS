---
title: Wargames — Security Challenges
description: Curated security wargames from the OverTheWire community. Learn and practice security concepts through gamified challenges.
layout: home
permalink: /
date: '2025-01-27T00:00:00.000Z'
lastmod: '2026-04-07T02:46:45.000Z'
categories:
- wargames
tags:
- security
- wargames
- linux
- ctf
- cybersecurity
toc_sticky: true
source_repo: https://github.com/OverTheWireOrg/OverTheWire-website
source_name: overthewire
license: MIT
author: bamr87
excerpt: Security wargame challenges to practice Linux, CTF, and cybersecurity skills.
draft: false
keywords:
- security
- wargames
- linux
- overthewire
- ctf
- cybersecurity
---

> **Source:** This section aggregates content from the [OverTheWire](https://overthewire.org/wargames/) community project ([MIT License](https://github.com/OverTheWireOrg/OverTheWire-website/blob/gh-pages/LICENSE)). Visit the original site to play the games live via SSH.

## What Are Wargames?

Wargames are security-focused challenges offered by the [OverTheWire](https://overthewire.org/) community. They teach security concepts in a gamified, progressive format, starting from basic Unix/Linux commands and building up to advanced exploitation techniques.

Each wargame is a series of levels that must be completed in order. In most games you connect to a server over SSH and use what you know to find the password for the next level. The password is the reward, but the real prize is the skill you build while finding it.

## How This Site Helps You Learn

The challenge pages are a mirror of the upstream OverTheWire pages, and many of them are deliberately sparse: some levels say only that there is "no information for this level, intentionally". To make the collection useful for self-study, every page also carries a **Study guide** section that:

- explains the concepts the level is about, in plain language;
- suggests how to approach it, with hints rather than answers;
- says why the skill matters in real security and IT work.

The guides are **spoiler-free**. They never contain passwords or finished solutions, so you can read them without ruining the game. Where upstream withholds details about a level and the guide cannot say more, it says so instead of guessing.

## Available Games

### Beginner

| Game | Focus | What you will practise |
|------|-------|------------------------|
| [**Bandit**](docs/wargames/bandit/) | Linux basics | the command line, SSH, text tools, permissions, cron, git |
| [**Natas**](docs/wargames/natas/) | Web security | server-side web flaws from page source to SQL injection, played in a browser |
| [**Krypton**](docs/wargames/krypton/) | Cryptography | classical ciphers, frequency analysis, Vigenère, a weak stream cipher |
| [**Leviathan**](docs/wargames/leviathan/) | Reverse engineering | tracing small setuid programs, with no programming required |

### Intermediate

| Game | Focus | What you will practise |
|------|-------|------------------------|
| [**Narnia**](docs/wargames/narnia/) | Binary exploitation | buffer overflows and format strings, with source code provided |
| [**Behemoth**](docs/wargames/behemoth/) | Binary exploitation | overflows, format strings and race conditions without source |
| [**Utumno**](docs/wargames/utumno/) | Binary exploitation | harder binaries, a step above Behemoth |

### Advanced

| Game | Focus | What you will practise |
|------|-------|------------------------|
| [**Maze**](docs/wargames/maze/) | Exploitation and reversing | tricky, unconventional levels that call for `gdb` |
| [**Manpage**](docs/wargames/manpage/) | Code auditing | finding bugs by reading manual pages for C pitfalls |
| [**Vortex**](docs/wargames/vortex/) | Mixed advanced topics | network programming, heap bugs, weak crypto, reverse engineering |
| [**Drifter**](docs/wargames/drifter/) | Mixed advanced topics | remote services, C++ and heap corruption, ASLR |
| [**FormulaOne**](docs/wargames/formulaone/) | Exploitation | a game rescued from intruded.net |

### Archived and downloadable

| Game | Status |
|------|--------|
| [**Semtex**](docs/wargames/semtex/) | offline; network programming and reverse engineering |
| [**Blacksun**](docs/wargames/blacksun/) | currently down; exploiting hardened hosts |
| [**Abraxas**](docs/wargames/abraxas/), [**HES2010**](docs/wargames/hes2010/), [**Monxla**](docs/wargames/monxla/), [**Kishi**](docs/wargames/kishi/) | released conference games you run locally as virtual machines |

The [full games index](docs/wargames/) compares all of them, including levels, SSH ports and difficulty.

## How to Get Started

1. **Start with Bandit.** It teaches the basics you will need for every other game.
2. **Connect via SSH:** `ssh bandit0@bandit.labs.overthewire.org -p 2220` (password: `bandit0`). Every game uses its own port.
3. **Progress through the levels.** Each level's password unlocks the next.
4. **Take notes.** Record the password, the command that worked, and why it worked. Passwords are not saved for you.
5. **Pick your next game** from the suggested order: Bandit, then one of Natas, Krypton or Leviathan, then Narnia, Behemoth, Utumno and Maze.

## Ground Rules

- Only attack the wargame servers and the accounts the games provide. Never use these techniques against systems you do not own or have written permission to test.
- Do not disrupt other players, and clean up after yourself in `/tmp`.
- Do not publish passwords or step-by-step solutions. Write about the concepts instead.

## About This Content

This documentation is aggregated from the [OverTheWire-website repository](https://github.com/OverTheWireOrg/OverTheWire-website) using the docs aggregation pipeline in `scripts/docs-aggregator/`. The content is transformed to fit the zer0-mistakes theme while preserving the original educational material. The **Study guide** sections are additions made by this site and sit after the upstream text, between `study-guide` marker comments, so they can be told apart from vendored content.

To update the upstream content, run:

```bash
bash scripts/docs-aggregator/aggregate_docs.sh
```

See the [aggregator documentation](https://github.com/bamr87/wargames/blob/main/scripts/docs-aggregator/README.md) for details, including how to carry the study guides over when you re-sync.
