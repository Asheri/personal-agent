"""`.env` has to reach os.environ, not just pydantic-settings.

pydantic-settings reads `.env` into Settings but never exports it, so Typer's
``envvar=`` lookups and the plain ``os.environ.get("OPENALEX_API_KEY")`` in
the campaign commands could not see values the docs tell users to put there.
"""

from __future__ import annotations

import os
from pathlib import Path

from sci_rag.cli.main import _load_dotenv_into_environ


def test_values_are_exported(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    env = tmp_path / ".env"
    env.write_text("SCI_RAG_CAMPAIGN_MAILTO=you@lbl.gov\n", encoding="utf-8")
    monkeypatch.delenv("SCI_RAG_CAMPAIGN_MAILTO", raising=False)

    loaded = _load_dotenv_into_environ(env)

    assert os.environ["SCI_RAG_CAMPAIGN_MAILTO"] == "you@lbl.gov"
    assert loaded == ["SCI_RAG_CAMPAIGN_MAILTO"]


def test_a_real_environment_variable_wins(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    env = tmp_path / ".env"
    env.write_text("SCI_RAG_CAMPAIGN_MAILTO=file@example.org\n", encoding="utf-8")
    monkeypatch.setenv("SCI_RAG_CAMPAIGN_MAILTO", "shell@example.org")

    loaded = _load_dotenv_into_environ(env)

    assert os.environ["SCI_RAG_CAMPAIGN_MAILTO"] == "shell@example.org"
    assert loaded == []


def test_unprefixed_third_party_keys_are_exported_too(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """OPENALEX_API_KEY can never be a Settings field; it still has to work."""
    env = tmp_path / ".env"
    env.write_text("OPENALEX_API_KEY=abc123\n", encoding="utf-8")
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)

    _load_dotenv_into_environ(env)

    assert os.environ["OPENALEX_API_KEY"] == "abc123"


def test_comments_blanks_exports_and_quotes_are_handled(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "  # an indented comment",
                "export SCI_RAG_LLM_MODEL=gemini-2.5-flash",
                'SCI_RAG_CORS_ORIGINS="https://example.org"',
                "SCI_RAG_SERVER_HOST='127.0.0.1'",
                "MALFORMED_LINE_WITHOUT_EQUALS",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for name in ("SCI_RAG_LLM_MODEL", "SCI_RAG_CORS_ORIGINS", "SCI_RAG_SERVER_HOST"):
        monkeypatch.delenv(name, raising=False)

    _load_dotenv_into_environ(env)

    assert os.environ["SCI_RAG_LLM_MODEL"] == "gemini-2.5-flash"
    assert os.environ["SCI_RAG_CORS_ORIGINS"] == "https://example.org"
    assert os.environ["SCI_RAG_SERVER_HOST"] == "127.0.0.1"
    assert "MALFORMED_LINE_WITHOUT_EQUALS" not in os.environ


def test_a_missing_env_file_is_not_an_error(tmp_path: Path) -> None:
    assert _load_dotenv_into_environ(tmp_path / "nope.env") == []
