"""Prompt adapter selection and user-visible terminal behavior."""

from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest

from sci_rag.scaffold.prompt import (
    PlainPrompter,
    PromptAborted,
    QuestionaryPrompter,
    make_prompter,
)
from sci_rag.scaffold.questions import Question


class _TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_injected_streams_use_the_plain_prompt_contract() -> None:
    """Scripted callers must never enter a terminal UI event loop."""
    input_stream = io.StringIO()
    output_stream = io.StringIO()
    prompter = make_prompter(input_stream=input_stream, output_stream=output_stream)

    assert isinstance(prompter, PlainPrompter)
    assert prompter.stdin is input_stream
    assert prompter.stdout is output_stream

    input_only = io.StringIO()
    output_only = io.StringIO()
    with_input = make_prompter(input_stream=input_only)
    with_output = make_prompter(output_stream=output_only)
    assert isinstance(with_input, PlainPrompter)
    assert isinstance(with_output, PlainPrompter)
    assert with_input.stdin is input_only
    assert with_output.stdout is output_only


def test_plain_text_prompt_preserves_echo_and_validation_output() -> None:
    """The script-friendly prompt remains an exact line-oriented contract."""

    def validate(value: str) -> str:
        if value != "accepted":
            raise ValueError("use the accepted value")
        return value

    output = io.StringIO()
    prompter = PlainPrompter(io.StringIO("wrong\naccepted\n"), output)

    answer = prompter.text(Question("field", "field", "default", validator=validate), "default")

    assert answer == "accepted"
    assert output.getvalue() == (
        "field (default): wrong\n  use the accepted value\nfield (default): accepted\n"
    )


def test_plain_prompt_marks_only_nonempty_input_as_explicit() -> None:
    question = Question("field", "field", "default")

    empty = PlainPrompter(io.StringIO("\n"), io.StringIO())
    empty.text(question, "default")
    assert empty.last_input_was_explicit is False

    explicit = PlainPrompter(io.StringIO("typed\n"), io.StringIO())
    explicit.text(question, "default")
    assert explicit.last_input_was_explicit is True


def test_plain_prompt_updates_explicit_flag_for_each_input_kind() -> None:
    choice = Question("choice", "choice", "one", choices=("one", "two"))
    prompter = PlainPrompter(io.StringIO("two\n"), io.StringIO())
    prompter.choice(choice, "one")
    assert prompter.last_input_was_explicit is True

    menu_prompter = PlainPrompter(io.StringIO("2\n"), io.StringIO())
    menu_prompter.menu("mode", (("one", "One"), ("two", "Two")), "one")
    assert menu_prompter.last_input_was_explicit is True

    confirm_prompter = PlainPrompter(io.StringIO("y\n"), io.StringIO())
    confirm_prompter.confirm("Continue?", default=False)
    assert confirm_prompter.last_input_was_explicit is True


def test_plain_choice_prompt_preserves_numbered_menu_and_retry_output() -> None:
    output = io.StringIO()
    prompter = PlainPrompter(io.StringIO("9\n2\n"), output)
    question = Question("mode", "mode", "quick", choices=("quick", "advanced"))

    answer = prompter.choice(question, "quick")

    assert answer == "advanced"
    assert output.getvalue() == (
        "Select mode\n"
        "1 - quick\n"
        "2 - advanced\n"
        "Choose from [1/2] (1): 9\n"
        "  '9' is not one of quick, advanced.\n"
        "Select mode\n"
        "1 - quick\n"
        "2 - advanced\n"
        "Choose from [1/2] (1): 2\n"
    )


def test_plain_text_prompt_states_the_question_in_words_above_the_field() -> None:
    output = io.StringIO()
    question = Question(
        "google_api_key",
        "google_api_key",
        "",
        label="Google AI Studio API key",
        help="Get one at https://aistudio.google.com/apikey. Blank to add it later.",
    )

    answer = PlainPrompter(io.StringIO("\n"), output).text(question, "")

    assert answer == ""
    assert output.getvalue() == (
        "Google AI Studio API key. Get one at https://aistudio.google.com/apikey. "
        "Blank to add it later.\n"
        "google_api_key (): \n"
    )


def test_plain_choice_menu_explains_each_option() -> None:
    output = io.StringIO()
    question = Question(
        "credentials",
        "credentials",
        "offline",
        choices=("google_ai_studio", "offline"),
        label="How will you reach a model?",
        choice_help={"google_ai_studio": "Shortest local setup; no manual Cloud setup"},
    )

    answer = PlainPrompter(io.StringIO("1\n"), output).choice(question, "offline")

    assert answer == "google_ai_studio"
    assert output.getvalue() == (
        "Select credentials: How will you reach a model?\n"
        "1 - google_ai_studio: Shortest local setup; no manual Cloud setup\n"
        "2 - offline\n"
        "Choose from [1/2] (2): 1\n"
    )


def test_plain_validated_choice_keeps_the_legacy_text_bytes() -> None:
    output = io.StringIO()
    question = Question(
        "python_version",
        "python_version",
        "3.12",
        choices=("3.11", "3.12"),
        validator=lambda value: value,
    )

    answer = PlainPrompter(io.StringIO("\n"), output).choice(question, "3.12")

    assert answer == "3.12"
    assert output.getvalue() == "python_version (3.12): \n"


def test_plain_secret_prompt_never_echoes_the_answer() -> None:
    output = io.StringIO()
    prompter = PlainPrompter(io.StringIO("hidden-value\n"), output)

    answer = prompter.secret(Question("key", "key", "", secret=True), "")

    assert answer == "hidden-value"
    assert output.getvalue() == "key (): \n"
    assert "hidden-value" not in output.getvalue()


def test_supported_tty_uses_the_interactive_prompt_adapter(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "stdin", _TTY())
    monkeypatch.setattr(sys, "stdout", _TTY())
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    assert isinstance(make_prompter(), QuestionaryPrompter)


def _supported_tty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "stdin", _TTY())
    monkeypatch.setattr(sys, "stdout", _TTY())
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")


def test_explicit_plain_mode_overrides_a_supported_tty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _supported_tty(monkeypatch)

    assert isinstance(make_prompter(plain=True), PlainPrompter)


def test_non_tty_standard_streams_use_plain_prompts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    assert isinstance(make_prompter(), PlainPrompter)


def test_no_color_uses_plain_prompts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _supported_tty(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")

    assert isinstance(make_prompter(), PlainPrompter)


@pytest.mark.parametrize("term", ["", "dumb"])
def test_unsupported_term_uses_plain_prompts(monkeypatch, term: str) -> None:  # type: ignore[no-untyped-def]
    _supported_tty(monkeypatch)
    monkeypatch.setenv("TERM", term)

    assert isinstance(make_prompter(), PlainPrompter)


def test_missing_questionary_falls_back_to_plain_prompts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _supported_tty(monkeypatch)

    def missing(_name: str) -> None:
        raise ImportError("questionary is unavailable")

    monkeypatch.setattr("sci_rag.scaffold.prompt.import_module", missing)

    assert isinstance(make_prompter(), PlainPrompter)


def test_cancelling_an_interactive_question_aborts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake = SimpleNamespace(
        Style=lambda rules: rules,
        text=lambda *_args, **_kwargs: SimpleNamespace(ask=lambda: None),
    )
    monkeypatch.setattr("sci_rag.scaffold.prompt.import_module", lambda _name: fake)
    prompter = QuestionaryPrompter()

    with pytest.raises(PromptAborted, match="Setup cancelled"):
        prompter.text(Question("project", "project", "Default"), "Default")


def test_interactive_choices_show_labels_help_and_recommendation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    shown: dict[str, object] = {}

    class Choice:
        def __init__(self, title: str, value: str) -> None:
            self.title = title
            self.value = value

    def select(message: str, **kwargs):  # type: ignore[no-untyped-def]
        shown["message"] = message
        shown.update(kwargs)
        return SimpleNamespace(ask=lambda: "vertex_ai")

    fake = SimpleNamespace(Choice=Choice, Style=lambda rules: rules, select=select)
    monkeypatch.setattr("sci_rag.scaffold.prompt.import_module", lambda _name: fake)
    prompter = QuestionaryPrompter()
    question = Question(
        "credentials",
        "credentials",
        "google_ai_studio",
        choices=("google_ai_studio", "vertex_ai", "offline"),
        label="How will you reach a model?",
        choice_help={
            "google_ai_studio": "Shortest local setup; no manual Cloud setup",
            "vertex_ai": "Billed through a Google Cloud project",
            "offline": "No model calls",
        },
        help="Choose the access mode for this project.",
    )

    assert prompter.choice(question, "google_ai_studio") == "vertex_ai"
    assert shown["message"] == "How will you reach a model?"
    choices = shown["choices"]
    assert isinstance(choices, list)
    assert "Shortest local setup; no manual Cloud setup" in choices[0].title
    assert "(recommended)" in choices[0].title
    assert "(recommended)" not in choices[1].title
    assert shown["instruction"] == "Choose the access mode for this project."


def test_interactive_text_and_secret_prompts_use_the_right_input_kind(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    shown: list[tuple[str, str, dict[str, object]]] = []

    def prompt(kind: str, answer: str):  # type: ignore[no-untyped-def]
        def build(message: str, **kwargs):  # type: ignore[no-untyped-def]
            shown.append((kind, message, kwargs))
            return SimpleNamespace(ask=lambda: answer)

        return build

    fake = SimpleNamespace(
        Style=lambda rules: rules,
        text=prompt("text", "Membrane KB"),
        password=prompt("password", "not-printed"),
    )
    monkeypatch.setattr("sci_rag.scaffold.prompt.import_module", lambda _name: fake)
    prompter = QuestionaryPrompter()

    assert (
        prompter.text(
            Question("project", "project", "Default", label="Project name", help="Be concise."),
            "Default",
        )
        == "Membrane KB"
    )
    assert (
        prompter.secret(
            Question("key", "key", "", label="API key", secret=True),
            "",
        )
        == "not-printed"
    )
    assert [kind for kind, _message, _kwargs in shown] == ["text", "password"]
    assert shown[0][1] == "Project name"
    assert shown[0][2]["instruction"] == "Be concise."


def test_questionary_marks_explicit_values_from_prompt_results(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    answers = iter(["Default", "Changed"])

    def build(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(ask=lambda: next(answers))

    fake = SimpleNamespace(Style=lambda rules: rules, text=build)
    monkeypatch.setattr("sci_rag.scaffold.prompt.import_module", lambda _name: fake)
    prompter = QuestionaryPrompter()
    question = Question("field", "field", "Default")

    prompter.text(question, "Default")
    assert prompter.last_input_was_explicit is False

    prompter.text(question, "Default")
    assert prompter.last_input_was_explicit is True


def test_interactive_text_accepts_an_unedited_hint_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def build(_message: str, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return SimpleNamespace(ask=lambda: "Hint rather than an email")

    def email(value: str) -> str:
        if "@" not in value:
            raise ValueError("enter an email or leave the hint unchanged")
        return value

    fake = SimpleNamespace(Style=lambda rules: rules, text=build)
    monkeypatch.setattr("sci_rag.scaffold.prompt.import_module", lambda _name: fake)
    prompter = QuestionaryPrompter()
    question = Question("email", "email", "", validator=email)

    assert prompter.text(question, "Hint rather than an email") == "Hint rather than an email"
    validate = captured["validate"]
    assert callable(validate)
    assert validate("Hint rather than an email") is True
    assert validate("not-an-email") == "enter an email or leave the hint unchanged"
    assert validate("you@example.org") is True


def test_interactive_menu_returns_machine_value_and_marks_its_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    shown: dict[str, object] = {}

    class Choice:
        def __init__(self, title: str, value: str) -> None:
            self.title = title
            self.value = value

    def select(message: str, **kwargs):  # type: ignore[no-untyped-def]
        shown["message"] = message
        shown.update(kwargs)
        return SimpleNamespace(ask=lambda: "quick")

    fake = SimpleNamespace(Choice=Choice, Style=lambda rules: rules, select=select)
    monkeypatch.setattr("sci_rag.scaffold.prompt.import_module", lambda _name: fake)
    prompter = QuestionaryPrompter()

    assert (
        prompter.menu(
            "Setup",
            (("quick", "Quick - Six questions"), ("advanced", "Advanced - Every option")),
            "quick",
        )
        == "quick"
    )
    assert shown["message"] == "Setup"
    choices = shown["choices"]
    assert isinstance(choices, list)
    assert choices[0].value == "quick"
    assert "(recommended)" in choices[0].title


def test_interactive_banner_notes_errors_and_confirmation_are_styled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    printed: list[tuple[str, object]] = []
    confirmed: dict[str, object] = {}

    def confirm(message: str, **kwargs):  # type: ignore[no-untyped-def]
        confirmed["message"] = message
        confirmed.update(kwargs)
        return SimpleNamespace(ask=lambda: True)

    fake = SimpleNamespace(
        Style=lambda rules: rules,
        print=lambda message, style=None: printed.append((message, style)),
        confirm=confirm,
    )
    monkeypatch.setattr("sci_rag.scaffold.prompt.import_module", lambda _name: fake)
    prompter = QuestionaryPrompter()

    prompter.banner()
    prompter.note("Detected uv on PATH.")
    prompter.error("The key was rejected.")

    assert prompter.confirm("Continue?", default=False) is True
    assert any("Sci RAG Kit" in message for message, _style in printed)
    assert any("Detected uv" in message for message, _style in printed)
    assert any("key was rejected" in message for message, _style in printed)
    assert confirmed["message"] == "Continue?"
    assert confirmed["default"] is False
