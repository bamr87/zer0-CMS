"""The ideas app's Celery task: an idea's vector stored once its text is saved, so clusters and duplicates are read
from stored vectors and no request ever waits on an embedding model."""

from celery import shared_task

from .models import Idea
from .services import embed


@shared_task
def embed_idea(pk: int) -> bool:
    idea = Idea.objects.filter(pk=pk).first()
    return embed(idea) if idea is not None else False
