---
lastmod: 2026-04-18T19:30:03.000Z
title: Analytics
description: Analytics integration options for the Zer0-Mistakes theme including PostHog, Google Analytics, and Tag Manager.
preview: /images/previews/analytics.png
layout: default
categories:
    - docs
    - analytics
tags:
    - analytics
    - tracking
    - privacy
permalink: /docs/analytics/
difficulty: beginner
estimated_reading_time: 5 minutes
sidebar:
    nav: docs
type: doc
aliases:
  - /docs/analytics/
---

# Analytics

The Zer0-Mistakes theme supports multiple analytics platforms with privacy-first configurations.

## Available Integrations

| Platform | Privacy Focus | Free Tier |
|----------|--------------|-----------|
| [[_docs/features/posthog-analytics|PostHog]] | Yes (self-hostable) | 1M events/mo |
| [[_docs/analytics/google-analytics|Google Analytics]] | Limited | 10M hits/mo |
| [[_docs/analytics/google-tag-manager|Google Tag Manager]] | Varies | Unlimited |

## Quick Comparison

### PostHog (Recommended)

- **Privacy**: GDPR compliant, self-hostable
- **Features**: Analytics, session recording, feature flags
- **Best for**: Privacy-conscious sites

### Google Analytics

- **Privacy**: Data sent to Google
- **Features**: Comprehensive analytics
- **Best for**: Marketing insights

### Google Tag Manager

- **Privacy**: Depends on tags used
- **Features**: Centralized tag management
- **Best for**: Marketing teams

## Configuration Overview

### PostHog

```yaml
# _config.yml
posthog:
  enabled: true
  api_key: 'phc_YOUR_KEY'
  api_host: 'https://us.i.posthog.com'
```

### Google Analytics

```yaml
# _config.yml
google_analytics:
  tracking_id: 'G-XXXXXXXXXX'
```

### Google Tag Manager

```yaml
# _config.yml
google_tag_manager:
  container_id: 'GTM-XXXXXXX'
```

## Environment-Aware Loading

All analytics only load in production:

```liquid
{% raw %}{% if jekyll.environment == 'production' %}
  {% include analytics/posthog.html %}
{% endif %}{% endraw %}
```

## Privacy Compliance

See [[_docs/features/cookie-consent|Cookie Consent]] for GDPR/CCPA compliant consent management.

## Related

- [[_docs/features/posthog-analytics|PostHog Analytics]]
- [[_docs/analytics/google-analytics|Google Analytics]]
- [[_docs/analytics/google-tag-manager|Google Tag Manager]]
- [[_docs/features/cookie-consent|Cookie Consent]]
- [[privacy-policy|Privacy Policy]]

## See also

- [[_docs/features/index|Features]]
- [[_docs/customization/index|Customization]]
- [[_docs/seo/index|SEO]]
- [[_docs/deployment/index|Deployment]]
