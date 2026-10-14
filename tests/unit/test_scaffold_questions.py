"""questions.py is the single source of truth for the wizard and the docs.

The order and the defaults are the user-visible contract: the plan's target
transcript is this list rendered. A change here is a change to the homepage,
so the spec is spelled out rather than derived.
"""

from __future__ import annotations

from sci_rag.scaffold.questions import QUESTIONS, default_answers, default_for, is_asked
from sci_rag.scaffold.runners import runner_keys

# The question order from the plan's target transcript: identity, then
# credentials and models, then domain, then corpus, then stack choices,
# then licensing and git.
EXPECTED_ORDER = [
    "project_name",
    "repo_name",
    "description",
    "author_name",
    "contact_email",
    "python_version",
    "environment_manager",
    "dependency_file",
    "credentials",
    "deepseek_api_key",
    "google_api_key",
    "gcp_project",
    "embedding_provider",
    "llm_model",
    "embedding_model",
    "embedding_dim",
    "ontology",
    "corpus_source",
    "openalex_topic",
    "max_results",
    "pdf_parser",
    "reranker",
    "include_terraform",
    "include_cloud_database",
    "include_demo_corpus",
    "open_source_license",
    "initialize_git",
    "draft_domain_files",
]


def test_question_order_matches_the_documented_transcript() -> None:
    assert [q.name for q in QUESTIONS] == EXPECTED_ORDER


def test_every_question_has_a_default() -> None:
    """Pressing Enter through the whole session has to produce a project."""
    for question in QUESTIONS:
        assert isinstance(default_for(question, {}), str), question.name
    assert default_for(next(q for q in QUESTIONS if q.name == "google_api_key"), {}) == ""
    assert default_for(next(q for q in QUESTIONS if q.name == "gcp_project"), {}) == ""


def test_environment_manager_choices_come_from_runners() -> None:
    """The choice list is derived, so adding a profile cannot leave it stale."""
    question = next(q for q in QUESTIONS if q.name == "environment_manager")
    assert list(question.choices or ()) == runner_keys()


def test_repo_name_default_is_slugified_from_the_project_name() -> None:
    question = next(q for q in QUESTIONS if q.name == "repo_name")
    assert (
        default_for(question, {"project_name": "Membrane Materials KB"}) == "membrane-materials-kb"
    )


def test_openalex_questions_are_gated_on_the_corpus_source() -> None:
    topic = next(q for q in QUESTIONS if q.name == "openalex_topic")
    assert is_asked(topic, {"corpus_source": "openalex_topic"})
    assert not is_asked(topic, {"corpus_source": "local_files"})


def test_embedding_provider_is_not_asked_when_offline() -> None:
    provider = next(q for q in QUESTIONS if q.name == "embedding_provider")
    assert not is_asked(provider, {"credentials": "offline"})
    assert is_asked(provider, {"credentials": "google_ai_studio"})


def test_dependency_file_is_only_asked_for_pixi() -> None:
    dependency_file = next(q for q in QUESTIONS if q.name == "dependency_file")
    assert not is_asked(dependency_file, {"environment_manager": "uv"})
    assert is_asked(dependency_file, {"environment_manager": "pixi"})


def test_python_version_rejects_an_unsupported_interpreter() -> None:
    question = next(q for q in QUESTIONS if q.name == "python_version")
    assert question.validator is not None
    assert question.validator("3.11") == "3.11"
    try:
        question.validator("3.9")
    except ValueError as exc:
        assert "3.11" in str(exc)
    else:  # pragma: no cover - the assert above is the point
        raise AssertionError("3.9 should be rejected")


def test_default_answers_walks_the_gates() -> None:
    answers = default_answers()
    assert answers["project_name"] == "My Scientific KB"
    assert answers["repo_name"] == "my-scientific-kb"
    assert answers["python_version"] == "3.12"
    # local_files is the default corpus source, so the OpenAlex follow-ups
    # are never reached.
    assert "openalex_topic" not in answers
    assert answers["include_cloud_database"] == "No"


def test_quick_mode_has_the_six_base_questions_plus_the_gated_credential_value() -> None:
    assert [question.name for question in QUESTIONS if question.quick] == [
        "project_name",
        "description",
        "contact_email",
        "environment_manager",
        "credentials",
        "deepseek_api_key",
        "google_api_key",
        "gcp_project",
        "corpus_source",
    ]


def test_every_choice_has_human_help_and_python_is_a_menu() -> None:
    python = next(question for question in QUESTIONS if question.name == "python_version")
    assert python.choices == ("3.11", "3.12")

    for question in QUESTIONS:
        if question.choices:
            assert set(question.choice_help) == set(question.choices), question.name
            assert all(question.choice_help.values()), question.name


def test_credential_values_are_gated_and_explain_how_to_get_them() -> None:
    by_name = {question.name: question for question in QUESTIONS}
    api_key = by_name["google_api_key"]
    project = by_name["gcp_project"]

    assert api_key.secret is True
    assert "aistudio.google.com/apikey" in api_key.help
    assert is_asked(api_key, {"credentials": "google_ai_studio"})
    assert not is_asked(api_key, {"credentials": "vertex_ai"})

    assert "gcloud auth application-default login" in project.help
    assert is_asked(project, {"credentials": "vertex_ai"})
    assert not is_asked(project, {"credentials": "google_ai_studio"})
