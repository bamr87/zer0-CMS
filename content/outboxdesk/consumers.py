"""The outbox desk's handler on the platform's own event stream (`zer0:content`): a page that went live is announced
on the belt as a `published` handoff from the publisher station (services.publish_page).

It rides the transactional outbox: the publish and its `content.page.published` event commit together, the relay
puts the event on the stream, and this handler — run by `manage.py consume_events --stream zer0:content --group
outboxdesk` (the compose `belt-publisher` service) — writes the handoff once per event (outbox/consumers.py records
it in `ProcessedEvent`; the handoff's id comes from the event's, so a redelivery after a lost commit sends nothing).
Nothing writes a belt file from the request or the signal that published the page.
"""

from outbox.consumers import handler

from .services import publish_page

CONSUMER = "outboxdesk.belt"


@handler("content.page.published", consumer=CONSUMER)
def page_published(envelope: dict) -> None:
    publish_page(envelope)
