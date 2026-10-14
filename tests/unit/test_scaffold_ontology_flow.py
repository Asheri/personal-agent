"""Accept, reject, and redraft, driven by a stubbed model.

Drafting is the one question the wizard cannot answer from a default, so the
loop around it is worth pinning: an accepted draft has to reach the answers,
a rejected one has to leave the worked example in place, and a draft that
fails validation must not be written out at all.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from sci_rag.llm import MockLLM
from sci_rag.scaffold.wizard import confirm_ontology_draft

DOMAIN_DIR = Path(__file__).parents[2] / "domain"

_DRAFT = json.dumps(
    {
        "entity_types": [{"name": "Membrane", "description": "A separation layer"}],
        "relation_types": [{"name": "REMOVES"}],
        "query_classes": [{"name": "performance", "keywords": ["flux"]}],
    }
)


def _run(responses: list[str], replies: str):  # type: ignore[no-untyped-def]
    output = io.StringIO()
    config = confirm_ontology_draft(
        DOMAIN_DIR,
        project_name="Membrane KB",
        description="Membrane chemistry",
        llm=MockLLM(responses=responses),
        input_stream=io.StringIO(replies),
        output_stream=output,
    )
    return config, output.getvalue()


def test_pressing_enter_accepts_the_draft() -> None:
    config, transcript = _run([_DRAFT], "\n")
    assert config is not None
    assert [e.name for e in config.entity_types] == ["Membrane"]
    assert "Accept this ontology?" in transcript


def test_the_draft_is_shown_before_it_is_accepted() -> None:
    _, transcript = _run([_DRAFT], "\n")
    assert "Drafting an ontology" in transcript
    assert "Entity types" in transcript
    assert "Membrane" in transcript


def test_declining_keeps_the_worked_example() -> None:
    config, _ = _run([_DRAFT], "n\n")
    assert config is None


def test_redraft_asks_the_model_again() -> None:
    second = json.dumps(
        {
            "entity_types": [{"name": "Contaminant"}],
            "relation_types": [],
            "query_classes": [],
        }
    )
    config, _ = _run([_DRAFT, second], "redraft\ny\n")
    assert config is not None
    assert [e.name for e in config.entity_types] == ["Contaminant"]


def test_a_malformed_draft_is_reported_and_not_returned() -> None:
    config, transcript = _run(["I cannot help with that."], "n\n")
    assert config is None
    assert "could not be used" in transcript


def test_a_malformed_draft_can_be_retried() -> None:
    config, _ = _run(["not json", _DRAFT], "y\n\n")
    assert config is not None
    assert [e.name for e in config.entity_types] == ["Membrane"]


def test_the_loop_gives_up_rather_than_spinning() -> None:
    """A model that keeps returning junk must not hang the wizard."""
    config, transcript = _run(["junk"] * 10, "y\ny\ny\ny\ny\n")
    assert config is None
    assert "could not be used" in transcript


def test_provider_exception_is_reported_without_a_traceback_or_secret() -> None:
    class ExplodingLLM:
        async def generate(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("provider failed around secret-key-value")

    output = io.StringIO()
    config = confirm_ontology_draft(
        DOMAIN_DIR,
        project_name="Membrane KB",
        description="Membrane chemistry",
        llm=ExplodingLLM(),  # type: ignore[arg-type]
        input_stream=io.StringIO("n\n"),
        output_stream=output,
    )

    transcript = output.getvalue()
    assert config is None
    assert "RuntimeError" in transcript
    assert "Traceback" not in transcript
    assert "secret-key-value" not in transcript
