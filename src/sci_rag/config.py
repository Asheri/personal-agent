"""Runtime configuration for sci-rag-kit.

Everything is driven by environment variables with the ``SCI_RAG_`` prefix
(or a local ``.env`` file; see ``.env.example`` for a guided tour). Domain
semantics (ontology, prompts, retrieval weights) live in ``domain/domain.yaml``
instead, so that pointing the kit at a new field never means editing
Python.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from sci_rag.llm.spec import ModelSpec

CredentialsMode = Literal["api_key", "vertex", "none"]

#: Generation backends exposed by the model-spec contract. Each name must have
#: a matching adapter before runtime generation can use it.
LLMProviderName = Literal["google", "anthropic", "openai-compatible", "deepseek"]

#: Where a generation call comes from. Each role resolves to its own model
#: spec so a cheap model can do high-volume extraction while a stronger one
#: writes answers, and a *different* one grades them.
LLMRole = Literal["answer", "extraction", "judge"]

#: The settings that name a generation model. Writing any of them is how a
#: user says they intend to generate, so a project that has changed one is
#: not offline no matter what its credentials look like.
_GENERATION_MODEL_FIELDS = ("llm_provider", "llm_model", "extraction_model", "judge_model")


#: The generation model a fresh install uses, named once so the wizard, the
#: scaffolder, the preflight, and the settings cannot drift apart.
#:
#: `tests/cloud/test_default_model_live.py` checks this against a real
#: endpoint; nothing offline can prove that a remote model is still served.
DEFAULT_LLM_MODEL = "deepseek-flash"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCI_RAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://sci_rag:sci_rag@localhost:5433/sci_rag"

    # --- Google credentials (either an AI Studio key or a GCP project) ------
    google_api_key: str | None = None
    gcp_project: str | None = None
    gcp_location: str = "us-central1"

    # --- Credentials for the non-Google generation providers ----------------
    # Anthropic on Vertex uses ``gcp_project`` and application-default
    # credentials; this key is only for the direct Anthropic API.
    anthropic_api_key: str | None = None
    # The OpenAI-compatible provider points at Vertex Model Garden by default
    # (Grok, Llama, Mistral, DeepSeek) using application-default credentials.
    # Set a base URL to target OpenAI itself or a self-hosted server instead.
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"

    # --- Embeddings ---------------------------------------------------------
    # "modelscope" ships Qwen3 embeddings in this configuration.
    # "google" uses gemini-embedding-001 through whichever credential mode is
    # configured. "local-hash" is a deterministic, offline embedder for tests
    # and pipeline dry runs; its rankings are lexical, not semantic.
    embedding_provider: Literal["modelscope", "google", "local-hash"] = "modelscope"
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    # ModelScope 与 SentenceTransformer 共用的本地运行设置。
    modelscope_device: str = "auto"
    modelscope_cache_dir: str | None = None
    # ModelScope embeddings are fixed at 1024 dimensions here. The database
    # column is created with this dimension, so changing it after ingestion
    # requires a migration plus a re-embedding pass.
    embedding_dim: int = 1024

    # --- Generation (answers, graph extraction, HyDE, summaries) ------------
    # The provider a bare model id belongs to. Any model setting below may
    # override it inline as "provider:model".
    llm_provider: LLMProviderName = "deepseek"
    llm_model: str = DEFAULT_LLM_MODEL
    # Cheap-and-fast model for high-volume extraction calls. Defaults to
    # ``llm_model`` when unset.
    extraction_model: str | None = None
    # Model for the evaluation judge. Pointing it at a different provider than
    # ``llm_model`` avoids grading a model's answers with its own family.
    judge_model: str | None = None

    @field_validator("deepseek_base_url")
    @classmethod
    def _validate_deepseek_base_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("deepseek_base_url must not be empty.")
        return value

    @field_validator("modelscope_device")
    @classmethod
    def _validate_modelscope_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        cuda_index = normalized.removeprefix("cuda:")
        is_cuda_index = (
            normalized.startswith("cuda:")
            and bool(cuda_index)
            and all("0" <= character <= "9" for character in cuda_index)
        )
        if normalized in {"auto", "cpu", "cuda"} or is_cuda_index:
            return normalized
        raise ValueError(
            "modelscope_device must be auto, cpu, cuda, or cuda:N "
            "(case-insensitive; surrounding whitespace is ignored)."
        )

    @model_validator(mode="after")
    def _validate_embedding_dimension(self) -> Settings:
        if self.embedding_provider == "modelscope" and not 32 <= self.embedding_dim <= 1024:
            raise ValueError("embedding_dim must be between 32 and 1024 for modelscope.")
        return self

    # --- Retrieval stage timeouts (seconds) ---------------------------------
    # "interactive" keeps a user waiting; "deep" is for offline/agent use.
    # Both bound a stage's own database work.
    interactive_stage_timeout_s: float = 8.0
    deep_stage_timeout_s: float = 30.0
    # Four of the five stages call an embedding or generation provider before
    # they reach SQL, and a remote round trip has nothing to do with how long
    # a database stage should take. Charging one to the other made a supported
    # live Vertex project return nothing: its query embedding took 33 seconds
    # against a 30-second budget, and every stage sharing that embedding
    # failed together. Those stages get this in addition to the budget above.
    provider_call_timeout_s: float = 60.0

    # --- Paths --------------------------------------------------------------
    domain_dir: Path = Path("domain")
    data_dir: Path = Path("data")

    # --- Server -------------------------------------------------------------
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    # JSON map of API key -> {"scopes": [...], ...}. Unset means the server
    # runs open (fine on localhost; it warns loudly at startup).
    api_keys: str | None = None
    cors_origins: str = "*"

    @property
    def resolved_extraction_model(self) -> str:
        return self.extraction_model or self.llm_model

    @property
    def resolved_judge_model(self) -> str:
        return self.judge_model or self.llm_model

    def model_spec_for(self, role: LLMRole) -> ModelSpec:
        """The provider and model id a given call site should use."""
        # Imported here because sci_rag.llm imports this module; the lazy
        # import keeps the package graph acyclic.
        from sci_rag.llm.spec import parse_model_spec

        raw = {
            "answer": self.llm_model,
            "extraction": self.resolved_extraction_model,
            "judge": self.resolved_judge_model,
        }[role]
        return parse_model_spec(raw, default_provider=self.llm_provider)

    def credentials_mode(self) -> CredentialsMode:
        """Which Google credential path is configured, if any.

        An explicit API key wins over a Vertex project so that a laptop user
        with both can predict what happens. This covers embeddings and the
        Google generation provider; the other providers carry their own
        credentials.
        """
        if self.google_api_key:
            return "api_key"
        if self.gcp_project:
            return "vertex"
        return "none"

    def is_offline(self) -> bool:
        """Whether this project asks anything of a model provider at all.

        Running with no credentials is a supported mode, not a half-finished
        setup: the deterministic local embedder ingests, retrieves, and scores
        without a single model call, and the setup wizard writes exactly this
        configuration for ``credentials: offline``. Diagnostics use the answer
        to tell "these features are switched off" apart from "these features
        are broken".

        Three conditions have to hold together, and each one is there to stop
        a real misconfiguration from being read as a deliberate choice:

        - The embedder is the local one. A Google embedder with no credentials
          cannot embed anything, so that project is broken rather than offline.
        - No provider credential is set anywhere. A project holding one is
          reaching for a model, which makes a second missing credential a gap.
        - Every generation model setting is still the current shipped default
          or the previous Google default, so an existing offline project does
          not become cloud intent merely because the default changed.
        """
        if self.embedding_provider != "local-hash":
            return False
        if self.credentials_mode() != "none":
            return False
        if self.anthropic_api_key or self.openai_api_key or self.openai_base_url:
            return False
        fields = type(self).model_fields
        if self.deepseek_api_key or self.deepseek_base_url != fields["deepseek_base_url"].default:
            return False
        current_defaults = all(
            getattr(self, name) == fields[name].default for name in _GENERATION_MODEL_FIELDS
        )
        legacy_google_defaults = (
            self.llm_provider == "google"
            and self.llm_model == "gemini-3.6-flash"
            and self.extraction_model is None
            and self.judge_model is None
        )
        return current_defaults or legacy_google_defaults


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test hook: force settings to be re-read from the environment."""
    get_settings.cache_clear()
