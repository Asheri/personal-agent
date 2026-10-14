"""Credential preflight is bounded, actionable, and safe to run offline in tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from google.auth.exceptions import DefaultCredentialsError

from sci_rag.config import DEFAULT_LLM_MODEL, Settings
from sci_rag.scaffold.preflight import (
    CredentialProbe,
    _failure_result,
    _safe_provider_text,
    explicit_deepseek_settings,
    explicit_google_settings,
    probe_deepseek_credentials,
    probe_google_credentials,
    probe_modelscope_dependencies,
)


class _Client:
    def __init__(self, *, reply: str = "ready", failure: Exception | None = None) -> None:
        self.reply = reply
        self.failure = failure
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self.generate_content))

    async def generate_content(self, **_kwargs):  # type: ignore[no-untyped-def]
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(text=self.reply)


def _install_client(monkeypatch, *, failure: Exception | None = None) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []

    def factory(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        return _Client(failure=failure)

    monkeypatch.setattr("google.genai.Client", factory)
    return calls


def test_ai_studio_key_can_complete_a_tiny_generation_probe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = _install_client(monkeypatch)

    result = probe_google_credentials(api_key="test-secret-key", timeout_s=1)

    assert result.ok is True
    assert DEFAULT_LLM_MODEL in result.detail
    assert calls == [{"api_key": "test-secret-key"}]
    assert "test-secret-key" not in repr(result)


def test_deepseek_probe_uses_only_its_dedicated_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    async def probe(settings, *, api_key_override, timeout_s):  # type: ignore[no-untyped-def]
        captured["settings"] = settings
        captured["api_key_override"] = api_key_override
        captured["timeout_s"] = timeout_s
        return CredentialProbe(True, "deepseek-flash answered in 1 ms.")

    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_model_credentials", probe)

    result = probe_deepseek_credentials(api_key="dedicated-secret", timeout_s=2)

    settings = captured["settings"]
    assert settings.deepseek_api_key == "dedicated-secret"
    assert settings.google_api_key is None
    assert settings.gcp_project is None
    assert captured["api_key_override"] == "dedicated-secret"
    assert captured["timeout_s"] == 2
    assert result.ok is True
    assert "dedicated-secret" not in repr(result)


def test_deepseek_probe_without_a_key_fails_before_any_model_call(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    def should_not_probe(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("a missing dedicated key must fail closed")

    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_model_credentials", should_not_probe)

    result = probe_deepseek_credentials(api_key="")

    assert result.ok is False
    assert "SCI_RAG_DEEPSEEK_API_KEY" in result.fix


def test_deepseek_explicit_settings_do_not_read_ambient_google_credentials(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".env").write_text(
        "SCI_RAG_GOOGLE_API_KEY=ambient-google-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = explicit_deepseek_settings(api_key="dedicated-secret")

    assert settings.llm_provider == "deepseek"
    assert settings.deepseek_api_key == "dedicated-secret"
    assert settings.google_api_key is None


def test_modelscope_preflight_reports_a_missing_local_dependency(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def available(name: str) -> object | None:
        return None if name == "modelscope" else object()

    monkeypatch.setattr("sci_rag.scaffold.preflight.find_spec", available)

    result = probe_modelscope_dependencies()

    assert result.ok is False
    assert "modelscope" in result.detail
    assert "uv sync --extra modelscope-embedding" in result.fix


def test_modelscope_preflight_passes_when_local_dependencies_are_present(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sci_rag.scaffold.preflight.find_spec", lambda _name: object())

    result = probe_modelscope_dependencies()

    assert result.ok is True
    assert "modelscope" in result.detail.casefold()


def test_short_deepseek_key_is_redacted_and_not_reported_as_google(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    key = "sk-abc123"
    exc = RuntimeError(f"DeepSeek API is not enabled for this key: {key}")

    safe_text = _safe_provider_text(exc)
    result = _failure_result(exc, vertex=False, provider="deepseek")

    assert key not in safe_text
    assert key not in repr(result)
    assert "Google model API is not enabled" not in result.detail


@pytest.mark.parametrize(
    ("llm_provider", "llm_model", "expected_fix"),
    [
        ("google", "deepseek:deepseek-flash", "SCI_RAG_DEEPSEEK_API_KEY"),
        ("deepseek", "anthropic:claude-haiku-4-5", "SCI_RAG_ANTHROPIC_API_KEY"),
    ],
)
async def test_failure_classification_uses_the_effective_answer_provider(
    monkeypatch,
    llm_provider: str,
    llm_model: str,
    expected_fix: str,
) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import probe_model_credentials

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("401 invalid API key")

    monkeypatch.setattr("sci_rag.scaffold.preflight._generate_once", fail)
    settings = Settings(
        _env_file=None,
        llm_provider=llm_provider,
        llm_model=llm_model,
        google_api_key=None,
        gcp_project=None,
        anthropic_api_key=None,
        openai_api_key=None,
        deepseek_api_key=None,
    )

    result = await probe_model_credentials(settings)

    assert result.ok is False
    assert expected_fix in result.fix


def test_explicit_settings_ignore_a_parent_project_dotenv(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".env").write_text(
        "SCI_RAG_GOOGLE_API_KEY=ambient-parent-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = explicit_google_settings(gcp_project="selected-project")

    assert settings.google_api_key is None
    assert settings.gcp_project == "selected-project"


def test_vertex_checks_adc_before_calling_the_model(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = _install_client(monkeypatch)
    adc_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "google.auth.default",
        lambda **kwargs: adc_calls.append(kwargs) or (SimpleNamespace(), "detected-project"),
    )

    result = probe_google_credentials(gcp_project="science-project", timeout_s=1)

    assert result.ok is True
    assert adc_calls
    assert calls == [{"vertexai": True, "project": "science-project", "location": "us-central1"}]


def test_missing_adc_names_the_login_command(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _install_client(monkeypatch)

    def missing(**_kwargs):  # type: ignore[no-untyped-def]
        raise DefaultCredentialsError("credentials not found")

    monkeypatch.setattr("google.auth.default", missing)

    result = probe_google_credentials(gcp_project="science-project", timeout_s=1)

    assert result == CredentialProbe(
        ok=False,
        detail="Application Default Credentials were not found.",
        fix="Run `gcloud auth application-default login`, then try again.",
    )


@pytest.mark.parametrize(
    ("failure", "detail", "fix_fragment"),
    [
        (
            RuntimeError("400 API key not valid. Please pass a valid API key."),
            "Google rejected the API key.",
            "aistudio.google.com/apikey",
        ),
        (
            RuntimeError("403 SERVICE_DISABLED: Generative Language API is disabled"),
            "The Google model API is not enabled for this project.",
            "Enable",
        ),
        (
            ConnectionError("DNS lookup failed"),
            "Could not reach the Google model service.",
            "network",
        ),
    ],
)
def test_common_failures_map_to_concrete_fixes(
    monkeypatch, failure: Exception, detail: str, fix_fragment: str
) -> None:  # type: ignore[no-untyped-def]
    _install_client(monkeypatch, failure=failure)

    result = probe_google_credentials(api_key="never-print-this", timeout_s=1)

    assert result.ok is False
    assert result.detail == detail
    assert fix_fragment in result.fix
    assert "never-print-this" not in repr(result)


def test_probe_timeout_is_reported_without_leaking_an_exception(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class SlowClient(_Client):
        async def generate_content(self, **_kwargs):  # type: ignore[no-untyped-def]
            await asyncio.Event().wait()

    monkeypatch.setattr("google.genai.Client", lambda **_kwargs: SlowClient())

    result = probe_google_credentials(api_key="slow-key", timeout_s=0.01)

    assert result.ok is False
    assert "timed out" in result.detail
    assert "network" in result.fix


async def test_doctor_generation_probe_uses_the_shared_failure_mapping(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.cli.doctor import _live_probe

    async def failed(_settings, **_kwargs):  # type: ignore[no-untyped-def]
        return CredentialProbe(False, "Mapped provider failure.", "Use the mapped fix.")

    monkeypatch.setattr("sci_rag.scaffold.preflight.probe_model_credentials", failed)

    checks = await _live_probe(Settings(_env_file=None, embedding_provider="local-hash"))
    generation = next(check for check in checks if check.name == "generation probe")

    assert generation.status == "fail"
    assert generation.detail == "Mapped provider failure."
    assert generation.fix == "Use the mapped fix."


class _ProbeLLM:
    def describe(self) -> str:
        return "probe:ready"

    async def generate(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return "ready"


@pytest.mark.parametrize(
    ("provider", "model", "key_field"),
    [
        ("google", "gemini-3.6-flash", "google_api_key"),
        ("deepseek", "deepseek-flash", "deepseek_api_key"),
        ("anthropic", "claude-haiku-4-5", "anthropic_api_key"),
        ("openai-compatible", "xai/grok-4.1-fast", "openai_api_key"),
    ],
)
async def test_generation_probe_maps_an_override_to_the_selected_provider_field(
    monkeypatch, provider, model, key_field
) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import probe_model_credentials

    captured: dict[str, object] = {}

    def build(settings, **kwargs):  # type: ignore[no-untyped-def]
        captured["settings"] = settings
        captured.update(kwargs)
        return _ProbeLLM()

    monkeypatch.setattr("sci_rag.llm.get_llm", build)
    settings = Settings(
        _env_file=None,
        llm_provider=provider,
        llm_model=model,
        google_api_key=None,
        gcp_project=None,
        anthropic_api_key=None,
        openai_api_key=None,
        deepseek_api_key=None,
    )

    result = await probe_model_credentials(settings, api_key_override="byo-secret")

    assert result.ok is True
    routed_settings = captured["settings"]
    assert getattr(routed_settings, key_field) == "byo-secret"
    assert captured.get("api_key_override") is None
    assert "byo-secret" not in repr(result)


async def test_generation_probe_rejects_a_deepseek_override_with_google_credentials(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import probe_model_credentials

    def should_not_build(**_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("a cross-provider key must not reach the client factory")

    monkeypatch.setattr("sci_rag.llm.get_llm", should_not_build)
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        llm_model="deepseek-flash",
        google_api_key="ambient-google-secret",
        deepseek_api_key=None,
    )

    result = await probe_model_credentials(settings, api_key_override="google-secret")

    assert result.ok is False
    assert "SCI_RAG_DEEPSEEK_API_KEY" in result.fix
    assert "ambient-google-secret" not in repr(result)
    assert "google-secret" not in repr(result)


async def test_generation_probe_ignores_generic_override_when_target_key_exists(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.scaffold.preflight import probe_model_credentials

    captured: dict[str, object] = {}

    def build(settings, **kwargs):  # type: ignore[no-untyped-def]
        captured["settings"] = settings
        captured.update(kwargs)
        return _ProbeLLM()

    monkeypatch.setattr("sci_rag.llm.get_llm", build)
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        llm_model="deepseek-flash",
        google_api_key="ambient-google-secret",
        deepseek_api_key="target-deepseek-key",
    )

    result = await probe_model_credentials(settings, api_key_override="generic-request-key")

    assert result.ok is True
    assert captured["settings"].deepseek_api_key == "target-deepseek-key"
    assert captured.get("api_key_override") is None


# --- wrong location for a partner model -------------------------------------


@pytest.fixture()
def stub_adc(monkeypatch):  # type: ignore[no-untyped-def]
    """Vertex mode resolves ADC before it calls the model; keep that offline."""
    monkeypatch.setattr(
        "google.auth.default",
        lambda **_kwargs: (SimpleNamespace(), "detected-project"),
    )


#
# F-029: `docs/extend.md` tells a reader that a partner model served only from
# `global` fails with "a clear `400 ... is not servable in region` or `404 ...
# not found`, so `sci-rag doctor --probe` will catch it before a pipeline run
# does". The probe caught the failure and then classified it as a generic
# credential problem, so the guide's own repair, `SCI_RAG_GCP_LOCATION=global`,
# appeared nowhere in the diagnosis.


@pytest.mark.parametrize(
    "failure",
    [
        # Vertex, Anthropic publisher model, wrong region.
        RuntimeError(
            "400 Publisher Model `projects/p/locations/us-central1/publishers/anthropic/"
            "models/claude-haiku-4-5` is not servable in region us-central1."
        ),
        # Vertex, OpenAI-compatible partner endpoint, same cause, 404 shape.
        RuntimeError(
            "404 Publisher Model `publishers/xai/models/grok-4-fast` not found in "
            "location us-central1."
        ),
        # The message a live call actually returns, captured on 2026-08-30
        # with SCI_RAG_GCP_LOCATION=us-central1 against a partner model that
        # answers from global. #181 took its two phrasings from the guide
        # rather than from a response, and this third one matched neither, so
        # the case it was written for fell back to the generic diagnosis.
        RuntimeError(
            "Error code: 400 - [{'error': {'code': 400, 'message': \"Publisher model "
            "'xai/grok-4.1-fast-non-reasoning' in region 'us-central1' is only "
            "available via global endpoint.\", 'status': 'FAILED_PRECONDITION'}}]"
        ),
    ],
    ids=["not-servable-in-region", "not-found-in-location", "only-via-global-endpoint"],
)
def test_a_wrong_location_names_the_location_setting(
    monkeypatch, stub_adc, failure: Exception
) -> None:  # type: ignore[no-untyped-def]
    _install_client(monkeypatch, failure=failure)

    result = probe_google_credentials(gcp_project="a-project", location="us-central1", timeout_s=1)

    assert result.ok is False
    # The effective location, so a reader can see what was actually asked.
    assert "us-central1" in result.detail
    assert "SCI_RAG_GCP_LOCATION=global" in result.fix
    # Not the generic branch, which names five unrelated things.
    assert "Check the project ID, ADC login" not in result.fix


def test_a_location_404_also_offers_the_model_garden_reading(monkeypatch, stub_adc) -> None:  # type: ignore[no-untyped-def]
    """A 404 has a second cause a 400 does not, and it has to say so.

    `not servable in region` means the model exists and is served elsewhere.
    `not found in location` also covers a model id that is wrong, or one whose
    Model Garden offering was never enabled for this project. Collapsing them
    would send a reader to change a location that was never the problem.
    """
    _install_client(
        monkeypatch,
        failure=RuntimeError(
            "404 Publisher Model `publishers/xai/models/typo` not found in location us-central1."
        ),
    )

    result = probe_google_credentials(gcp_project="a-project", location="us-central1", timeout_s=1)

    assert "SCI_RAG_GCP_LOCATION=global" in result.fix
    assert "Model Garden" in result.fix


def test_a_location_diagnostic_does_not_reprint_the_provider_payload(monkeypatch, stub_adc) -> None:  # type: ignore[no-untyped-def]
    """The raw message names an internal project path; the diagnosis must not."""
    _install_client(
        monkeypatch,
        failure=RuntimeError(
            "400 Publisher Model `projects/secret-project-1234/locations/us-central1/"
            "publishers/anthropic/models/claude-haiku-4-5` is not servable in region us-central1."
        ),
    )

    result = probe_google_credentials(gcp_project="a-project", location="us-central1", timeout_s=1)

    assert "secret-project-1234" not in repr(result)
    assert "Publisher Model" not in repr(result)


@pytest.mark.parametrize(
    ("failure", "detail"),
    [
        (
            RuntimeError("403 SERVICE_DISABLED: Vertex AI API is disabled"),
            "The Google model API is not enabled for this project.",
        ),
        (
            RuntimeError("400 `not-a-model` is not a valid publisher model name"),
            "Credential check failed (RuntimeError).",
        ),
        (
            RuntimeError("Could not automatically determine credentials"),
            "Application Default Credentials were not found.",
        ),
    ],
    ids=["api-disabled", "malformed-model", "authentication"],
)
def test_failures_that_are_not_about_location_keep_their_own_diagnosis(  # type: ignore[no-untyped-def]
    monkeypatch, stub_adc, failure: Exception, detail: str
) -> None:
    """A new branch must not swallow the ones already answering correctly.

    Quota is deliberately absent. A 429 or `RESOURCE_EXHAUSTED` is retryable
    by design, so it reaches this mapper only after the shared retry budget
    and cannot be exercised against a one-second probe deadline without
    testing the backoff instead of the classification.
    """
    _install_client(monkeypatch, failure=failure)

    result = probe_google_credentials(gcp_project="a-project", location="us-central1", timeout_s=1)

    # `startswith`, not equality: the generic branch now appends the
    # provider's own redacted text, which is the point of that branch. What
    # this test guards is the classification in front of it.
    assert result.detail.startswith(detail)
    assert "SCI_RAG_GCP_LOCATION" not in result.fix


# Captured from the Generative Language API on 2026-08-31, calling a model a
# freshly issued key may no longer use. Quoted rather than paraphrased: #181
# shipped two phrasings taken from a guide, Vertex sent a third, and #232 had
# to fix it. This is the fourth, from a different surface again.
RETIREMENT_MESSAGE = (
    "404 NOT_FOUND. This model models/gemini-2.5-flash is no longer available "
    "to new users. Please update your code to use models/gemini-3.6-flash for "
    "the latest features and improvements."
)


def test_a_retired_model_is_diagnosed_as_a_model_problem(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The old answer sent a reader to check three things that were all fine.

    Before this, the retirement phrasing matched no marker and fell through
    to "Credential check failed (ClientError)" with "Check the AI Studio key,
    model, and quota". The key was valid, the quota was fine, and the model
    name was spelled correctly.
    """
    _install_client(monkeypatch, failure=RuntimeError(RETIREMENT_MESSAGE))

    result = probe_google_credentials(api_key="never-print-this", timeout_s=1)

    assert result.ok is False
    assert "no longer available" in result.detail.lower()
    assert "never-print-this" not in repr(result)


def test_an_unrecognised_failure_keeps_the_provider_message(monkeypatch) -> None:
    """The generic branch used to throw away the one useful thing it had.

    Every gap in the marker list has cost a round trip, because the text that
    would have diagnosed it was in hand and discarded. A message nobody
    anticipated is exactly when the provider's own words are worth most.
    """
    _install_client(monkeypatch, failure=RuntimeError("418 TEAPOT: the carafe is not attached"))

    result = probe_google_credentials(api_key="never-print-this", timeout_s=1)

    assert result.ok is False
    assert "carafe is not attached" in result.detail
    assert "never-print-this" not in repr(result)


def test_a_kept_message_still_redacts_a_credential(monkeypatch) -> None:
    """Keeping the text must not become a way to print a key.

    A provider that echoes the key back in an error is the case this has to
    survive, because it is the one where forwarding is most tempting and most
    dangerous.
    """
    leaky = RuntimeError("400 BAD: key AIzaSyEXAMPLEEXAMPLEEXAMPLEEXAMPLE123 rejected by policy")
    _install_client(monkeypatch, failure=leaky)

    result = probe_google_credentials(api_key="AIzaSyEXAMPLEEXAMPLEEXAMPLEEXAMPLE123", timeout_s=1)

    assert result.ok is False
    assert "AIzaSyEXAMPLE" not in repr(result)
    assert "rejected by policy" in result.detail
