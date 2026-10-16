---
title: Narnia6
description: "Narnia Level 6 — a harder overflow where relying on injected shellcode is unattractive; think about reusing code that already exists in the program."
excerpt: "Narnia Level 6 — a harder overflow where relying on injected shellcode is unattractive; think about reusing code that already exists in the program."
permalink: /docs/wargames/narnia/narnia6/
date: '2026-04-07T01:41:09.000Z'
lastmod: '2026-04-07T01:41:09.000Z'
categories:
- wargames
- narnia
tags:
- security
- wargames
- linux
- ctf
- cybersecurity
toc_sticky: true
source_repo: https://github.com/OverTheWireOrg/OverTheWire-website
source_url: https://github.com/OverTheWireOrg/OverTheWire-website/blob/gh-pages/narnia/narnia6.md
source_name: overthewire
license: MIT
draft: false
keywords:
- security
- wargames
- linux
- ctf
- cybersecurity
- narnia
author: bamr87
nav_order: 6
sidebar_label: "Level 6"
---
> **Source:** This content is aggregated from [overthewire](https://github.com/OverTheWireOrg/OverTheWire-website) ([MIT](https://github.com/OverTheWireOrg/OverTheWire-website/blob/gh-pages/LICENSE)). Visit the original repository for the latest version.

There is no information for this level, intentionally.

<!-- study-guide:start -->

## Study guide

**Level map:** logged in as `narnia6`, find the password for `narnia7`.

### What this level teaches

Reusing existing code rather than injecting your own, a stepping stone to modern exploitation.

### Key ideas

- **Return-to-libc.** The C library is already loaded and contains useful functions. Redirecting execution to one with chosen arguments avoids needing shellcode.
- **Calling conventions.** On 32-bit x86, arguments go on the stack; you have to place them where the called function expects.
- **Finding addresses.** `gdb` and `ldd` help locate library functions, and addresses differ between runs if randomisation is on.
- **Read the source closely.** The program's structure determines which pointers or return addresses are reachable.

### How to approach it

1. Read the source and list what can be overwritten and what it controls.
2. Locate the function you want to call and the string you want to pass it.
3. Assemble and test the payload in `gdb` before running it for real.

### Why it matters

Return-to-libc leads directly to return-oriented programming (ROP), the standard bypass for non-executable stacks.

<!-- study-guide:end -->
