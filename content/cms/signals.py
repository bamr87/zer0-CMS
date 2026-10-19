"""What happens when a page is published, in one place and one order.

Wagtail sends `page_published` from inside the publish; every request is one
transaction (`ATOMIC_REQUESTS`), so the graph rows and the outbox event written
here commit with the page or not at all. Graph first, so the event a consumer
reads describes a page whose edges and vector are already in place.
"""

from django.db import transaction
from django.dispatch import receiver
from wagtail.signals import page_published


@receiver(page_published)
def on_page_published(sender, instance, revision, **kwargs):
    from graph.services import index_page
    from outbox.services import emit

    page = instance.specific
    with transaction.atomic():
        index_page(page)
        emit(
            "content.page.published",
            subject=f"page:{page.pk}",
            data={
                "page_id": page.pk,
                "revision_id": revision.pk if revision else None,
                "locale": page.locale.language_code,
                "content_hash": page.compute_content_hash(),
                "url_path": page.url_path,
                "page_type": page._meta.label,
            },
        )
