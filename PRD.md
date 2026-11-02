# zer0-CMS — Product requirements

> What the product must do, with stable requirement ids (`FRn`, `NFRn`) that features in [`features/features.yml`](features/features.yml) name under `prd:`. The constitution (§ 3) ranks this document under AGENTS.md and above the feature catalog. FR1 and NFR1 (the books library's serial fiction) arrive with bamr87/zer0-CMS#84; this file adds FR2 and is merged with that one's.

## 1. Requirements

### Functional

- FR2: An author can carry a book's chapters — one book of a serial such as the books library's `cost-line` pilot — to a Substack publication, as drafts while they are in progress and as posts once marked published, keyed by each chapter's canonical URL so that a re-sync never makes a second post; by Substack's sanctioned routes (its post importer reading an RSS feed, or a paste-ready copy) by default, with any unofficial route behind the same adapter interface, off unless the deployment arms it.

### Non-functional

- NFR2: A Substack sync is designed for failure: it detects each failure as retryable or in doubt, contains it to its chapter, retries only failures that cannot have published (with backoff), ledgers a write in doubt as unconfirmed and refuses it until a person forces past it, and logs every outcome without a credential; credentials come from the environment only.
