"""Localizing prompt wording, with the measurement prompts walled off.

Most of ``domain/prompts/`` is wording. An extraction prompt written for
agricultural residues reads oddly to a membrane chemist, and rewording it is
exactly the kind of tedious, low-risk edit a model is good at.

Two of the prompts are not wording. ``judge_grounding.md`` is blind to the
reference answer on purpose and ``judge_correctness.md`` is the separate
reference-based pass; a well-meaning rewrite that merged them would break
nothing visibly and would quietly change what every judged number means.
``snippet_compression.md`` decides which evidence reaches the answer at all,
and ``ontology_draft.md`` is the drafting machinery itself. All four are
refused by name.

The subtler risk is a rewrite that reads beautifully and drops a ``$SLOT``.
That template loads fine and fails in the middle of a pipeline run, so the
rewrite is re-rendered against dummy values here and rejected if any required
slot went missing.
"""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any

from sci_rag.draft import DraftError, complete, parse_json_object
from sci_rag.draft import render_prompt as _render_template

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sci_rag.domain import DomainProfile
    from sci_rag.llm import LLMClient

PROMPT_NAME = "prompt_localization"

#: The prompts that are wording, and nothing else.
EDITABLE_PROMPTS: tuple[str, ...] = ("entity_extraction", "answer")

#: Prompts this drafter will not touch, and why. The reason is shown to the
#: user, because "no" without a reason reads as an arbitrary limit and invites
#: someone to edit the file by hand instead.
REFUSED_PROMPTS: dict[str, str] = {
    "judge_grounding": (
        "The grounding judge is deliberately blind to the reference answer, and "
        "correctness is graded in a separate reference-based pass. Rewording either "
        "one risks merging them, which would change what every judged number means "
        "without breaking anything visibly."
    ),
    "judge_correctness": (
        "Correctness is the separate reference-based pass that grounding is kept "
        "blind to. Rewording it risks collapsing the two-pass design that makes the "
        "judged scores comparable across runs."
    ),
    "snippet_compression": (
        "Compression decides which evidence reaches the answer at all. It is gated "
        "on paired judged-answer measurements, so its wording is an experimental "
        "condition rather than a matter of taste."
    ),
    "ontology_draft": (
        "This is the drafting machinery itself. Rewriting it with the drafter would "
        "change how future drafts are made, with nothing left to compare against."
    ),
}


def required_slots(template_text: str) -> set[str]:
    """Every ``$SLOT`` the current template depends on."""
    template = Template(template_text)
    return {
        match.group("named") or match.group("braced")
        for match in template.pattern.finditer(template.template)
        if match.group("named") or match.group("braced")
    }


def _prompt_path(domain: DomainProfile, name: str) -> Path:
    return domain.directory / "prompts" / f"{name}.md"


def _check_editable(name: str) -> None:
    if name in REFUSED_PROMPTS:
        raise DraftError(
            f"{name} is not rewritten by this command. {REFUSED_PROMPTS[name]} "
            f"Edit domain/prompts/{name}.md by hand if you have a reason to, and "
            "re-run the evaluation afterwards."
        )
    if name not in EDITABLE_PROMPTS:
        raise DraftError(
            f"{name} is not one of the prompts this command rewrites. "
            f"Choose from: {', '.join(EDITABLE_PROMPTS)}."
        )


def render_prompt(domain: DomainProfile, *, name: str) -> str:
    """The localization prompt for one template, identical in both lanes."""
    _check_editable(name)
    path = _prompt_path(domain, name)
    if not path.exists():
        raise DraftError(f"No prompt template at {path}.")
    current = path.read_text(encoding="utf-8")
    slots = sorted(required_slots(current))
    return _render_template(
        domain.directory,
        PROMPT_NAME,
        PROMPT_NAME=name,
        DOMAIN_NAME=domain.name,
        ENTITY_TYPES=domain.entity_types_block(),
        REQUIRED_SLOTS=", ".join(f"${slot}" for slot in slots) or "(none)",
        CURRENT_TEXT=current,
    )


def parse_reply(raw: str) -> str:
    """Pull the rewritten template out of an untrusted reply."""
    payload = parse_json_object(raw, expecting="prompt")
    rewritten = payload.get("prompt")
    if not isinstance(rewritten, str) or not rewritten.strip():
        raise DraftError(
            'The reply carried no "prompt" string. Expected '
            '{"prompt": "the complete rewritten template"}.'
        )
    return rewritten


def verify_rewrite(original: str, rewritten: str) -> None:
    """Reject a rewrite that lost a slot or will not render.

    Both halves matter. A missing slot is a template that loads and then fails
    mid-run; a stray ``$`` is the same failure with a different cause. Rendering
    against dummy values is the only check that catches either one here rather
    than three commands later.
    """
    if not rewritten.strip():
        raise DraftError("The rewrite was empty.")

    needed = required_slots(original)
    present = required_slots(rewritten)
    missing = sorted(needed - present)
    if missing:
        raise DraftError(
            "The rewrite dropped required slot(s): "
            + ", ".join(f"${slot}" for slot in missing)
            + ". A template missing a slot loads fine and fails mid-run, so this "
            "rewrite was not written."
        )

    added = sorted(present - needed)
    if added:
        raise DraftError(
            "The rewrite introduced slot(s) nothing fills: "
            + ", ".join(f"${slot}" for slot in added)
            + ". Write a literal dollar sign as $$."
        )

    dummy = dict.fromkeys(needed, "x")
    try:
        Template(rewritten).substitute(**dummy)
    except (KeyError, ValueError) as exc:
        raise DraftError(
            f"The rewrite is not a renderable template ({type(exc).__name__}: {exc}). "
            "A literal dollar sign must be written $$."
        ) from exc


async def draft_prompt(
    domain: DomainProfile,
    *,
    name: str,
    llm: LLMClient | None = None,
    settings: Any = None,
    raw_reply: str | None = None,
) -> str:
    """Reword one prompt for this domain, and verify it still renders."""
    _check_editable(name)
    original = _prompt_path(domain, name).read_text(encoding="utf-8")
    if raw_reply is None:
        prompt = render_prompt(domain, name=name)
        raw_reply = await complete(prompt, llm=llm, settings=settings)
    rewritten = parse_reply(raw_reply)
    verify_rewrite(original, rewritten)
    return rewritten


__all__ = [
    "EDITABLE_PROMPTS",
    "PROMPT_NAME",
    "REFUSED_PROMPTS",
    "draft_prompt",
    "parse_reply",
    "render_prompt",
    "required_slots",
    "verify_rewrite",
]
