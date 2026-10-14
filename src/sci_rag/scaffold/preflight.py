"""Bounded LLM provider credential checks shared by setup and ``sci-rag doctor``."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from importlib.util import find_spec
from typing import TYPE_CHECKING

from google.auth.exceptions import DefaultCredentialsError

from sci_rag.config import DEFAULT_LLM_MODEL, Settings

if TYPE_CHECKING:
    from sci_rag.llm import LLMClient

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@dataclass(frozen=True)
class CredentialProbe:
    """A user-safe probe result that never carries the credential itself."""

    ok: bool
    detail: str
    fix: str = ""


def explicit_google_settings(
    *,
    api_key: str = "",
    gcp_project: str = "",
    location: str = "us-central1",
    model: str = DEFAULT_LLM_MODEL,
) -> Settings:
    """Build settings without reading a parent project's ``.env`` file."""
    return Settings.model_validate(
        {
            "google_api_key": api_key or None,
            "gcp_project": gcp_project or None,
            "gcp_location": location,
            "llm_provider": "google",
            "llm_model": model,
            "embedding_provider": "google",
        }
    )


def explicit_deepseek_settings(
    *,
    api_key: str = "",
    model: str = DEFAULT_LLM_MODEL,
) -> Settings:
    """构建只使用 DeepSeek 专用凭据的设置, 不读取环境中的 Google 凭据。"""
    return Settings.model_validate(
        {
            "google_api_key": None,
            "gcp_project": None,
            "deepseek_api_key": api_key or None,
            "llm_provider": "deepseek",
            "llm_model": model,
            "embedding_provider": "local-hash",
        }
    )


def build_explicit_deepseek_llm(
    *,
    api_key: str = "",
    model: str = DEFAULT_LLM_MODEL,
) -> LLMClient:
    """用向导捕获的专用 DeepSeek 密钥构建一次性客户端。"""
    from sci_rag.llm import get_llm

    settings = explicit_deepseek_settings(api_key=api_key, model=model)
    return get_llm(settings, api_key_override=api_key or None)


def build_explicit_google_llm(
    *,
    api_key: str = "",
    gcp_project: str = "",
    location: str = "us-central1",
    model: str = DEFAULT_LLM_MODEL,
) -> LLMClient:
    """Build a client from captured values without consulting ambient settings."""
    from sci_rag.llm import get_llm

    settings = explicit_google_settings(
        api_key=api_key,
        gcp_project=gcp_project,
        location=location,
        model=model,
    )
    return get_llm(settings, api_key_override=api_key or None)


def probe_google_credentials(
    *,
    api_key: str = "",
    gcp_project: str = "",
    location: str = "us-central1",
    model: str = DEFAULT_LLM_MODEL,
    timeout_s: float = 15.0,
) -> CredentialProbe:
    """Make one bounded generation call with an explicit Google credential."""
    if not api_key and not gcp_project:
        return CredentialProbe(
            False,
            "No Google credential was provided.",
            "Add an AI Studio key or a Google Cloud project, then try again.",
        )
    settings = explicit_google_settings(
        api_key=api_key,
        gcp_project=gcp_project,
        location=location,
        model=model,
    )
    return asyncio.run(
        probe_model_credentials(
            settings,
            api_key_override=api_key or None,
            timeout_s=timeout_s,
        )
    )


def probe_deepseek_credentials(
    *,
    api_key: str = "",
    model: str = DEFAULT_LLM_MODEL,
    timeout_s: float = 15.0,
) -> CredentialProbe:
    """使用 DeepSeek 专用密钥做一次有界生成探测。"""
    if not api_key:
        return CredentialProbe(
            False,
            "No DeepSeek credential was provided.",
            "Set SCI_RAG_DEEPSEEK_API_KEY, then try again.",
        )
    settings = explicit_deepseek_settings(api_key=api_key, model=model)
    return asyncio.run(
        probe_model_credentials(
            settings,
            api_key_override=api_key,
            timeout_s=timeout_s,
        )
    )


def probe_modelscope_dependencies() -> CredentialProbe:
    """只检查本地可选依赖, 不下载模型, 也不接受任何密钥。"""
    missing = [name for name in ("modelscope", "sentence_transformers") if find_spec(name) is None]
    if missing:
        return CredentialProbe(
            False,
            "Missing local embedding dependencies: " + ", ".join(missing) + ".",
            "Install them with `uv sync --extra modelscope-embedding`.",
        )
    return CredentialProbe(
        True,
        "ModelScope and Sentence Transformers are installed locally.",
    )


async def probe_model_credentials(
    settings: Settings,
    *,
    api_key_override: str | None = None,
    timeout_s: float = 15.0,
) -> CredentialProbe:
    """Probe configured generation with a hard deadline and safe error copy."""
    try:
        return await asyncio.wait_for(
            _generate_once(settings, api_key_override=api_key_override),
            timeout=timeout_s,
        )
    except TimeoutError:
        return CredentialProbe(
            False,
            f"Credential check timed out after {timeout_s:g} seconds.",
            "Check the network or proxy, then try again.",
        )
    except Exception as exc:
        return _failure_result(
            exc,
            vertex=settings.credentials_mode() == "vertex",
            location=settings.gcp_location,
            provider=settings.model_spec_for("answer").provider,
        )


async def _generate_once(settings: Settings, *, api_key_override: str | None) -> CredentialProbe:
    provider = settings.model_spec_for("answer").provider
    if api_key_override:
        from sci_rag.llm import resolve_llm_api_key_override, settings_with_llm_api_key

        resolved_override = resolve_llm_api_key_override(
            settings,
            provider,
            api_key_override,
        )
        if resolved_override:
            settings = settings_with_llm_api_key(settings, provider, resolved_override)

    if settings.credentials_mode() == "vertex":
        import google.auth

        await asyncio.to_thread(google.auth.default, scopes=[_CLOUD_PLATFORM_SCOPE])

    from sci_rag.llm import get_llm

    llm = get_llm(settings)
    start = time.monotonic()
    # Reasoning models may spend output tokens before producing the visible
    # word. A generous cap avoids misclassifying that as an empty response;
    # the hard wall-clock timeout still bounds the probe.
    reply = await llm.generate("Reply with the single word: ready", max_tokens=2048)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if not reply.strip():
        return CredentialProbe(
            False,
            f"{llm.describe()} returned an empty response.",
            "Check the model name and quota, then try again.",
        )
    return CredentialProbe(True, f"{llm.describe()} answered in {elapsed_ms} ms.")


#: Vertex refuses a model served somewhere else in several shapes. Two say
#: the model exists and this region does not serve it, so the location is the
#: only thing to change. The 404 covers the same cause plus two others: a
#: model id that is wrong, and a Model Garden offering the project never
#: enabled, so it is answered separately.
#:
#: `only available via global endpoint` is the one a live call returns, and it
#: is here because #181's first two came from the guide rather than from a
#: response. Prose is the weak part of this match, so a `FAILED_PRECONDITION`
#: on a partner model is treated the same way: the status is what Vertex uses
#: for "right model, wrong place", and it outlives a rewording.
_NOT_SERVABLE_MARKERS = (
    "not servable in region",
    "not servable in location",
    "only available via global endpoint",
    "only available via the global endpoint",
)
_NOT_FOUND_MARKERS = ("not found in location", "not found in region")
#: A model the account may no longer use. Distinct from "not found": the id is
#: real and the credential is valid, so pointing at either wastes the reader's
#: time. Captured from the provider on 2026-08-31.
_RETIRED_MODEL_MARKERS = ("no longer available", "is not available to new users")
_WRONG_PLACE_STATUS = "failed_precondition"


#: Anything shaped like a credential, removed before a provider message is
#: shown. Keeping the text is only safe if this runs first.
_SECRET_SHAPED = re.compile(
    r"AIza[0-9A-Za-z_\-]{10,}|\bsk-[A-Za-z0-9_\-]{4,}\b|\b[A-Za-z0-9_\-]{40,}\b"
)
#: Internal resource paths name projects and locations the reader did not ask
#: about, which is what the original "build your own sentence" rule protected.
_RESOURCE_PATH = re.compile(r"\bprojects/[^\s,;]+")


def _safe_provider_text(exc: Exception, limit: int = 300) -> str:
    """The provider's own words, with credentials and resource paths removed.

    Discarding this entirely is what made #181, #232, and the model
    retirement each cost a round trip: the sentence that would have explained
    the failure was in hand and thrown away. Redaction keeps the explanation
    without keeping the secret.
    """
    text = " ".join(str(exc).split())
    text = _SECRET_SHAPED.sub("<redacted>", text)
    text = _RESOURCE_PATH.sub("<resource>", text)
    return text[:limit].rstrip()


def _failure_result(
    exc: Exception,
    *,
    vertex: bool,
    location: str = "",
    provider: str = "google",
) -> CredentialProbe:
    """Translate provider failures without copying exception text or secrets.

    The raw messages name an internal resource path, so every branch builds
    its own sentence from values the caller already holds rather than
    forwarding the provider's.
    """
    if isinstance(exc, DefaultCredentialsError):
        return CredentialProbe(
            False,
            "Application Default Credentials were not found.",
            "Run `gcloud auth application-default login`, then try again.",
        )

    message = str(exc).lower()
    if provider == "deepseek":
        if any(
            marker in message
            for marker in (
                "service_disabled",
                "api is disabled",
                "has not been used",
                "not enabled",
            )
        ):
            return CredentialProbe(
                False,
                "DeepSeek model API is not enabled.",
                "Check the DeepSeek endpoint and account access, then try again.",
            )
        if any(
            marker in message
            for marker in (
                "api key not valid",
                "invalid api key",
                "api_key_invalid",
                "unauthenticated",
            )
        ):
            return CredentialProbe(
                False,
                "DeepSeek rejected the API key.",
                "Set a valid SCI_RAG_DEEPSEEK_API_KEY and try again.",
            )
        if isinstance(exc, (ConnectionError, OSError)) or any(
            marker in message
            for marker in ("connection", "network", "dns", "name resolution", "unreachable")
        ):
            return CredentialProbe(
                False,
                "Could not reach the DeepSeek service.",
                "Check the network or proxy, then try again.",
            )
    if any(
        marker in message
        for marker in ("service_disabled", "api is disabled", "has not been used", "not enabled")
    ):
        return CredentialProbe(
            False,
            "The Google model API is not enabled for this project.",
            "Enable the Generative Language API or Vertex AI API for the project, then retry.",
        )
    if (
        provider == "google"
        and not vertex
        and any(
            marker in message
            for marker in (
                "api key not valid",
                "invalid api key",
                "api_key_invalid",
                "unauthenticated",
            )
        )
    ):
        return CredentialProbe(
            False,
            "Google rejected the API key.",
            "Create or copy a valid key from https://aistudio.google.com/apikey.",
        )
    if vertex and any(
        marker in message
        for marker in ("default credentials", "could not automatically determine credentials")
    ):
        return CredentialProbe(
            False,
            "Application Default Credentials were not found.",
            "Run `gcloud auth application-default login`, then try again.",
        )
    where = f" in {location}" if location else ""
    wrong_place = any(marker in message for marker in _NOT_SERVABLE_MARKERS) or (
        _WRONG_PLACE_STATUS in message and "region" in message
    )
    if wrong_place:
        return CredentialProbe(
            False,
            f"The model is not served{where}.",
            "Partner models such as Claude and Grok are served from the global "
            "location. Set SCI_RAG_GCP_LOCATION=global and try again.",
        )
    if any(marker in message for marker in _RETIRED_MODEL_MARKERS):
        return CredentialProbe(
            False,
            f"The model is no longer available to this account. {_safe_provider_text(exc)}",
            "Pick a current model. The provider names a replacement in the message above; "
            "set it as SCI_RAG_LLM_MODEL, then try again.",
        )
    if any(marker in message for marker in _NOT_FOUND_MARKERS):
        return CredentialProbe(
            False,
            f"The model was not found{where}.",
            "Set SCI_RAG_GCP_LOCATION=global if this is a partner model such as "
            "Claude or Grok, which are served only from there. If it is already "
            "global, check the model id and that the model's Model Garden "
            "offering is enabled for this project.",
        )
    if isinstance(exc, (ConnectionError, OSError)) or any(
        marker in message
        for marker in ("connection", "network", "dns", "name resolution", "unreachable")
    ):
        return CredentialProbe(
            False,
            "Could not reach the Google model service.",
            "Check the network or proxy, then try again.",
        )

    if provider == "deepseek":
        fix = "Check SCI_RAG_DEEPSEEK_API_KEY, the model, and the quota."
    elif provider == "anthropic":
        fix = (
            "Check the project ID, ADC login, API enablement, model, and quota."
            if vertex
            else "Check SCI_RAG_ANTHROPIC_API_KEY, the model, and the quota."
        )
    elif provider == "openai-compatible":
        fix = (
            "Check the project ID, ADC login, API enablement, model, and quota."
            if vertex
            else "Check SCI_RAG_OPENAI_API_KEY, the model, and the quota."
        )
    else:
        fix = (
            "Check the project ID, ADC login, API enablement, model, and quota."
            if vertex
            else "Check the AI Studio key, model, and quota, then try again."
        )
    # Carry the provider's own text. Naming only the exception class sent
    # readers to check things that were already fine, and every marker gap
    # below is discovered exactly once, by someone who had this string.
    return CredentialProbe(
        False,
        f"Credential check failed ({type(exc).__name__}). {_safe_provider_text(exc)}",
        fix,
    )
