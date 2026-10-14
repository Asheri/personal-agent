"""Google embeddings via the google-genai SDK.

Works in either credential mode without code changes:

* AI Studio API key (``SCI_RAG_GOOGLE_API_KEY``), the fastest way to start.
* Vertex AI (``SCI_RAG_GCP_PROJECT`` plus application-default credentials),
  the mode labs and teams on Google Cloud will want.
"""

from __future__ import annotations

import asyncio
from typing import Literal

import structlog
from google import genai
from google.genai import types

from sci_rag.config import Settings
from sci_rag.embed.provider import EmbeddingProvider, EmbeddingTask, l2_normalize

log = structlog.get_logger(__name__)

_TASK_TYPES: dict[EmbeddingTask, str] = {
    "document": "RETRIEVAL_DOCUMENT",
    "query": "RETRIEVAL_QUERY",
}

#: Texts per API call. Conservative so a batch never trips request limits.
_BATCH_SIZE = 20
_MAX_ATTEMPTS = 4

#: Which capability is asking for a client. It decides only what a missing
#: credential is reported as, since both capabilities need the same one.
ClientPurpose = Literal["embeddings", "generation"]


_CREDENTIAL_REPAIR = (
    "Set SCI_RAG_GOOGLE_API_KEY (easiest; get one at "
    "https://aistudio.google.com/apikey) or SCI_RAG_GCP_PROJECT "
    "(after `gcloud auth application-default login`)."
)


def make_genai_client(
    settings: Settings,
    *,
    api_key_override: str | None = None,
    purpose: ClientPurpose = "embeddings",
) -> genai.Client:
    """Build the Google client for whichever capability asked for it.

    Both the embedder and ``GoogleLLM`` build their client here, which is why
    ``purpose`` exists. Generation used to fail with the embedder's advice,
    ending on ``SCI_RAG_EMBEDDING_PROVIDER=local-hash``: a setting an offline
    project already has, and one that cannot produce an answer at any value.
    A reader who followed it changed nothing and learned nothing.

    ``api_key_override`` supports the server's bring-your-own-key flow; it is
    used for this client only and never stored or logged.
    """
    if api_key_override:
        return genai.Client(api_key=api_key_override)
    mode = settings.credentials_mode()
    if mode == "api_key":
        return genai.Client(api_key=settings.google_api_key)
    if mode == "vertex":
        return genai.Client(
            vertexai=True, project=settings.gcp_project, location=settings.gcp_location
        )
    if purpose == "generation":
        raise RuntimeError(
            "No LLM provider credentials configured, so this project cannot generate. "
            f"{_CREDENTIAL_REPAIR} Ingestion, retrieval, and retrieval evaluation "
            "keep working without one. SCI_RAG_EMBEDDING_PROVIDER selects an "
            "embedder and cannot enable generation."
        )
    raise RuntimeError(
        f"No Google credentials configured. {_CREDENTIAL_REPAIR} For a "
        "no-credential dry run, set SCI_RAG_EMBEDDING_PROVIDER=local-hash."
    )


class GoogleEmbedder(EmbeddingProvider):
    def __init__(self, settings: Settings, *, client: genai.Client | None = None) -> None:
        self._settings = settings
        self._client = client or make_genai_client(settings)
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self.version = f"{self.model}@{self.dim}"

    async def embed(self, texts: list[str], *, task: EmbeddingTask) -> list[list[float]]:
        results: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            response = await self._embed_with_retry(batch, task)
            for item in response.embeddings or []:
                vector = list(item.values or [])
                results.append(self.assert_dimension(l2_normalize(vector)))
        if len(results) != len(texts):
            raise RuntimeError(
                f"Embedding API returned {len(results)} vectors for {len(texts)} texts."
            )
        return results

    async def _embed_with_retry(
        self, batch: list[str], task: EmbeddingTask
    ) -> types.EmbedContentResponse:
        config = types.EmbedContentConfig(
            task_type=_TASK_TYPES[task],
            output_dimensionality=self.dim,
        )
        delay = 1.0
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await self._client.aio.models.embed_content(
                    model=self.model, contents=batch, config=config
                )
            except Exception as exc:
                if attempt == _MAX_ATTEMPTS or not _is_retryable(exc):
                    raise
                log.warning(
                    "embedding_retry", attempt=attempt, delay_s=delay, error=type(exc).__name__
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")


def _is_retryable(exc: Exception) -> bool:
    text = str(exc)
    return any(
        marker in text for marker in ("429", "503", "500", "RESOURCE_EXHAUSTED", "UNAVAILABLE")
    )
