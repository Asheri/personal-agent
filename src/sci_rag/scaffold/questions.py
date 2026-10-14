"""The question list: one declaration, used by the wizard and by the docs.

Order is the user-visible contract. It mirrors the shape a scientist expects
when starting a project: identity, then credentials and models, then the
domain itself, then the corpus, then stack choices, then licensing and git.

Every question has a default, so pressing Enter through the whole session
produces a working project rather than a half-configured one. Questions that
only make sense after an earlier answer carry an ``asked_when`` gate instead
of being asked unconditionally and then ignored.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from sci_rag.config import DEFAULT_LLM_MODEL
from sci_rag.scaffold.naming import slugify
from sci_rag.scaffold.runners import runner_keys

Answers = Mapping[str, str]

SUPPORTED_PYTHON_VERSIONS = ("3.11", "3.12")
_GOOGLE_LLM_MODEL = "gemini-3.6-flash"
_GOOGLE_EMBEDDING_MODEL = "gemini-embedding-001"
_GOOGLE_EMBEDDING_DIM = "1024"
_MODELSCOPE_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
_MODELSCOPE_EMBEDDING_DIM = "1024"


def _embedding_provider_default(answers: Answers) -> str:
    if answers.get("credentials") in {"google_ai_studio", "vertex_ai"}:
        return "google"
    return "modelscope"


def _llm_model_default(answers: Answers) -> str:
    if answers.get("credentials") in {"google_ai_studio", "vertex_ai"}:
        return _GOOGLE_LLM_MODEL
    return DEFAULT_LLM_MODEL


def _embedding_model_default(answers: Answers) -> str:
    if answers.get("embedding_provider") == "google":
        return _GOOGLE_EMBEDDING_MODEL
    return _MODELSCOPE_EMBEDDING_MODEL


def _embedding_dim_default(answers: Answers) -> str:
    if answers.get("embedding_provider") == "google":
        return _GOOGLE_EMBEDDING_DIM
    return _MODELSCOPE_EMBEDDING_DIM


@dataclass(frozen=True)
class Question:
    """One prompt.

    ``default`` may be a callable so a question can derive its suggestion from
    an earlier answer (``repo_name`` from ``project_name``). ``validator``
    returns the normalized value or raises :class:`ValueError` with a message
    the wizard shows before asking again.
    """

    name: str
    prompt: str
    default: str | Callable[[Answers], str]
    # What `--defaults` uses when the interactive default needs a person.
    # Drafting an ontology is the only such answer today: it is the right
    # first suggestion when somebody is there to accept the draft, and not a
    # thing an unattended run can do. See #164.
    noninteractive_default: str | None = None
    choices: tuple[str, ...] | None = None
    label: str = ""
    choice_help: Mapping[str, str] = field(default_factory=dict)
    quick: bool = False
    secret: bool = False
    help: str = ""
    asked_when: Callable[[Answers], bool] | None = None
    validator: Callable[[str], str] | None = None


def _validate_python_version(value: str) -> str:
    if value not in SUPPORTED_PYTHON_VERSIONS:
        raise ValueError(
            f"Python {value} is not supported. Choose one of "
            f"{' or '.join(SUPPORTED_PYTHON_VERSIONS)}."
        )
    return value


def _validate_positive_int(value: str) -> str:
    try:
        parsed = int(value)
    except ValueError:
        raise ValueError(f"{value!r} is not a whole number.") from None
    if parsed <= 0:
        raise ValueError("Must be greater than zero.")
    return str(parsed)


def _validate_email(value: str) -> str:
    if value and ("@" not in value or value.startswith("@") or value.endswith("@")):
        raise ValueError(f"{value!r} does not look like an email address.")
    return value


QUESTIONS: tuple[Question, ...] = (
    Question(
        "project_name",
        "project_name",
        "My Scientific KB",
        label="What is your project called?",
        quick=True,
    ),
    Question(
        "repo_name",
        "repo_name",
        lambda a: slugify(a.get("project_name", "")),
        label="Repository directory name",
    ),
    Question(
        "description",
        "description",
        "A short description of your domain.",
        label="One line about your field",
        quick=True,
    ),
    Question(
        "author_name",
        "author_name",
        "Your name, lab, or organization",
        label="Who should the project credit?",
    ),
    Question(
        "contact_email",
        "contact_email",
        "",
        label="Contact email",
        quick=True,
        validator=_validate_email,
        help=(
            "Sent with each request to OpenAlex, Crossref, and Unpaywall, which serve "
            "identified callers faster. Blank is allowed."
        ),
    ),
    Question(
        "python_version",
        "python_version",
        "3.12",
        choices=SUPPORTED_PYTHON_VERSIONS,
        label="Python version",
        choice_help={
            "3.11": "The oldest version supported by this release",
            "3.12": "The current recommended runtime",
        },
        validator=_validate_python_version,
    ),
    Question(
        "environment_manager",
        "environment_manager",
        # Derived, so registering a profile can never leave this list stale.
        lambda _a: runner_keys()[0],
        choices=tuple(runner_keys()),
        label="Environment manager",
        choice_help={
            "uv": "Fast Python environments and locking with uv",
            "pixi": "Conda packages and Python dependencies in one project",
            "conda": "A conventional conda environment plus pip dependencies",
            "venv+pip": "Standard-library virtual environment and pip",
        },
        quick=True,
    ),
    Question(
        "dependency_file",
        "dependency_file",
        "pyproject.toml",
        choices=("pyproject.toml", "pixi.toml"),
        label="Where should pixi dependencies live?",
        choice_help={
            "pyproject.toml": "Keep project and pixi dependencies together",
            "pixi.toml": "Keep pixi configuration in its own file",
        },
        asked_when=lambda a: a.get("environment_manager") == "pixi",
    ),
    Question(
        "credentials",
        "credentials",
        "deepseek",
        choices=("deepseek", "google_ai_studio", "vertex_ai", "offline"),
        label="How will you reach a model?",
        choice_help={
            "deepseek": "DeepSeek generation with a dedicated API key",
            "google_ai_studio": "Shortest local setup; no manual Cloud setup",
            "vertex_ai": "Billed through a Google Cloud project you already have",
            "offline": "No model calls, graph extraction, or generated answers",
        },
        quick=True,
    ),
    Question(
        "deepseek_api_key",
        "deepseek_api_key",
        "",
        label="DeepSeek API key",
        quick=True,
        secret=True,
        help="Create one in the DeepSeek platform. Blank to add it later.",
        asked_when=lambda a: a.get("credentials") == "deepseek",
    ),
    Question(
        "google_api_key",
        "google_api_key",
        "",
        label="Google AI Studio API key",
        quick=True,
        secret=True,
        help="Get one at https://aistudio.google.com/apikey. Blank to add it later.",
        asked_when=lambda a: a.get("credentials") == "google_ai_studio",
    ),
    Question(
        "gcp_project",
        "gcp_project",
        "",
        label="Google Cloud project ID",
        quick=True,
        help="Uses Application Default Credentials. Run gcloud auth application-default login.",
        asked_when=lambda a: a.get("credentials") == "vertex_ai",
    ),
    Question(
        "embedding_provider",
        "embedding_provider",
        _embedding_provider_default,
        choices=("modelscope", "google", "local-hash"),
        label="Embedding provider",
        choice_help={
            "modelscope": "Local Qwen3 embeddings downloaded through ModelScope",
            "google": "Semantic embeddings from the configured Google model",
            "local-hash": "Deterministic offline vectors for development and tests",
        },
        # Offline projects have no provider to choose; answers.py forces it.
        asked_when=lambda a: a.get("credentials") != "offline",
    ),
    Question("llm_model", "llm_model", _llm_model_default, label="Generation model"),
    Question(
        "embedding_model",
        "embedding_model",
        _embedding_model_default,
        label="Embedding model",
    ),
    Question(
        "embedding_dim",
        "embedding_dim",
        _embedding_dim_default,
        label="Embedding dimensions",
        validator=_validate_positive_int,
    ),
    Question(
        "ontology",
        "ontology",
        "draft_with_llm",
        noninteractive_default="keep_demo_example",
        choices=("draft_with_llm", "keep_demo_example", "blank"),
        label="Starting ontology",
        choice_help={
            "draft_with_llm": "Draft field-specific types from your description",
            "keep_demo_example": "Keep the worked agricultural-residue ontology for now",
            "blank": "Start with an intentionally empty ontology",
        },
    ),
    Question(
        "corpus_source",
        "corpus_source",
        "local_files",
        choices=("local_files", "openalex_topic", "doi_list", "demo_only"),
        label="Where will the first documents come from?",
        choice_help={
            "local_files": "Add PDFs, HTML, Markdown, or text files from disk",
            "openalex_topic": "Discover a legal corpus from an OpenAlex topic",
            "doi_list": "Resolve a list of known DOI records",
            "demo_only": "Keep the bundled synthetic corpus for evaluation",
        },
        quick=True,
    ),
    Question(
        "openalex_topic",
        "openalex_topic",
        "your topic",
        label="OpenAlex topic",
        asked_when=lambda a: a.get("corpus_source") == "openalex_topic",
    ),
    Question(
        "max_results",
        "max_results",
        "100",
        label="Maximum OpenAlex results",
        validator=_validate_positive_int,
        asked_when=lambda a: a.get("corpus_source") == "openalex_topic",
    ),
    Question(
        "pdf_parser",
        "pdf_parser",
        "pypdf",
        choices=("pypdf", "docling"),
        label="PDF parser",
        choice_help={
            "pypdf": "Lightweight text extraction with no machine-learning stack",
            "docling": "Structure-aware parsing with stronger table extraction",
        },
    ),
    Question(
        "reranker",
        "reranker",
        "none",
        choices=("none", "llm", "local_cross_encoder"),
        label="Result reranker",
        choice_help={
            "none": "Return the fused ranking as-is",
            "llm": "Ask the configured model to reorder retrieved passages",
            "local_cross_encoder": "Run a local cross-encoder model",
        },
    ),
    Question(
        "include_terraform",
        "include_terraform",
        "Yes",
        choices=("Yes", "No"),
        label="Keep production Terraform?",
        choice_help={
            "Yes": "Keep the optional Cloud Run and Cloud SQL deployment module",
            "No": "Remove production infrastructure files and their CI job",
        },
    ),
    Question(
        "include_cloud_database",
        "include_cloud_database",
        "No",
        choices=("Yes", "No"),
        label="Include the Cloud SQL development helper?",
        choice_help={
            "Yes": "Keep the opt-in shared development database helper",
            "No": "Use Docker, conda-forge, or another PostgreSQL server",
        },
        help="Include the opt-in Cloud SQL development helper and Terraform module.",
    ),
    Question(
        "include_demo_corpus",
        "include_demo_corpus",
        "Yes",
        choices=("Yes", "No"),
        label="Keep the demo corpus?",
        choice_help={
            "Yes": "Keep five synthetic documents for a known-good first run",
            "No": "Remove the demo and examples from the generated project",
        },
    ),
    Question(
        "open_source_license",
        "open_source_license",
        "BSD-3-Clause",
        choices=("BSD-3-Clause", "MIT", "Apache-2.0", "No license file"),
        label="Open-source license",
        choice_help={
            "BSD-3-Clause": "Permissive license with non-endorsement protection",
            "MIT": "Short permissive license",
            "Apache-2.0": "Permissive license with an explicit patent grant",
            "No license file": "Do not grant redistribution rights yet",
        },
    ),
    Question(
        "initialize_git",
        "initialize_git",
        "Yes",
        choices=("Yes", "No"),
        label="Initialize a Git repository?",
        choice_help={
            "Yes": "Create a repository and make the generated baseline commit",
            "No": "Leave version-control setup to you",
        },
    ),
    Question(
        "draft_domain_files",
        "draft_domain_files",
        "Yes",
        choices=("Yes", "No"),
        label="Draft the remaining domain files next?",
        choice_help={
            "Yes": "Put the corpus-grounded drafting commands in next steps",
            "No": "Point next steps at the hand-written route",
        },
        # An offline project has no model to draft with, and the copy-paste
        # lane is a manual step nobody should be volunteered for by a default.
        asked_when=lambda a: a.get("credentials") != "offline",
    ),
)


def default_for(question: Question, answers: Answers) -> str:
    if callable(question.default):
        return question.default(answers)
    return question.default


def is_asked(question: Question, answers: Answers) -> bool:
    return question.asked_when is None or question.asked_when(answers)


def default_answers() -> dict[str, str]:
    """Walk the list applying every default, honouring the gates.

    This is what ``--defaults`` answers with, and it is the base an answers
    file overrides, so a partial file still produces a complete answer set.
    """
    answers: dict[str, str] = {}
    for question in QUESTIONS:
        if is_asked(question, answers):
            answers[question.name] = default_for(question, answers)
    return answers
