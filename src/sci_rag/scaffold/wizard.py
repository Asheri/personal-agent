"""The question and answer session.

Three ways in, one answer set out: an interactive session, ``--defaults`` for
a straight-through run, and ``--answers-file`` for reproducible generation in
CI and in the documentation. All three walk the same list in
:mod:`sci_rag.scaffold.questions`, so a question added there is asked by all
three without further wiring.

Prompts are written to the output stream directly rather than through Rich's
prompt helpers. The session transcript is a documented artifact (it is the
example on the homepage), so its exact shape is part of the contract and is
worth more here than styled output.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

import yaml

from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.questions import QUESTIONS, default_for, is_asked


class AnswerFileError(ValueError):
    """An answers file named something the wizard does not ask about."""


def _load_answer_file(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise AnswerFileError(f"{path} must contain a mapping of question name to answer.")
    known = {question.name for question in QUESTIONS}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise AnswerFileError(
            f"{path} names questions the wizard does not ask: {', '.join(unknown)}. "
            f"Known questions: {', '.join(q.name for q in QUESTIONS)}."
        )
    answers = {key: str(value) for key, value in raw.items()}
    _refuse_interactive_only_answers(path, answers)
    return answers


def answer_file_fields(path: Path, *, preset: dict[str, str] | None = None) -> set[str]:
    """Read an answers file once and return the keys the user actually supplied.

    ``preset`` lets the caller keep the parsed values while this helper returns
    their provenance, so validation and answer collection do not each parse the
    same YAML document again.
    """
    answers = _load_answer_file(path)
    if preset is not None:
        preset.update(answers)
    return set(answers)


# Values a person has to be present for. An answers file that names one used
# to be accepted and then quietly replaced, which is how a reproducible
# generation route produced something nobody asked for. See #164.
_INTERACTIVE_ONLY = {
    "ontology": {
        "draft_with_llm": (
            "Drafting an ontology means reading what the model proposed and "
            "accepting or redrafting it, which needs a terminal. Write "
            "`ontology: keep_demo_example` or `ontology: blank` instead, then "
            "draft into the generated project with `sci-rag draft ontology "
            "--from-corpus`. That command also takes `--print-prompt` and "
            "`--from-file`, which run the same validation with no model call."
        )
    }
}


def _refuse_interactive_only_answers(path: Path, answers: dict[str, str]) -> None:
    for question, refused in _INTERACTIVE_ONLY.items():
        value = answers.get(question)
        if value in refused:
            raise AnswerFileError(
                f"{path} answers `{question}: {value}`, which an answers file cannot do. "
                f"{refused[value]}"
            )


def _read(stream: TextIO) -> str | None:
    """One answer, or ``None`` at end of input."""
    line = stream.readline()
    if line == "":
        return None
    return line.strip()


def collect_answers(
    *,
    defaults: bool = False,
    answers_file: Path | None = None,
    quick: bool | None = None,
    plain: bool = False,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    preset: Mapping[str, str] | None = None,
    explicit_fields_out: set[str] | None = None,
) -> dict[str, str]:
    """Walk the question list and return the raw string answers.

    Gates are evaluated against the answers gathered so far, which is why this
    is a single ordered pass rather than a dictionary comprehension: whether a
    question is asked at all can depend on the answer above it.
    """
    preset_values = (
        dict(preset)
        if preset is not None
        else (_load_answer_file(answers_file) if answers_file is not None else {})
    )
    non_interactive = defaults or answers_file is not None
    from sci_rag.scaffold.prompt import QuestionaryPrompter, make_prompter

    prompter = make_prompter(
        input_stream=input_stream,
        output_stream=output_stream,
        plain=plain,
    )
    detected_manager = None
    if not non_interactive and isinstance(prompter, QuestionaryPrompter):
        from sci_rag.scaffold.runners import detect_environment_manager

        detected_manager = detect_environment_manager()
    if not non_interactive:
        prompter.banner()
        if quick is None:
            mode = prompter.menu(
                "Setup",
                (
                    ("quick", "Quick - Six questions, sensible defaults for the rest"),
                    ("advanced", "Advanced - Every option for full customization"),
                ),
                "quick",
            )
            quick = mode == "quick"

    answers: dict[str, str] = {}

    def record_explicit(question_name: str) -> None:
        if explicit_fields_out is not None:
            explicit_fields_out.add(question_name)

    def record_prompt_result(question_name: str, value: str, default: str) -> None:
        is_explicit = getattr(
            prompter,
            "last_input_was_explicit",
            value != default,
        )
        if is_explicit:
            record_explicit(question_name)

    for question in QUESTIONS:
        if not is_asked(question, answers):
            continue
        default = default_for(question, answers)
        if question.name == "environment_manager" and detected_manager is not None:
            default = detected_manager
            prompter.note(f"Detected {detected_manager} on PATH; preselected below.")
        if question.name in preset_values:
            answers[question.name] = preset_values[question.name]
            record_explicit(question.name)
        elif non_interactive and question.noninteractive_default is not None:
            answers[question.name] = question.noninteractive_default
        elif non_interactive or (quick is True and not question.quick):
            answers[question.name] = default
        elif question.name == "google_api_key" and (
            existing_key := os.environ.get("SCI_RAG_GOOGLE_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        ):
            if prompter.confirm(
                "Use the Google API key already set in your environment?", default=True
            ):
                answers[question.name] = existing_key
                prompter.note("Using the existing environment key; its value stays hidden.")
            else:
                answers[question.name] = prompter.secret(question, default)
            record_prompt_result(
                question.name,
                answers[question.name],
                default,
            )
        elif question.secret:
            answers[question.name] = prompter.secret(question, default)
            record_prompt_result(
                question.name,
                answers[question.name],
                default,
            )
        elif question.choices:
            answers[question.name] = prompter.choice(question, default)
            record_prompt_result(
                question.name,
                answers[question.name],
                default,
            )
        else:
            answers[question.name] = prompter.text(question, default)
            record_prompt_result(
                question.name,
                answers[question.name],
                default,
            )
    return answers


def run_wizard(
    *,
    defaults: bool = False,
    answers_file: Path | None = None,
    quick: bool | None = None,
    plain: bool = False,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> ProjectAnswers:
    preset: dict[str, str] = {}
    explicit_fields: set[str] = set()
    if answers_file is not None:
        explicit_fields.update(answer_file_fields(answers_file, preset=preset))

    raw = collect_answers(
        defaults=defaults,
        answers_file=answers_file,
        quick=quick,
        plain=plain,
        input_stream=input_stream,
        output_stream=output_stream,
        preset=preset,
        explicit_fields_out=explicit_fields,
    )
    return ProjectAnswers.from_raw(raw, explicit_fields=explicit_fields)


def confirm_ontology_draft(
    domain_dir: Path,
    *,
    project_name: str,
    description: str,
    llm: object | None = None,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    max_attempts: int = 3,
) -> object | None:
    """Draft an ontology and let the user accept, reject, or redraft it.

    Returns the accepted :class:`~sci_rag.domain.DomainConfig`, or ``None`` to
    fall back to the worked example. A draft that fails validation is reported
    and offered again rather than written out: model output is untrusted, and
    a junk ontology only fails later, when the graph extractor reads it.
    """
    import asyncio

    from sci_rag.scaffold.ontology import OntologyDraftError, draft_ontology, summarize

    stdin = input_stream if input_stream is not None else sys.stdin
    stdout = output_stream if output_stream is not None else sys.stdout

    for _ in range(max_attempts):
        stdout.write(f'\n  Drafting an ontology for "{description}"...\n\n')
        try:
            config = asyncio.run(
                draft_ontology(
                    domain_dir,
                    project_name=project_name,
                    description=description,
                    llm=llm,  # type: ignore[arg-type]
                )
            )
        except Exception as exc:
            detail = str(exc) if isinstance(exc, OntologyDraftError) else type(exc).__name__
            stdout.write(f"  The draft could not be used: {detail}\n")
            if not _wants_retry(stdin, stdout):
                return None
            continue

        for label, value in summarize(config):
            stdout.write(f"  {label.ljust(18)}{value}\n")

        stdout.write("\n  Accept this ontology? [y/n/redraft] (y): ")
        reply = _read(stdin)
        if reply is None:
            return config
        stdout.write(f"{reply}\n" if reply else "\n")
        answer = (reply or "y").strip().lower()
        if answer in {"y", "yes"}:
            return config
        if answer in {"n", "no"}:
            return None
        # Anything else, including "redraft", asks the model again.
    stdout.write("  Keeping the worked example after several drafts.\n")
    return None


def _wants_retry(stdin: TextIO, stdout: TextIO) -> bool:
    stdout.write("  Try again? [y/n] (n): ")
    reply = _read(stdin)
    if reply is None:
        return False
    stdout.write(f"{reply}\n" if reply else "\n")
    return (reply or "n").strip().lower() in {"y", "yes"}
