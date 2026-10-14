"""The REST API contract, as Pydantic models.

Everything an integrator needs to know about a request or response is in
this file (and rendered into OpenAPI at /docs automatically). Field
constraints here are the API's input validation; keep them honest.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr


class QueryRequest(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=2000, description="The question to search for."
    )
    top_k: int = Field(8, ge=1, le=50, description="How many fused results to return.")
    profile: Literal["interactive", "deep", "auto"] = Field(
        "interactive",
        description=(
            "interactive = vector+keyword, fast; deep = all five layers; "
            "auto = a cheap router picks per query (response traces show its decision)."
        ),
    )
    include_graph: bool | None = Field(None, description="Override the profile's graph layer.")
    include_community: bool | None = Field(None, description="Override the community layer.")
    include_hyde: bool | None = Field(None, description="Override the HyDE layer.")
    include_rerank: bool | None = Field(
        None, description="Override the post-fusion reranker (off unless the domain enables it)."
    )
    license_classes: list[str] | None = Field(
        None,
        description="Allowlist of license classes; omit for all. An empty list returns nothing.",
    )
    sources: list[str] | None = Field(None, description="Allowlist of document sources.")
    year_min: int | None = Field(
        None, ge=1000, le=2200, description="Earliest publication year to include."
    )
    year_max: int | None = Field(
        None, ge=1000, le=2200, description="Latest publication year to include."
    )
    authors: list[str] | None = Field(
        None,
        description=(
            "Keep only documents with at least one of these authors, matched exactly "
            "against the stored author strings."
        ),
    )
    journals: list[str] | None = Field(
        None, description="Keep only documents published in one of these journals."
    )
    exclude_dois: list[str] | None = Field(
        None, description="Drop these DOIs (for example a paper already under review)."
    )
    include_content: bool = Field(
        True, description="Set false to omit chunk text (lean responses)."
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "How much rice straw was generated in the Colusa Basin in 2023?",
                    "top_k": 5,
                    "profile": "deep",
                }
            ]
        }
    }


class StageTraceModel(BaseModel):
    stage: str
    status: str
    duration_ms: int
    candidate_count: int


class RetrievedItemModel(BaseModel):
    kind: Literal["chunk", "community"]
    id: str
    score: float
    layers: list[str]
    title: str
    content: str | None = None
    document_id: str | None = None
    section_path: str | None = None
    citation: str | None = None
    license_class: str
    source: str
    is_table: bool = False


class QueryResponse(BaseModel):
    request_id: str
    profile: str
    items: list[RetrievedItemModel]
    traces: list[StageTraceModel]
    degraded_stages: list[str] = Field(
        default_factory=list,
        description="Layers that timed out or errored; results are still valid, just narrower.",
    )


class AnswerRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(8, ge=1, le=20, description="Sources given to the model.")
    profile: Literal["interactive", "deep"] = "deep"
    max_tokens: int = Field(2048, ge=64, le=8192)
    stream: bool = Field(True, description="true = Server-Sent Events; false = one JSON response.")
    include_compression: bool | None = Field(
        None,
        description=(
            "Override question-aware source compression. Otherwise use the evaluated domain "
            "default."
        ),
    )
    license_classes: list[str] | None = None
    sources: list[str] | None = None
    year_min: int | None = Field(
        None, ge=1000, le=2200, description="Earliest publication year to include."
    )
    year_max: int | None = Field(
        None, ge=1000, le=2200, description="Latest publication year to include."
    )
    authors: list[str] | None = Field(
        None,
        description=(
            "Keep only documents with at least one of these authors, matched exactly "
            "against the stored author strings."
        ),
    )
    journals: list[str] | None = Field(
        None, description="Keep only documents published in one of these journals."
    )
    exclude_dois: list[str] | None = Field(
        None, description="Drop these DOIs (for example a paper already under review)."
    )
    llm_api_key: SecretStr | None = Field(
        None,
        description=(
            "Bring your own Google AI Studio key for the generation call. Requires the "
            "byo_llm scope. Used only for this request; never stored or logged."
        ),
    )


class CitationModel(BaseModel):
    index: int
    kind: str
    title: str
    citation: str | None
    license_class: str
    document_id: str | None
    chunk_id: str | None
    section_path: str | None
    cited: bool


class AnswerResponse(BaseModel):
    request_id: str
    answer: str
    model: str
    citations: list[CitationModel]
    traces: list[StageTraceModel]
    degraded_stages: list[str] = Field(default_factory=list)
    prompt_tokens_before: int
    prompt_tokens_after: int
    compression_failure_count: int
    compression_dropped_count: int


class DocumentSummary(BaseModel):
    id: str
    title: str
    source: str
    license_class: str
    authors: list[str]
    publication_year: int | None
    doi: str | None
    chunk_count: int
    ingested_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]
    total: int
    page: int
    page_size: int


class ChunkPreview(BaseModel):
    id: str
    chunk_index: int
    section_path: str | None
    is_table: bool
    preview: str


class DocumentDetail(DocumentSummary):
    source_ref: str | None
    formatted_citation: str | None
    page_count: int | None
    chunks: list[ChunkPreview]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str = "sci-rag"
    version: str
    database: bool


class StatsResponse(BaseModel):
    documents: int
    chunks: int
    entities: int
    relationships: int
    communities: int
    license_classes: dict[str, int]
    sources: dict[str, int]
    embedding_versions: dict[str, int]


class CorpusManifest(BaseModel):
    """The machine-readable descriptor a multi-RAG router reads to decide
    whether this knowledge base fits a query. Public by design."""

    name: str
    description: str
    domain: str
    kit: str = "sci-rag-kit"
    kit_version: str
    stats: dict[str, Any]
    embedding: dict[str, Any]
    retrieval: dict[str, Any]
    endpoints: dict[str, str]
    features: dict[str, bool]
