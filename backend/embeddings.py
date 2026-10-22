import logging
import math
import os
from typing import Any

from openai import OpenAI, OpenAIError


LOGGER = logging.getLogger(__name__)
OPENROUTER_EMBEDDING_MODEL = "nvidia/nemotron-3.5-embed-1b:free"
EMBEDDING_DIMENSIONS = 2048
MINIMUM_COSINE_SIMILARITY = 0.45


class EmbeddingProviderError(RuntimeError):
    pass


class OpenRouterEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = OPENROUTER_EMBEDDING_MODEL,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise EmbeddingProviderError(
                "OpenRouter embeddings are selected but OPENROUTER_API_KEY is not set."
            )
        if not model.strip():
            raise EmbeddingProviderError(
                "FOODIES_OPENROUTER_EMBEDDING_MODEL must not be blank."
            )
        self.model = model.strip()
        self.client = client or OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=30.0,
            max_retries=1,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=texts,
            )
        except OpenAIError as exc:
            LOGGER.warning(
                "OpenRouter embedding request failed: error_type=%s status_code=%s error_code=%s request_id=%s",
                type(exc).__name__,
                getattr(exc, "status_code", None),
                getattr(exc, "code", None),
                getattr(exc, "request_id", None),
            )
            raise EmbeddingProviderError(
                "The embedding service is temporarily unavailable."
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise EmbeddingProviderError(
                "The embedding service is temporarily unavailable."
            ) from exc

        vectors: list[list[float] | None] = [None] * len(texts)
        for item in response.data:
            index = item.index
            if not isinstance(index, int) or not 0 <= index < len(texts):
                raise EmbeddingProviderError(
                    "The embedding service returned an invalid response."
                )
            values = item.embedding
            if len(values) != EMBEDDING_DIMENSIONS:
                raise EmbeddingProviderError(
                    "The embedding service returned an unexpected vector size."
                )
            try:
                vector = [float(value) for value in values]
            except (TypeError, ValueError, OverflowError) as exc:
                raise EmbeddingProviderError(
                    "The embedding service returned invalid vector values."
                ) from exc
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingProviderError(
                    "The embedding service returned invalid vector values."
                )
            if vectors[index] is not None:
                raise EmbeddingProviderError(
                    "The embedding service returned duplicate results."
                )
            vectors[index] = vector

        if any(vector is None for vector in vectors):
            raise EmbeddingProviderError(
                "The embedding service returned an incomplete response."
            )
        return [vector for vector in vectors if vector is not None]


def configured_embedding_provider() -> OpenRouterEmbeddingProvider | None:
    provider = os.getenv("FOODIES_EMBEDDING_PROVIDER", "none").strip().casefold()
    if provider in {"", "none", "disabled"}:
        return None
    if provider != "openrouter":
        raise EmbeddingProviderError(
            "FOODIES_EMBEDDING_PROVIDER must be 'none' or 'openrouter'."
        )
    api_key = os.getenv("FOODIES_OPENROUTER_EMBEDDING_API_KEY", "").strip()
    if not api_key:
        api_key = os.getenv("OPENROUTER_API_KEY", "")
    return OpenRouterEmbeddingProvider(
        api_key=api_key,
        model=os.getenv(
            "FOODIES_OPENROUTER_EMBEDDING_MODEL",
            OPENROUTER_EMBEDDING_MODEL,
        ),
    )
