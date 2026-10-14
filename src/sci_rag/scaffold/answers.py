"""The validated answer set.

Individual questions cannot see each other, but several answers only make
sense together: offline credentials cannot drive a Google embedder, an
LLM-drafted ontology needs a draft to have actually come back, and choosing
the demo corpus as your corpus means keeping it. Those rules live here, in
one model, so the wizard, an answers file, and any future non-interactive
caller all get the same coercions.

Coercions are deliberate rather than errors: the wizard is a guided setup,
and silently generating a project that cannot start is worse than quietly
correcting an impossible combination. Each coercion is surfaced in the change
log the caller prints.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from sci_rag.config import DEFAULT_LLM_MODEL, LLMProviderName
from sci_rag.domain import DomainConfig, RerankerTuning
from sci_rag.scaffold.naming import slugify
from sci_rag.scaffold.runners import RunnerProfile, get_runner, runner_keys

# Earlier releases showed this hint in the default slot, ccds style, and an
# answers file copied from one of those transcripts can still carry it. Taking
# it literally would write prose into a machine-readable mailto header, so the
# unedited hint still means "no email". The default is empty today.
CONTACT_EMAIL_PLACEHOLDER = "Sent to OpenAlex, Crossref, and Unpaywall"

_YES = {"yes", "y", "true", "1"}
_LICENSE_NONE = "No license file"
_GOOGLE_LLM_MODEL = "gemini-3.6-flash"
_GOOGLE_EMBEDDING_MODEL = "gemini-embedding-001"
_GOOGLE_EMBEDDING_DIM = 1024
_MODELSCOPE_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
_MODELSCOPE_EMBEDDING_DIM = 1024
_WIZARD_DEFAULT_FIELDS = (
    "llm_provider",
    "llm_model",
    "embedding_provider",
    "embedding_model",
    "embedding_dim",
)

CredentialsChoice = Literal["deepseek", "google_ai_studio", "vertex_ai", "offline"]
OntologyChoice = Literal["draft_with_llm", "keep_demo_example", "blank"]
CorpusChoice = Literal["local_files", "openalex_topic", "doi_list", "demo_only"]
LicenseChoice = Literal["BSD-3-Clause", "MIT", "Apache-2.0", "none"]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _YES


class ProjectAnswers(BaseModel):
    project_name: str
    repo_name: str
    description: str = ""
    author_name: str = ""
    contact_email: str = ""
    python_version: Literal["3.11", "3.12"] = "3.12"
    environment_manager: str = "uv"
    dependency_file: Literal["pyproject.toml", "pixi.toml"] = "pyproject.toml"
    credentials: CredentialsChoice = "deepseek"
    google_api_key: str = Field(default="", repr=False, exclude=True)
    deepseek_api_key: str = Field(default="", repr=False, exclude=True)
    gcp_project: str = ""
    embedding_provider: Literal["modelscope", "google", "local-hash"] = "modelscope"
    llm_provider: LLMProviderName = "deepseek"
    llm_model: str = DEFAULT_LLM_MODEL
    extraction_model: str | None = None
    judge_model: str | None = None
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dim: int = 1024
    ontology: OntologyChoice = "keep_demo_example"
    drafted_ontology: DomainConfig | None = None
    corpus_source: CorpusChoice = "local_files"
    openalex_topic: str = ""
    max_results: int = 100
    pdf_parser: Literal["pypdf", "docling"] = "pypdf"
    reranker: Literal["none", "llm", "local_cross_encoder"] = "none"
    include_terraform: bool = True
    include_cloud_database: bool = False
    include_demo_corpus: bool = True
    open_source_license: LicenseChoice = "BSD-3-Clause"
    initialize_git: bool = True
    #: Whether the next-steps block leads with `sci-rag draft ...` or with the
    #: hand-written route. Forced off for an offline project, which has no
    #: model to draft with.
    draft_domain_files: bool = True
    coercions: list[str] = Field(default_factory=list)

    @field_validator("environment_manager")
    @classmethod
    def _known_manager(cls, value: str) -> str:
        if value not in runner_keys():
            raise ValueError(
                f"Unknown environment manager {value!r}. Known: {', '.join(runner_keys())}."
            )
        return value

    @field_validator("contact_email")
    @classmethod
    def _looks_like_an_email(cls, value: str) -> str:
        if value and ("@" not in value or value.startswith("@") or value.endswith("@")):
            raise ValueError(f"contact_email {value!r} does not look like an email address.")
        return value

    @model_validator(mode="after")
    def _resolve_cross_field_rules(self, info: ValidationInfo) -> ProjectAnswers:
        context_fields = info.context.get("explicit_fields") if info.context else None
        explicit_fields = (
            set(context_fields) if context_fields is not None else set(self.model_fields_set)
        )
        explicit_llm_provider = "llm_provider" in explicit_fields
        explicit_llm_model = "llm_model" in explicit_fields
        explicit_embedding_provider = "embedding_provider" in explicit_fields
        explicit_embedding_model = "embedding_model" in explicit_fields
        explicit_embedding_dim = "embedding_dim" in explicit_fields

        if (
            self.credentials in {"google_ai_studio", "vertex_ai"}
            and not explicit_llm_provider
            and self.llm_provider != "google"
        ):
            self.llm_provider = "google"
            self.coercions.append("llm_provider set to google for the selected Google credential")
        if (
            self.credentials == "deepseek"
            and not explicit_llm_provider
            and self.llm_provider != "deepseek"
        ):
            self.llm_provider = "deepseek"
            self.coercions.append(
                "llm_provider set to deepseek for the selected DeepSeek credential"
            )

        expected_llm_model = {
            "google": _GOOGLE_LLM_MODEL,
            "deepseek": DEFAULT_LLM_MODEL,
        }.get(self.llm_provider)
        if expected_llm_model and not explicit_llm_model and self.llm_model != expected_llm_model:
            self.llm_model = expected_llm_model
            self.coercions.append(
                f"llm_model set to {expected_llm_model} for {self.llm_provider} generation"
            )

        if (
            self.credentials in {"google_ai_studio", "vertex_ai"}
            and not explicit_embedding_provider
            and self.embedding_provider != "google"
        ):
            self.embedding_provider = "google"
            self.coercions.append(
                "embedding_provider set to google for the selected Google credential"
            )

        if self.credentials == "offline" and self.embedding_provider != "local-hash":
            self.embedding_provider = "local-hash"
            self.coercions.append(
                "embedding_provider set to local-hash because credentials are offline"
            )

        expected_embedding: tuple[str, int] | None = None
        if self.embedding_provider == "google":
            expected_embedding = (_GOOGLE_EMBEDDING_MODEL, _GOOGLE_EMBEDDING_DIM)
        elif self.embedding_provider == "modelscope":
            expected_embedding = (_MODELSCOPE_EMBEDDING_MODEL, _MODELSCOPE_EMBEDDING_DIM)
        if expected_embedding:
            expected_model, expected_dim = expected_embedding
            if not explicit_embedding_model and self.embedding_model != expected_model:
                self.embedding_model = expected_model
                self.coercions.append(
                    f"embedding_model set to {expected_model} for {self.embedding_provider} embeddings"
                )
            if not explicit_embedding_dim and self.embedding_dim != expected_dim:
                self.embedding_dim = expected_dim
                self.coercions.append(
                    f"embedding_dim set to {expected_dim} for {self.embedding_provider} embeddings"
                )

        if self.ontology == "draft_with_llm" and self.credentials == "offline":
            self.ontology = "keep_demo_example"
            self.drafted_ontology = None
            self.coercions.append(
                "ontology kept as the demo example because drafting needs a model"
            )
        if self.ontology == "draft_with_llm" and self.drafted_ontology is None:
            self.ontology = "keep_demo_example"
            self.coercions.append("ontology kept as the demo example because no draft was accepted")
        if self.draft_domain_files and self.credentials == "offline":
            self.draft_domain_files = False
            self.coercions.append(
                "drafting not offered because an offline project has no model to draft with"
            )
        if self.corpus_source == "demo_only" and not self.include_demo_corpus:
            self.include_demo_corpus = True
            self.coercions.append("demo corpus kept because it is the chosen corpus source")

        self._validate_credential_source_against_generation_roles()

        if not self.repo_name:
            self.repo_name = slugify(self.project_name)
        return self

    def _effective_generation_providers(self) -> set[LLMProviderName]:
        """Resolve every configured generation role to its effective provider."""
        from sci_rag.llm.spec import parse_model_spec

        providers: set[LLMProviderName] = set()
        for model in (self.llm_model, self.extraction_model, self.judge_model):
            if model is None:
                providers.add(self.llm_provider)
            else:
                providers.add(parse_model_spec(model, default_provider=self.llm_provider).provider)
        return providers

    def _validate_credential_source_against_generation_roles(self) -> None:
        allowed_by_credentials: dict[CredentialsChoice, set[LLMProviderName]] = {
            "google_ai_studio": {"google"},
            "deepseek": {"deepseek"},
            "vertex_ai": {"google", "anthropic", "openai-compatible"},
        }
        allowed = allowed_by_credentials.get(self.credentials)
        if allowed is None:
            return

        invalid = self._effective_generation_providers() - allowed
        if not invalid:
            return

        labels = {
            "google": "Google",
            "anthropic": "Anthropic",
            "openai-compatible": "OpenAI-compatible",
            "deepseek": "DeepSeek",
        }
        invalid_labels = ", ".join(sorted(labels[provider] for provider in invalid))
        if self.credentials == "google_ai_studio" and invalid == {"deepseek"}:
            raise ValueError(
                "Google credentials cannot be used with DeepSeek generation. "
                "Select DeepSeek credentials or set the generation provider/model to Google."
            )
        if self.credentials == "deepseek" and invalid == {"google"}:
            raise ValueError(
                "DeepSeek credentials cannot be used with Google generation. "
                "Select Google credentials or set the generation provider/model to DeepSeek."
            )
        if self.credentials == "google_ai_studio":
            fix = "Select Vertex AI credentials or set every generation role to Google."
        elif self.credentials == "deepseek":
            fix = "Select Vertex AI credentials or set every generation role to DeepSeek."
        else:
            fix = (
                "Select DeepSeek credentials or set every generation role to "
                "Google, Anthropic, or OpenAI-compatible."
            )
        raise ValueError(
            f"{self.credentials.replace('_', ' ').title()} credentials cannot be used with "
            f"{invalid_labels} generation. {fix}"
        )

    # --- derived views the appliers use ------------------------------------

    @property
    def runner(self) -> RunnerProfile:
        return get_runner(self.environment_manager)

    @property
    def extras(self) -> list[str]:
        """The optional-dependency groups the answers actually select.

        ``tokenizers`` is not driven by any answer, so it is not listed here;
        it stays in the generated pyproject either way.
        """
        selected = []
        if self.embedding_provider == "modelscope":
            selected.append("modelscope-embedding")
        providers = self._effective_generation_providers()
        if self.credentials != "offline":
            if "anthropic" in providers:
                selected.append("anthropic")
            if providers & {"deepseek", "openai-compatible"}:
                selected.append("openai")
        if self.pdf_parser == "docling":
            selected.append("docling")
        if self.reranker == "local_cross_encoder":
            selected.append("rerank")
        return selected

    def reranker_tuning(self) -> RerankerTuning:
        if self.reranker == "none":
            return RerankerTuning(enabled=False)
        if self.reranker == "llm":
            return RerankerTuning(enabled=True, adapter="llm")
        return RerankerTuning(enabled=True, adapter="local")

    @classmethod
    def from_raw(
        cls,
        raw: dict[str, Any],
        *,
        drafted_ontology: DomainConfig | None = None,
        explicit_fields: set[str] | None = None,
    ) -> ProjectAnswers:
        """Build from the wizard's string answers.

        The wizard collects strings because that is what a terminal gives it;
        this is the one place those strings become typed values.
        """
        data: dict[str, Any] = {k: v for k, v in raw.items() if v is not None}

        email = str(data.get("contact_email", "")).strip()
        data["contact_email"] = "" if email == CONTACT_EMAIL_PLACEHOLDER else email

        for flag in (
            "include_terraform",
            "include_cloud_database",
            "include_demo_corpus",
            "initialize_git",
            "draft_domain_files",
        ):
            if flag in data:
                data[flag] = _as_bool(data[flag])

        if str(data.get("open_source_license", "")) == _LICENSE_NONE:
            data["open_source_license"] = "none"

        if drafted_ontology is not None:
            data["drafted_ontology"] = drafted_ontology

        # Keep every raw value in the payload. The context records which
        # provider fields were actually explicit, so a user-entered value that
        # happens to equal a shipped default is never mistaken for a wizard
        # default and rewritten by cross-field coordination.
        inferred_explicit = {
            field_name
            for field_name in _WIZARD_DEFAULT_FIELDS
            if field_name in data
            and str(data[field_name]) != str(cls.model_fields[field_name].default)
        }
        resolved_explicit_fields = (
            inferred_explicit if explicit_fields is None else set(explicit_fields)
        )
        resolved_explicit_fields.update(inferred_explicit)

        return cls.model_validate(data, context={"explicit_fields": resolved_explicit_fields})
