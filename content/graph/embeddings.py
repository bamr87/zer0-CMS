"""Turning text into vectors.

`HashingEmbedder` is the default: feature hashing of word unigrams and
bigrams into `EMBEDDING_DIMENSIONS` signed buckets, L2-normalised. It needs no
model, no network and no randomness, so related pages and semantic search
work — modestly — on a laptop and give the same answer in every test run.
`LiteLLMEmbedder` calls a real embedding model when `EMBEDDING_BACKEND=litellm`
(imported lazily, like the LLM backend). Either way the vector is stored with
the model's name, and vectors of different models are never compared.
"""

import hashlib
import math
import re

from django.conf import settings

WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def tokens(text: str) -> list[str]:
    words = WORD.findall((text or "").lower())
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]


class HashingEmbedder:
    def __init__(self, dimensions: int | None = None, model: str | None = None):
        self.dimensions = dimensions or settings.EMBEDDING_DIMENSIONS
        self.model = model or settings.EMBEDDING_MODEL

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in tokens(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[bucket] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector] if norm else vector


class LiteLLMEmbedder:
    def __init__(self, model: str | None = None):
        self.model = model or settings.EMBEDDING_MODEL
        self.dimensions = settings.EMBEDDING_DIMENSIONS

    def embed(self, text: str) -> list[float]:
        import litellm  # noqa: PLC0415 — optional, deployment-time dependency

        response = litellm.embedding(model=self.model, input=[text])
        return [float(x) for x in response.data[0]["embedding"]]


def get_embedder():
    return LiteLLMEmbedder() if settings.EMBEDDING_BACKEND == "litellm" else HashingEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
