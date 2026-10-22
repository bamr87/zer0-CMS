"""The `distribution` agent's handler (agents/definitions/distribution.yaml): a
deterministic run, no model, that drafts a post of the run's page for every
channel of its site that drafts automatically — through `distribution.compose`
in the registry, so the agent's policy, the page's, the agent user's rights and
the rate all hold. A channel that already has a post of the page, or a ledger
entry for its URL, is left alone.
"""

from agents.registry import ToolError, registry

from .models import Channel, DistributionPost, LedgerEntry


def draft_for_page(run, ctx) -> dict:
    """The run's output is `{"json": {"drafted": n, "skipped": [why, …]}}` — its structured result."""
    page = run.target
    site = page.get_site() if page is not None else None
    if site is None:
        return {"json": {"drafted": 0, "skipped": []}}
    drafted, skipped = 0, []
    for channel in Channel.objects.filter(site=site, auto_draft=True).order_by("pk"):
        has_post = DistributionPost.objects.filter(channel=channel, page_id=page.pk).exclude(status="rejected").exists()
        published = LedgerEntry.objects.filter(channel=channel, post__page_id=page.pk).exclude(urn="").exists()
        if has_post or published:
            skipped.append(f"{channel.name}: already has a post of this page")
            continue
        try:
            registry.call("distribution.compose", {"channel": str(channel.public_id), "page_id": page.pk}, ctx)
        except ToolError as e:
            skipped.append(f"{channel.name}: {e.message}")
            continue
        drafted += 1
    return {"json": {"drafted": drafted, "skipped": skipped}}
