---
layout: home
title: "Marginalia"
description: "A public digital garden about reading, note-taking and how ideas connect — written in the open and revised in place."
permalink: /
hide_title: true
rss_subscribe: false
---
{%- assign landing = site.data.landing -%}
{%- assign hero = landing.hero -%}
<section class="zer0-landing-hero py-5{% if hero.variant == "inverse" %} bg-primary text-white{% elsif hero.variant == "muted" %} bg-body-tertiary{% endif %}" data-landing-template="{{ landing.template }}">
  <div class="container-xl text-{{ hero.align | default: "center" }}">
    {% if hero.eyebrow %}<p class="text-uppercase small fw-semibold mb-2 opacity-75">{{ hero.eyebrow }}</p>{% endif %}
    <h1 class="display-4 fw-bold mb-3">{{ hero.headline | default: site.title }}</h1>
    {% if hero.subheadline %}<p class="lead mb-4 mx-auto" style="max-width: 44rem;">{{ hero.subheadline }}</p>{% endif %}
    {% if hero.ctas and hero.ctas.size > 0 %}
    <div class="d-flex flex-wrap gap-2 justify-content-{{ hero.align | default: "center" }}">
      {%- for cta in hero.ctas -%}
        {%- assign cta_variant = cta.variant | default: "primary" -%}
        {%- comment -%} An outlined button is white on an inverse hero and primary-coloured everywhere else. {%- endcomment -%}
        {%- if cta_variant == "outline" and hero.variant == "inverse" %}{% assign cta_variant = "outline-light" %}{% endif -%}
        {% include components/cta-button.html label=cta.label url=cta.url variant=cta_variant icon=cta.icon size="lg" %}
      {%- endfor -%}
    </div>
    {% endif %}
    {% if hero.image %}<img src="{{ hero.image | relative_url }}" alt="" class="zer0-landing-hero-image img-fluid rounded-3 shadow-sm mt-4" loading="lazy" decoding="async">{% endif %}
  </div>
</section>

{% for s in landing.sections %}
{%- capture body -%}
  {%- case s.type -%}
  {%- when "features" -%}
    <div class="row g-4">{% for it in s.items %}<div class="col-md-4"><div class="card h-100 border-0 shadow-sm"><div class="card-body"><i class="bi {{ it.icon | default: "bi-check-circle" }} fs-2 text-primary" aria-hidden="true"></i><h3 class="h5 mt-2">{{ it.title }}</h3><p class="mb-0 text-body-secondary">{{ it.text }}</p></div></div></div>{% endfor %}</div>
  {%- when "cards" -%}
    <div class="row g-4">{% for it in s.items %}<div class="col-md-6 col-lg-4"><a class="card h-100 text-decoration-none" href="{{ it.url | default: "#" | relative_url }}"><div class="card-body"><i class="bi {{ it.icon | default: "bi-arrow-right-circle" }} fs-3 text-primary" aria-hidden="true"></i><h3 class="h5 mt-2 card-title">{{ it.title }}</h3><p class="card-text text-body-secondary mb-0">{{ it.text }}</p></div></a></div>{% endfor %}</div>
  {%- when "steps" -%}
    <ol class="list-unstyled row g-4 mb-0">{% for it in s.items %}<li class="col-md-4 d-flex gap-3"><span class="badge rounded-pill text-bg-primary fs-6 align-self-start">{{ forloop.index }}</span><div><h3 class="h5 mb-1">{{ it.title }}</h3><p class="mb-0 text-body-secondary">{{ it.text }}</p></div></li>{% endfor %}</ol>
  {%- when "stats" -%}
    <div class="row g-4 text-center">{% for it in s.items %}<div class="col-6 col-md-3"><div class="display-5 fw-bold text-primary">{{ it.value }}</div><div class="text-body-secondary">{{ it.label }}</div></div>{% endfor %}</div>
  {%- when "faq" -%}
    <div class="accordion" id="faq-{{ forloop.index }}">{% for it in s.items %}<div class="accordion-item"><h3 class="accordion-header"><button class="accordion-button{% unless forloop.first %} collapsed{% endunless %}" type="button" data-bs-toggle="collapse" data-bs-target="#faq-{{ forloop.parentloop.index }}-{{ forloop.index }}">{{ it.title }}</button></h3><div id="faq-{{ forloop.parentloop.index }}-{{ forloop.index }}" class="accordion-collapse collapse{% if forloop.first %} show{% endif %}" data-bs-parent="#faq-{{ forloop.parentloop.index }}"><div class="accordion-body">{{ it.text }}</div></div></div>{% endfor %}</div>
  {%- when "cta" -%}
    <div class="text-center">{% if s.cta %}{% include components/cta-button.html label=s.cta.label url=s.cta.url variant="light" size="lg" %}{% endif %}</div>
  {%- when "latest_posts" -%}
    <div class="row g-4">{% for post in site.posts limit: s.limit | default: 3 %}<div class="col-md-4"><a class="card h-100 text-decoration-none" href="{{ post.url | relative_url }}"><div class="card-body"><p class="small text-body-secondary mb-1">{{ post.date | date: "%B %-d, %Y" }}</p><h3 class="h5 card-title">{{ post.title }}</h3><p class="card-text text-body-secondary mb-0">{{ post.description | default: post.excerpt | strip_html | truncate: 140 }}</p></div></a></div>{% endfor %}</div>
  {%- when "quote" -%}
    {% assign q = s.items | first %}<figure class="text-center mb-0"><blockquote class="blockquote fs-3"><p>“{{ q.quote }}”</p></blockquote>{% if q.author %}<figcaption class="blockquote-footer mt-2">{{ q.author }}</figcaption>{% endif %}</figure>
  {%- else -%}
    <div class="mx-auto" style="max-width: 44rem;">{{ s.body | markdownify }}</div>
  {%- endcase -%}
{%- endcapture -%}
{% include components/section.html id=s.id variant=s.variant heading=s.heading lead=s.lead content=body %}
{% endfor %}
