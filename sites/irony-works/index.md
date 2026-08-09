---
layout: default
title: Irony Works
permalink: /
preview: /assets/images/previews/default.svg
description: >
  Irony is not a mood. It is a structure — an expectation, and a reversal that
  comments on it. A self-growing encyclopedia that requires every entry to state
  both, so that irony becomes machine-checkable.
---

Rain on a wedding day is weather. A meteorologist rained out of her own wedding
is closer. A meteorologist rained out of the wedding she scheduled **using her
own forecast** — that's an entry.

## Irony has a structure, so it can be checked

Irony is not a mood. It is an **expectation**, articulated or assumed, and a
**reversal** that comments on it. Because that structure is mechanical, it can
be required. Every entry here states both as frontmatter fields:

```yaml
expectation: >
  Kodak, synonymous with photography, would own whatever photography became.
reversal: >
  Kodak invented the digital camera in 1975, shelved it to protect film,
  and was bankrupted by it in 2012.
```

If a candidate cannot fill both fields, it is not irony — it is merely
unfortunate, and it goes to the [compost]({{ '/compost/' | relative_url }})
with a verdict. That pair is the load-bearing wall: it makes irony
deduplicable, queryable, and gradeable.

<p>
  <a class="btn btn-primary" href="{{ '/entries/' | relative_url }}">Browse every entry</a>
  <a class="btn btn-outline-secondary" href="{{ '/how-it-grows/' | relative_url }}">How it grows</a>
  <a class="btn btn-outline-secondary" href="{{ '/entries/alanis-gate/' | relative_url }}">The Alanis Gate</a>
</p>

## Start anywhere

<div class="row g-3 my-3">
  <div class="col-md-6">
    <div class="p-3 border rounded h-100">
      <h3 class="h6"><a href="{{ '/forms/' | relative_url }}">Forms</a></h3>
      <p class="small mb-0">The taxonomy — verbal, situational, dramatic, Socratic, cosmic, structural, historical, meta. The trunk everything else branches from.</p>
    </div>
  </div>
  <div class="col-md-6">
    <div class="p-3 border rounded h-100">
      <h3 class="h6"><a href="{{ '/instances/' | relative_url }}">Instances</a></h3>
      <p class="small mb-0">The specimens: history and the present, dated, sourced, and rated for how well the evidence holds.</p>
    </div>
  </div>
  <div class="col-md-6">
    <div class="p-3 border rounded h-100">
      <h3 class="h6"><a href="{{ '/works/' | relative_url }}">Works</a> &amp; <a href="{{ '/figures/' | relative_url }}">Figures</a></h3>
      <p class="small mb-0">Texts that use irony as an instrument, and the practitioners whose lives enacted what they described.</p>
    </div>
  </div>
  <div class="col-md-6">
    <div class="p-3 border rounded h-100">
      <h3 class="h6"><a href="{{ '/mirrors/' | relative_url }}">Mirrors</a></h3>
      <p class="small mb-0">This machine's own ironies. An encyclopedia of irony that exempted itself would fail its own gate.</p>
    </div>
  </div>
</div>

## Three entries, if you want the flavour

{% assign featured = "the-kodak-moment|ozymandias|the-streisand-effect" | split: "|" %}
<div class="list-group mb-4">
{% for slug in featured %}
  {% assign e = site.entries | where: "slug", slug | first %}
  {% if e %}
  <a class="list-group-item list-group-item-action" href="{{ e.url | relative_url }}">
    <h3 class="h6 mb-1">{{ e.title }}</h3>
    {% if e.reversal %}<p class="mb-0 small text-muted">{{ e.reversal | strip_newlines | truncate: 200 }}</p>{% endif %}
  </a>
  {% endif %}
{% endfor %}
</div>

## The vault is the product

The source of truth is an [Obsidian](https://obsidian.md) vault of Markdown
files. This site is a pressing of it — wikilinks converted to permalinks at
build time, nothing authored here that isn't authored there. The full graph,
including the drafts and the rejects, is
[public on GitHub](https://github.com/{{ site.repository | join: '' }}).

> An encyclopedia of irony compiled by a machine that cannot be embarrassed is
> either the death of the form or its final proof. This repository exists to
> find out.
