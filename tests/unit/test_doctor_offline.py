"""What the doctor says about credentials a project never asked for.

A project can run entirely on the deterministic local embedder, and the
wizard writes exactly that for ``credentials: offline``. Reporting FAIL for
the state a user deliberately selected trains them to ignore the diagnosis,
so these tests pin both directions: an offline project warns, and a project
that reached for a model and missed a credential still fails.

Every case builds ``Settings`` with the dotenv file switched off and the
credential and generation variables cleared, because a developer's exported
key or a local ``.env`` would otherwise decide the answer instead of the
argument under test.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from sci_rag.cli.doctor import (
    Check,
    _embedding_provider_check,
    _live_probe,
    _llm_credential_checks,
)
from sci_rag.config import Settings
from sci_rag.scaffold.preflight import CredentialProbe

_CREDENTIAL_VARS = (
    "SCI_RAG_GOOGLE_API_KEY",
    "SCI_RAG_GCP_PROJECT",
    "SCI_RAG_ANTHROPIC_API_KEY",
    "SCI_RAG_OPENAI_API_KEY",
    "SCI_RAG_OPENAI_BASE_URL",
    "SCI_RAG_DEEPSEEK_API_KEY",
    "SCI_RAG_DEEPSEEK_BASE_URL",
)
_GENERATION_VARS = (
    "SCI_RAG_LLM_PROVIDER",
    "SCI_RAG_LLM_MODEL",
    "SCI_RAG_EXTRACTION_MODEL",
    "SCI_RAG_JUDGE_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _CREDENTIAL_VARS + _GENERATION_VARS:
        monkeypatch.delenv(name, raising=False)


def _offline(**overrides: Any) -> Settings:
    """A project with the local embedder and nothing else configured."""
    values: dict[str, Any] = {"embedding_provider": "local-hash", **overrides}
    return Settings(_env_file=None, **values)


def _by_name(checks: list[Check]) -> dict[str, Check]:
    return {check.name: check for check in checks}


# --- the predicate ----------------------------------------------------------


def test_local_hash_with_current_deepseek_defaults_is_offline() -> None:
    settings = _offline()

    assert settings.llm_provider == "deepseek"
    assert settings.llm_model == "deepseek-flash"
    assert settings.is_offline() is True


def test_legacy_google_defaults_remain_offline_without_credentials() -> None:
    settings = _offline(llm_provider="google", llm_model="gemini-3.6-flash")

    assert settings.is_offline() is True


def test_a_google_embedder_is_not_offline() -> None:
    """Wanting semantic embeddings is cloud intent, credentials or not."""
    assert _offline(embedding_provider="google").is_offline() is False


@pytest.mark.parametrize(
    "credential",
    [
        {"google_api_key": "k"},
        {"gcp_project": "p"},
        {"anthropic_api_key": "k"},
        {"openai_api_key": "k"},
        {"openai_base_url": "http://localhost:8080/v1"},
        {"deepseek_api_key": "k"},
        {"deepseek_base_url": "http://localhost:11434/v1"},
    ],
)
def test_any_configured_credential_means_the_project_is_not_offline(
    credential: dict[str, str],
) -> None:
    """One credential says a model is in play, so a missing one is a real gap."""
    assert _offline(**credential).is_offline() is False


@pytest.mark.parametrize(
    "generation",
    [
        {"llm_model": "anthropic:claude-opus-5"},
        {"llm_model": "gemini-2.5-pro"},
        {"llm_provider": "anthropic"},
        {"extraction_model": "gemini-2.5-flash-lite"},
        {"judge_model": "openai-compatible:xai/grok-4.1-fast-reasoning"},
    ],
)
def test_naming_a_generation_model_means_the_project_is_not_offline(
    generation: dict[str, str],
) -> None:
    """Writing a model id is how a user says they intend to generate."""
    assert _offline(**generation).is_offline() is False


# --- the llm credential rows ------------------------------------------------


def test_offline_project_warns_instead_of_failing() -> None:
    checks = _llm_credential_checks(_offline())

    assert [check.status for check in checks] == ["warn"]
    row = checks[0]
    assert row.name == "llm credentials (deepseek)"
    assert "answer" in row.detail
    assert "extraction" in row.detail
    assert "judge" in row.detail
    assert "SCI_RAG_DEEPSEEK_API_KEY" in row.fix
    assert "SCI_RAG_GOOGLE_API_KEY" not in row.fix


def test_legacy_google_offline_project_gets_the_google_fix() -> None:
    settings = _offline(llm_provider="google", llm_model="gemini-3.6-flash")
    row = _by_name(_llm_credential_checks(settings))["llm credentials (google)"]

    assert row.status == "warn"
    assert "SCI_RAG_GOOGLE_API_KEY" in row.fix


@pytest.mark.parametrize(
    ("overrides", "expected_label"),
    [
        (
            {"embedding_provider": "google", "llm_provider": "google"},
            "llm credentials (google)",
        ),
        (
            {
                "embedding_provider": "google",
                "llm_provider": "google",
                "llm_model": "anthropic:claude-opus-5",
            },
            "llm credentials (anthropic)",
        ),
        (
            {
                "embedding_provider": "google",
                "llm_model": "openai-compatible:xai/grok-4.1-fast-reasoning",
            },
            "llm credentials (openai-compatible)",
        ),
        # Local embeddings with a deliberately named cloud model: the embedder
        # is offline but generation is not, so this project really is broken.
        ({"llm_model": "anthropic:claude-opus-5"}, "llm credentials (anthropic)"),
        (
            {"llm_provider": "google", "llm_model": "gemini-2.5-pro"},
            "llm credentials (google)",
        ),
        (
            {"judge_model": "openai-compatible:xai/grok-4.1-fast-reasoning"},
            "llm credentials (openai-compatible)",
        ),
    ],
)
def test_cloud_intent_without_credentials_still_fails(
    overrides: dict[str, str], expected_label: str
) -> None:
    checks = _by_name(_llm_credential_checks(_offline(**overrides)))

    assert checks[expected_label].status == "fail"


def test_an_openai_base_url_without_a_key_still_fails() -> None:
    """The one cloud misconfiguration that is not a missing credential."""
    settings = _offline(
        llm_model="openai-compatible:local/mixtral",
        openai_base_url="http://localhost:8080/v1",
    )

    row = _by_name(_llm_credential_checks(settings))["llm credentials (openai-compatible)"]

    assert row.status == "fail"
    assert "SCI_RAG_OPENAI_BASE_URL" in row.detail


def test_deepseek_without_a_key_fails_with_the_deepseek_variable() -> None:
    settings = _offline(embedding_provider="modelscope")
    row = _by_name(_llm_credential_checks(settings))["llm credentials (deepseek)"]

    assert row.status == "fail"
    assert "SCI_RAG_DEEPSEEK_API_KEY" in row.fix
    assert "SCI_RAG_OPENAI_API_KEY" not in row.fix


def test_a_deepseek_key_marks_the_deepseek_provider_ready() -> None:
    settings = _offline(embedding_provider="modelscope", deepseek_api_key="k")
    row = _by_name(_llm_credential_checks(settings))["llm credentials (deepseek)"]

    assert row.status == "ok"
    assert "SCI_RAG_DEEPSEEK_API_KEY" in row.detail


def test_a_credentialed_project_is_unaffected() -> None:
    checks = _by_name(_llm_credential_checks(_offline(llm_provider="google", google_api_key="k")))

    assert checks["llm credentials (google)"].status == "ok"


# --- the embedding provider row ---------------------------------------------


def test_offline_credentials_row_does_not_claim_embedding_is_broken() -> None:
    """local-hash ingests new documents fine, so saying otherwise is wrong."""
    row = _embedding_provider_check(_offline())

    assert row.status == "warn"
    assert "local-hash" in row.detail
    assert "lexical" in row.detail
    assert "embedding new documents will not" not in row.detail
    assert "SCI_RAG_GOOGLE_API_KEY" not in row.fix


def test_a_google_embedder_without_credentials_still_fails() -> None:
    row = _embedding_provider_check(_offline(embedding_provider="google"))

    assert row.status == "fail"
    assert "local-hash" in row.fix


def test_configured_credentials_report_their_mode() -> None:
    assert (
        _embedding_provider_check(_offline(embedding_provider="google", google_api_key="k")).status
        == "ok"
    )
    assert (
        _embedding_provider_check(_offline(embedding_provider="google", gcp_project="p")).detail
        == "mode=vertex"
    )


@pytest.mark.parametrize("missing", ["modelscope", "sentence_transformers"])
def test_modelscope_missing_dependencies_fail_with_the_exact_install_fix(
    missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sci_rag.cli.doctor.find_spec",
        lambda name: None if name == missing else object(),
    )

    row = _embedding_provider_check(Settings(_env_file=None, embedding_provider="modelscope"))

    assert row.status == "fail"
    assert missing in row.detail
    assert row.fix == "uv sync --extra modelscope-embedding"


@pytest.mark.parametrize(
    "model_id",
    [
        "",
        "   ",
    ],
)
def test_modelscope_static_check_rejects_an_invalid_model_id(
    model_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sci_rag.cli.doctor.find_spec", lambda _name: object())
    settings = Settings.model_construct(
        embedding_provider="modelscope",
        embedding_model=model_id,
    )

    row = _embedding_provider_check(settings)

    assert row.status == "fail"
    assert "SCI_RAG_EMBEDDING_MODEL" in row.fix


@pytest.mark.parametrize("dimension", [31, 1025])
def test_modelscope_dimension_fails_fast_during_settings_load(dimension: int) -> None:
    with pytest.raises(ValidationError, match="embedding_dim must be between 32 and 1024"):
        Settings(
            _env_file=None,
            embedding_provider="modelscope",
            embedding_dim=dimension,
        )


def test_doctor_does_not_claim_to_revalidate_a_settings_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dimension validation belongs to Settings, before doctor can build a table."""
    monkeypatch.setattr("sci_rag.cli.doctor.find_spec", lambda _name: object())
    bypassing_settings_load = Settings.model_construct(
        embedding_provider="modelscope",
        embedding_model="Qwen/Qwen3-Embedding-0.6B",
        embedding_dim=31,
    )

    row = _embedding_provider_check(bypassing_settings_load)

    assert row.status == "ok"


def test_modelscope_static_check_passes_without_downloading_a_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sci_rag.cli.doctor.find_spec", lambda _name: object())

    def forbid_embedder(_settings: Settings) -> None:
        raise AssertionError("the static check must not construct an embedder")

    monkeypatch.setattr("sci_rag.embed.get_embedder", forbid_embedder)
    row = _embedding_provider_check(
        Settings(
            _env_file=None,
            embedding_provider="modelscope",
            embedding_dim=1024,
        )
    )

    assert row.status == "ok"
    assert "Qwen/Qwen3-Embedding-0.6B" in row.detail
    assert "1024" in row.detail


def test_a_modelscope_embedder_does_not_require_google_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sci_rag.cli.doctor.find_spec", lambda _name: object())

    row = _embedding_provider_check(Settings(_env_file=None, embedding_provider="modelscope"))

    assert row.status == "ok"
    assert "SCI_RAG_GOOGLE_API_KEY" not in row.fix


@pytest.mark.parametrize(
    ("message", "expected_fix"),
    [
        (
            "Install it with: uv sync --extra modelscope-embedding",
            "uv sync --extra modelscope-embedding",
        ),
        (
            "Connection error while downloading the model",
            "SCI_RAG_MODELSCOPE_CACHE_DIR",
        ),
    ],
    ids=["missing-dependency", "download-failure"],
)
async def test_modelscope_embedding_probe_failures_stay_visible_and_actionable(
    message: str,
    expected_fix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenEmbedder:
        version = "Qwen/Qwen3-Embedding-0.6B@1024"

        async def embed(self, _texts: list[str], *, task: str) -> list[list[float]]:
            raise RuntimeError(message)

    async def generation_ok(_settings: Settings) -> CredentialProbe:
        return CredentialProbe(True, "offline generation stub")

    monkeypatch.setattr("sci_rag.embed.get_embedder", lambda _settings: BrokenEmbedder())
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_model_credentials",
        generation_ok,
    )

    checks = await _live_probe(Settings(_env_file=None, embedding_provider="modelscope"))
    row = _by_name(checks)["embedding probe"]

    assert row.status == "fail"
    assert "RuntimeError" in row.detail
    assert expected_fix in row.fix


async def test_embedding_probe_redacts_credentials_from_its_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ai_key = "AIzaSySECRETVALUE1234567890"
    api_key = "sk-topsecret1234567890"

    class BrokenEmbedder:
        version = "Qwen/Qwen3-Embedding-0.6B@1024"

        async def embed(self, _texts: list[str], *, task: str) -> list[list[float]]:
            raise RuntimeError(f"provider rejected {ai_key} and {api_key}")

    async def generation_ok(_settings: Settings) -> CredentialProbe:
        return CredentialProbe(True, "offline generation stub")

    monkeypatch.setattr("sci_rag.embed.get_embedder", lambda _settings: BrokenEmbedder())
    monkeypatch.setattr(
        "sci_rag.scaffold.preflight.probe_model_credentials",
        generation_ok,
    )

    checks = await _live_probe(Settings(_env_file=None, embedding_provider="modelscope"))
    row = _by_name(checks)["embedding probe"]

    assert row.status == "fail"
    assert "RuntimeError" in row.detail
    assert ai_key not in row.detail
    assert api_key not in row.detail
    assert "<redacted>" in row.detail
