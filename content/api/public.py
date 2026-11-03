"""What the public read surfaces may show of the image and document libraries:
the files a live, public page references — Wagtail's `ReferenceIndex`, which
holds what each page's row references (a preview image, a chooser block, a
rich-text embed), and a page's row is its live content once it is published.
A draft's files, an unpublished change's and a file nothing uses stay out.

One rule for REST's `images/` and `documents/` (api/urls.py) and GraphQL's
`image(s)` and `document(s)` (api/graphql.py), so neither shows what the other
hides. Signed renditions and the studio's media library are PLAN G6.
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import CharField
from django.db.models.functions import Cast
from wagtail.models import Page, ReferenceIndex


def referenced_by_live_pages(queryset):
    """`queryset` (images or documents) narrowed to the rows a live, public page references."""
    pages = Page.objects.live().public().annotate(key=Cast("pk", CharField())).values("key")
    referenced = ReferenceIndex.objects.filter(
        base_content_type=ContentType.objects.get_for_model(Page),
        object_id__in=pages,
        to_content_type=ContentType.objects.get_for_model(queryset.model),
    ).values("to_object_id")
    # The index keys every object by a string, so the row's key is compared as one.
    return queryset.alias(key=Cast("pk", CharField())).filter(key__in=referenced)
