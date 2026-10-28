"""The published-page consumer: when a page goes live (`content.page.published`,
schemas/events/), every channel of its site that drafts automatically
(`Channel.auto_draft`) gets a draft post of it — a draft, never a publish.

The drafting is a run of the GitOps `distribution` agent
(agents/definitions/distribution.yaml), so it is audited like any agent's work
and goes through the registry: `distribution.compose` under the agent's policy
narrowed by the page's (a page at policy `off` gets nothing), as the agent user.
The outbox dedupes the event per consumer (`ProcessedEvent`); the handler also
skips a channel that already has a post of the page (a rejected one too), or a
ledger entry for it.
"""

import logging

from wagtail.models import Page

from outbox.consumers import handler

log = logging.getLogger(__name__)
AGENT = "distribution"


@handler("content.page.published", consumer="distribution.auto-draft")
def draft_for_auto_channels(envelope: dict):
    from agents.models import AgentDefinition
    from agents.runner import RunRefused, start_run

    from .models import Channel

    page = Page.objects.filter(pk=envelope["data"]["page_id"]).first()
    site = page.get_site() if page is not None else None
    if site is None or not Channel.objects.filter(site=site, auto_draft=True).exists():
        return
    agent = AgentDefinition.objects.filter(slug=AGENT).first()
    if agent is None:
        log.warning("distribution: no %s agent to draft posts for page %s (run sync_agents)", AGENT, page.pk)
        return
    try:
        start_run(agent, trigger="event", target=page.specific, input={"page_id": page.pk}, event_id=envelope["id"])
    except RunRefused as e:
        log.warning("distribution: page %s was not drafted: %s", page.pk, e)
