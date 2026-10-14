"""The shipped generation default, named once.

`gemini-2.5-flash` was the default in v0.4.0 and it is refused for any
newly issued AI Studio key: `404 This model is no longer available to new
users`. Every synthetic branch of the onboarding route passed while the one
branch a real reader takes was broken, because nothing offline can tell a
model id that works from one that does not.

Offline tests cannot fix that. What they can do is make the default
impossible to update by halves. It was written out longhand in eight places
under `src/`, so a fix applied to `config.py` alone would leave the wizard,
the scaffolder, and the preflight still offering a dead model, and the
resulting bug would look exactly like the one being fixed.

The live half of this guard is `tests/cloud/test_default_model_live.py`,
which calls the model and is skipped without credentials.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import types
from pathlib import Path

import pytest

from sci_rag.config import DEFAULT_LLM_MODEL, Settings

ROOT = Path(__file__).resolve().parents[2]

# Files that offer a generation model default to a user. Each has to take it
# from the constant rather than restate it.
DEFAULT_SITES = (
    "src/sci_rag/config.py",
    "src/sci_rag/cli/new.py",
    "src/sci_rag/cli/init.py",
    "src/sci_rag/scaffold/questions.py",
    "src/sci_rag/scaffold/answers.py",
    "src/sci_rag/scaffold/preflight.py",
)

RETIRED = frozenset(
    {
        # Refused for new AI Studio keys as of 2026-08-31, captured from the
        # provider rather than read off a model card.
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
    }
)


def _load_default_model_cloud_test() -> types.ModuleType:
    path = ROOT / "tests" / "cloud" / "test_default_model_live.py"
    spec = importlib.util.spec_from_file_location("default_model_live_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_model_live_requires_the_default_provider_credential(monkeypatch) -> None:
    for name in ("SCI_RAG_DEEPSEEK_API_KEY", "SCI_RAG_GOOGLE_API_KEY", "SCI_RAG_GCP_PROJECT"):
        monkeypatch.setenv(name, "")

    module = _load_default_model_cloud_test()

    with pytest.raises(pytest.skip.Exception) as caught:
        module._settings()

    message = str(caught.value)
    assert "DeepSeek" in message
    assert "Google" not in message


def test_the_default_is_declared_once_and_is_not_a_retired_model() -> None:
    """Read the field default, not an instance.

    `Settings()` merges `.env`, so on a developer machine it reports whatever
    that file says. The shipped default is the field default, and that is the
    thing a new reader gets.
    """
    assert Settings.model_fields["llm_model"].default == DEFAULT_LLM_MODEL
    assert DEFAULT_LLM_MODEL not in RETIRED


def test_no_source_file_restates_the_default_model_longhand() -> None:
    """A second copy of the id is a second thing to forget.

    Matching the literal rather than the constant is deliberate: the failure
    this guards against is someone writing the id out again, and that is only
    visible in the source text.
    """
    offenders = []
    for relative in DEFAULT_SITES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if re.search(rf'["\']{re.escape(DEFAULT_LLM_MODEL)}["\']', line):
                if relative == "src/sci_rag/config.py" and "DEFAULT_LLM_MODEL" in line:
                    continue  # the one declaration
                offenders.append(f"{relative}:{number}: {line.strip()}")

    assert offenders == [], (
        "take the default from sci_rag.config.DEFAULT_LLM_MODEL rather than "
        f"restating it: {offenders}"
    )


def test_no_source_file_still_offers_a_retired_model_as_a_default() -> None:
    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for retired in RETIRED:
                if f'"{retired}"' in line or f"'{retired}'" in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")

    assert offenders == [], f"these still name a model new keys cannot call: {offenders}"


def test_the_example_environment_file_agrees_with_the_code() -> None:
    """`.env.example` is what a reader copies, so a stale id there is the bug.

    `scripts/render_config_docs.py` already checks that every settings field
    appears here. It does not check that the values match, and the value is
    what a reader ends up running.
    """
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    match = re.search(r"^SCI_RAG_LLM_MODEL=(.+)$", example, re.MULTILINE)
    assert match, "SCI_RAG_LLM_MODEL is missing from .env.example"
    assert match.group(1).strip() == DEFAULT_LLM_MODEL


def test_the_constant_is_a_plain_string_literal() -> None:
    """Readable by a human scanning the file, and by the release checklist.

    A computed default would make the value invisible at the declaration,
    which is the property that let the stale one survive.
    """
    tree = ast.parse((ROOT / "src/sci_rag/config.py").read_text(encoding="utf-8"))
    assigned = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "DEFAULT_LLM_MODEL" for t in node.targets)
    ]
    assert len(assigned) == 1
    assert isinstance(assigned[0], ast.Constant)
    assert isinstance(assigned[0].value, str)
