"""ProjectAnswers validates the whole answer set, not one field at a time.

Several answers only make sense together: offline credentials cannot use a
Google embedder, and an LLM-drafted ontology needs a draft to have actually
come back.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sci_rag.domain import DomainConfig, EntityTypeSpec
from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.questions import default_answers


def _answers(**overrides: object) -> ProjectAnswers:
    raw = dict(default_answers())
    raw.update({k: str(v) for k, v in overrides.items()})
    return ProjectAnswers.from_raw(raw)


def test_defaults_validate() -> None:
    answers = _answers()
    assert answers.project_name == "My Scientific KB"
    assert answers.repo_name == "my-scientific-kb"
    assert answers.include_cloud_database is False


def test_project_defaults_to_modelscope_and_deepseek() -> None:
    answers = ProjectAnswers(project_name="Demo", repo_name="demo")

    assert answers.embedding_provider == "modelscope"
    assert answers.embedding_model == "Qwen/Qwen3-Embedding-0.6B"
    assert answers.embedding_dim == 1024
    assert answers.llm_provider == "deepseek"
    assert answers.llm_model == "deepseek-flash"
    assert answers.credentials == "deepseek"


@pytest.mark.parametrize(
    ("credentials", "expected_llm_provider", "expected_llm_model"),
    [
        ("deepseek", "deepseek", "deepseek-flash"),
        ("google_ai_studio", "google", "gemini-3.6-flash"),
        ("vertex_ai", "google", "gemini-3.6-flash"),
        ("offline", "deepseek", "deepseek-flash"),
    ],
)
def test_real_wizard_raw_defaults_stay_in_one_provider_family(
    credentials: str,
    expected_llm_provider: str,
    expected_llm_model: str,
) -> None:
    raw = dict(default_answers())
    raw["credentials"] = credentials

    answers = ProjectAnswers.from_raw(raw)

    assert answers.credentials == credentials
    assert answers.llm_provider == expected_llm_provider
    assert answers.llm_model == expected_llm_model
    if credentials == "offline":
        assert answers.embedding_provider == "local-hash"
    elif credentials in {"google_ai_studio", "vertex_ai"}:
        assert answers.embedding_provider == "google"
        assert answers.embedding_model == "gemini-embedding-001"
        assert answers.embedding_dim == 1024
    else:
        assert answers.embedding_provider == "modelscope"
        assert answers.embedding_model == "Qwen/Qwen3-Embedding-0.6B"
        assert answers.embedding_dim == 1024
    if credentials in {"google_ai_studio", "vertex_ai"}:
        assert any("llm_model set to gemini-3.6-flash" in note for note in answers.coercions)


@pytest.mark.parametrize(
    ("embedding_provider", "expected_model", "expected_dim"),
    [
        ("google", "gemini-embedding-001", 1024),
        ("modelscope", "Qwen/Qwen3-Embedding-0.6B", 1024),
    ],
)
def test_real_wizard_raw_defaults_coordinate_embedding_provider(
    embedding_provider: str,
    expected_model: str,
    expected_dim: int,
) -> None:
    raw = dict(default_answers())
    raw["embedding_provider"] = embedding_provider

    answers = ProjectAnswers.from_raw(raw)

    assert answers.embedding_provider == embedding_provider
    assert answers.embedding_model == expected_model
    assert answers.embedding_dim == expected_dim
    if embedding_provider == "google":
        assert any(
            "embedding_model set to gemini-embedding-001" in note for note in answers.coercions
        )
        assert not any("embedding_dim set to 1536" in note for note in answers.coercions)


@pytest.mark.parametrize("credentials", ["google_ai_studio", "vertex_ai"])
def test_fresh_google_answers_use_a_migration_supported_1024_dimension(
    credentials: str,
) -> None:
    answers = _answers(credentials=credentials)

    assert answers.embedding_provider == "google"
    assert answers.embedding_model == "gemini-embedding-001"
    assert answers.embedding_dim == 1024
    assert 32 <= answers.embedding_dim <= 1024


def test_explicit_provider_model_and_dimension_overrides_survive_coordination() -> None:
    raw = dict(default_answers())
    raw.update(
        {
            "credentials": "vertex_ai",
            "llm_provider": "anthropic",
            "llm_model": "custom-generation-model",
            "embedding_provider": "google",
            "embedding_model": "custom-embedding-model",
            "embedding_dim": 768,
        }
    )

    answers = ProjectAnswers.from_raw(raw)

    assert answers.llm_provider == "anthropic"
    assert answers.llm_model == "custom-generation-model"
    assert answers.embedding_provider == "google"
    assert answers.embedding_model == "custom-embedding-model"
    assert answers.embedding_dim == 768
    assert not any("set to google" in note for note in answers.coercions)


@pytest.mark.parametrize(
    ("credentials", "llm_provider", "llm_model", "expected_fix"),
    [
        (
            "google_ai_studio",
            "deepseek",
            "deepseek:deepseek-flash",
            "Select DeepSeek credentials or set the generation provider/model to Google.",
        ),
        (
            "deepseek",
            "google",
            "gemini-3.6-flash",
            "Select Google credentials or set the generation provider/model to DeepSeek.",
        ),
    ],
)
def test_cross_provider_credentials_and_models_fail_closed(
    credentials: str,
    llm_provider: str,
    llm_model: str,
    expected_fix: str,
) -> None:
    with pytest.raises(ValidationError) as caught:
        ProjectAnswers(
            project_name="Mismatched KB",
            repo_name="mismatched-kb",
            credentials=credentials,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )

    message = str(caught.value)
    assert "cannot be used with" in message
    assert expected_fix in message


@pytest.mark.parametrize(
    (
        "credentials",
        "answer_provider",
        "answer_model",
        "role_field",
        "role_model",
        "expected_fix",
    ),
    [
        (
            "google_ai_studio",
            "google",
            "gemini-3.6-flash",
            "extraction_model",
            "anthropic:claude-haiku-4-5",
            "Select Vertex AI credentials or set every generation role to Google.",
        ),
        (
            "google_ai_studio",
            "google",
            "gemini-3.6-flash",
            "judge_model",
            "openai-compatible:xai/grok-4.1-fast",
            "Select Vertex AI credentials or set every generation role to Google.",
        ),
        (
            "deepseek",
            "deepseek",
            "deepseek-flash",
            "extraction_model",
            "openai-compatible:xai/grok-4.1-fast",
            "Select Vertex AI credentials or set every generation role to DeepSeek.",
        ),
        (
            "deepseek",
            "deepseek",
            "deepseek-flash",
            "judge_model",
            "anthropic:claude-haiku-4-5",
            "Select Vertex AI credentials or set every generation role to DeepSeek.",
        ),
    ],
)
def test_credential_sources_validate_every_generation_role(
    credentials: str,
    answer_provider: str,
    answer_model: str,
    role_field: str,
    role_model: str,
    expected_fix: str,
) -> None:
    with pytest.raises(ValidationError) as caught:
        ProjectAnswers(
            project_name="Role Mismatch",
            repo_name="role-mismatch",
            credentials=credentials,
            llm_provider=answer_provider,
            llm_model=answer_model,
            **{role_field: role_model},
        )

    message = str(caught.value)
    assert "cannot be used with" in message
    assert expected_fix in message


@pytest.mark.parametrize(
    ("llm_provider", "llm_model"),
    [
        ("anthropic", "anthropic:claude-haiku-4-5"),
        ("openai-compatible", "openai-compatible:xai/grok-4.1-fast"),
    ],
)
def test_vertex_credentials_allow_partner_generation_providers(
    llm_provider: str,
    llm_model: str,
) -> None:
    answers = ProjectAnswers(
        project_name="Vertex Partner KB",
        repo_name="vertex-partner-kb",
        credentials="vertex_ai",
        llm_provider=llm_provider,
        llm_model=llm_model,
    )

    assert answers.credentials == "vertex_ai"
    assert answers.llm_provider == llm_provider
    assert answers.llm_model == llm_model


def test_offline_credentials_do_not_reject_provider_names() -> None:
    answers = ProjectAnswers(
        project_name="Offline Mixed KB",
        repo_name="offline-mixed-kb",
        credentials="offline",
        llm_provider="google",
        llm_model="gemini-3.6-flash",
        extraction_model="deepseek:deepseek-flash",
        judge_model="anthropic:claude-haiku-4-5",
    )

    assert answers.credentials == "offline"
    assert answers.extraction_model == "deepseek:deepseek-flash"
    assert answers.judge_model == "anthropic:claude-haiku-4-5"


def test_explicit_default_valued_fields_are_not_treated_as_wizard_defaults() -> None:
    raw = dict(default_answers())
    raw.update(
        {
            "credentials": "google_ai_studio",
            "llm_model": "deepseek-flash",
            "embedding_dim": "1024",
        }
    )

    answers = ProjectAnswers.from_raw(raw, explicit_fields={"llm_model", "embedding_dim"})

    assert answers.llm_model == "deepseek-flash"
    assert answers.embedding_dim == 1024
    assert {"llm_model", "embedding_dim"} <= answers.model_fields_set


def test_cloud_database_answer_is_parsed_independently_of_the_manager() -> None:
    for manager in ("uv", "pixi", "conda", "venv+pip"):
        assert _answers(
            environment_manager=manager, include_cloud_database="Yes"
        ).include_cloud_database


def test_offline_credentials_force_the_local_embedder() -> None:
    answers = _answers(credentials="offline", embedding_provider="google")
    assert answers.embedding_provider == "local-hash"


def test_default_answers_select_the_shipped_provider_extras() -> None:
    answers = _answers()

    assert "modelscope-embedding" in answers.extras
    assert "openai" in answers.extras


def test_google_and_offline_answers_do_not_select_default_provider_extras() -> None:
    google = _answers(credentials="google_ai_studio")
    offline = _answers(credentials="offline")

    assert "modelscope-embedding" not in google.extras
    assert "openai" not in google.extras
    assert "modelscope-embedding" not in offline.extras
    assert "openai" not in offline.extras


def test_vertex_anthropic_answer_selects_the_anthropic_extra() -> None:
    answers = ProjectAnswers(
        project_name="Vertex Anthropic KB",
        repo_name="vertex-anthropic-kb",
        credentials="vertex_ai",
        llm_provider="anthropic",
        llm_model="anthropic:claude-haiku-4-5",
    )

    assert "anthropic" in answers.extras


def test_vertex_mixed_roles_select_every_generation_extra() -> None:
    answers = ProjectAnswers(
        project_name="Vertex Mixed KB",
        repo_name="vertex-mixed-kb",
        credentials="vertex_ai",
        llm_provider="google",
        llm_model="gemini-3.6-flash",
        extraction_model="anthropic:claude-haiku-4-5",
        judge_model="openai-compatible:xai/grok-4.1-fast",
    )

    assert "anthropic" in answers.extras
    assert "openai" in answers.extras


def test_offline_mixed_roles_select_no_generation_extras() -> None:
    answers = ProjectAnswers(
        project_name="Offline Mixed KB",
        repo_name="offline-mixed-kb",
        credentials="offline",
        llm_provider="google",
        llm_model="gemini-3.6-flash",
        extraction_model="anthropic:claude-haiku-4-5",
        judge_model="openai-compatible:xai/grok-4.1-fast",
    )

    assert "anthropic" not in answers.extras
    assert "openai" not in answers.extras


def test_offline_credentials_downgrade_an_llm_ontology() -> None:
    """Drafting needs a model. Offline projects keep the worked example."""
    answers = _answers(credentials="offline", ontology="draft_with_llm")
    assert answers.ontology == "keep_demo_example"


def test_draft_without_a_draft_falls_back_visibly() -> None:
    answers = _answers(credentials="google_ai_studio", ontology="draft_with_llm")
    assert answers.ontology == "keep_demo_example"
    assert answers.drafted_ontology is None


def test_draft_is_kept_when_one_was_accepted() -> None:
    drafted = DomainConfig(name="Membrane KB", entity_types=[EntityTypeSpec(name="Membrane")])
    raw = dict(default_answers())
    raw["ontology"] = "draft_with_llm"
    answers = ProjectAnswers.from_raw(raw, drafted_ontology=drafted)
    assert answers.ontology == "draft_with_llm"
    assert answers.drafted_ontology is not None
    assert answers.drafted_ontology.entity_types[0].name == "Membrane"


def test_demo_only_corpus_keeps_the_demo_corpus() -> None:
    answers = _answers(corpus_source="demo_only", include_demo_corpus="No")
    assert answers.include_demo_corpus is True


def test_extras_follow_the_parser_and_reranker_answers() -> None:
    assert _answers(pdf_parser="pypdf", reranker="none").extras == [
        "modelscope-embedding",
        "openai",
    ]
    assert "docling" in _answers(pdf_parser="docling").extras
    assert "rerank" in _answers(reranker="local_cross_encoder").extras
    # The LLM reranker needs no extra at all.
    assert "rerank" not in _answers(reranker="llm").extras


def test_reranker_answer_maps_onto_the_domain_tuning_model() -> None:
    assert _answers(reranker="none").reranker_tuning().enabled is False
    llm = _answers(reranker="llm").reranker_tuning()
    assert (llm.enabled, llm.adapter) == (True, "llm")
    local = _answers(reranker="local_cross_encoder").reranker_tuning()
    assert (local.enabled, local.adapter) == (True, "local")


def test_unknown_environment_manager_is_rejected() -> None:
    with pytest.raises(ValidationError, match="poetry"):
        _answers(environment_manager="poetry")


def test_python_version_outside_the_supported_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _answers(python_version="3.9")


def test_contact_email_must_look_like_an_address() -> None:
    with pytest.raises(ValidationError, match="contact_email"):
        _answers(contact_email="not-an-email")


def test_blank_contact_email_is_allowed() -> None:
    """The mailto is a courtesy header, not a requirement."""
    assert _answers(contact_email="").contact_email == ""


def test_runner_resolves_to_a_profile() -> None:
    assert _answers().runner.key == "uv"


def test_an_offline_project_is_never_offered_the_drafters() -> None:
    """Offering a model-backed step to a project with no model is a dead end."""
    from sci_rag.scaffold.answers import ProjectAnswers

    answers = ProjectAnswers(
        project_name="Offline KB",
        repo_name="offline-kb",
        credentials="offline",
        draft_domain_files=True,
    )

    assert answers.draft_domain_files is False
    assert any("drafting not offered" in note for note in answers.coercions)


def test_a_credentialed_project_keeps_the_drafters_offered() -> None:
    from sci_rag.scaffold.answers import ProjectAnswers

    answers = ProjectAnswers(
        project_name="Cloud KB",
        repo_name="cloud-kb",
        credentials="google_ai_studio",
        draft_domain_files=True,
    )

    assert answers.draft_domain_files is True


def test_api_key_is_never_represented_or_dumped() -> None:
    key = "secret-key-that-must-not-escape"
    answers = _answers(credentials="google_ai_studio", google_api_key=key)

    assert answers.google_api_key == key
    assert key not in repr(answers)
    assert "google_api_key" not in answers.model_dump()


def test_deepseek_key_is_never_represented_or_dumped() -> None:
    key = "secret-key-that-must-not-escape"
    answers = _answers(deepseek_api_key=key)

    assert answers.deepseek_api_key == key
    assert key not in repr(answers)
    assert "deepseek_api_key" not in answers.model_dump()
