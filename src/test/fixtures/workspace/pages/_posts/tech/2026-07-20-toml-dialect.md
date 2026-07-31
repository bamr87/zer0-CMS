+++
title = "The TOML dialect"
description = "A file whose front matter is TOML, to prove the parser is chosen by the fence and not by the folder."
slug = "toml-dialect"
date = "2026-07-20"
draft = false
tags = ["jekyll", "publishing"]
categories = ["tech"]
weight = 40
featured = false
+++

# The TOML dialect

Three fence forms, one `FrontMatter` shape. Line surgery is YAML-only by design: TOML and JSON blocks re-serialize wholesale through the documented fallback, which is why `updateFrontMatterKeys` answers `null` for them.
