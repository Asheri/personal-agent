"""Drafting the files a scientist would otherwise hand-author.

Four artifacts stand between the template and a working domain RAG: the
ontology, the corpus manifest, the seed questions, and the prompt wording.
Each drafter here offers the same three lanes, and the shape of this module
is what keeps them one system rather than three:

* **Lane A** gathers context from what is already on disk or in the database,
  calls the configured model, and validates the reply through the same
  pydantic model the loader uses.
* **Lane B** renders the identical prompt to stdout so a scientist with no
  credentials can handle it locally or use an approved assistant, then reads
  the reply back from a file through the identical validation.
* **Lane C** is writing the file by hand, which nothing here changes.

Model output is untrusted everywhere. A drafter parses, validates, and (for
seed questions) verifies the model's claims against the passages it was
shown, then writes a ``.proposed`` file for review rather than overwriting
work a human vouched for.

The LLM client is imported inside the functions that need it, matching
:mod:`sci_rag.scaffold`: rendering a prompt must not pull in the generation
stack.
"""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sci_rag.llm import LLMClient

#: Appended to a target path when a drafter proposes rather than applies.
PROPOSED_SUFFIX = ".proposed"


class DraftError(RuntimeError):
    """A draft could not be trusted, or the context for one could not be gathered.

    One exception type across every drafter, because the CLI's job is the
    same in all of them: print the reason and exit non-zero rather than
    write a file nobody can rely on.
    """


def prompt_template(domain_dir: Path, name: str) -> Template:
    """Load a drafting prompt from the domain profile.

    Drafting prompts live in ``domain/prompts/`` beside every other prompt,
    so a user can read and edit the instructions the model is given without
    touching package code.
    """
    path = domain_dir / "prompts" / f"{name}.md"
    if not path.exists():
        raise DraftError(
            f"No drafting prompt at {path}. It ships in the template's "
            "domain/prompts/ directory; copy it there if your project predates it."
        )
    return Template(path.read_text(encoding="utf-8"))


def render_prompt(domain_dir: Path, name: str, **slots: str) -> str:
    """Render a drafting prompt, failing loudly on a slot the template needs."""
    try:
        return prompt_template(domain_dir, name).substitute(**slots)
    except KeyError as exc:
        raise DraftError(
            f"The {name} prompt has a $ slot this version of the kit does not fill: {exc}."
        ) from exc


async def complete(
    prompt: str,
    *,
    llm: LLMClient | None = None,
    settings: Any = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """Ask the configured model for a JSON reply.

    Lane A's single point of contact with a provider. Lane B never reaches
    this function, which is why a project with no credentials can still use
    every drafter.
    """
    if llm is None:
        from sci_rag.config import get_settings
        from sci_rag.llm import get_llm

        llm = get_llm(settings or get_settings())
    return await llm.generate(
        prompt, temperature=temperature, max_tokens=max_tokens, json_mode=True
    )


def parse_json_object(raw: str, *, expecting: str) -> dict[str, Any]:
    """Parse an untrusted model reply into a JSON object, or say why not."""
    from sci_rag.llm import parse_json_loosely

    try:
        payload = parse_json_loosely(raw)
    except ValueError as exc:
        raise DraftError(
            f"The model did not return JSON ({exc}). Expected an object with {expecting!r}."
        ) from exc
    if not isinstance(payload, dict):
        raise DraftError(
            f"Expected a JSON object with {expecting!r}, got {type(payload).__name__}."
        )
    return payload


def read_reply(path: Path) -> str:
    """Read a Lane B reply that some other assistant produced."""
    if not path.exists():
        raise DraftError(f"No reply file at {path}.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise DraftError(f"The reply file at {path} is empty.")
    return text


def proposed_path(target: Path) -> Path:
    """Where a drafter writes when it is proposing rather than applying."""
    return target.with_name(target.name + PROPOSED_SUFFIX)


__all__ = [
    "PROPOSED_SUFFIX",
    "DraftError",
    "complete",
    "parse_json_object",
    "prompt_template",
    "proposed_path",
    "read_reply",
    "render_prompt",
]
