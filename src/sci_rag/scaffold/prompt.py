"""Terminal prompting behind one selectable seam."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from importlib import import_module
from types import ModuleType
from typing import Protocol, TextIO

from sci_rag.scaffold.questions import Question

_MAX_ATTEMPTS = 5


class Prompter(Protocol):
    """The prompting interface shared by plain and interactive adapters."""

    def text(self, question: Question, default: str) -> str: ...

    def choice(self, question: Question, default: str) -> str: ...

    def secret(self, question: Question, default: str) -> str: ...

    def confirm(self, message: str, *, default: bool = True) -> bool: ...

    def menu(self, title: str, options: Sequence[tuple[str, str]], default: str) -> str: ...

    def note(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...

    def banner(self) -> None: ...


class PromptAborted(RuntimeError):
    """The user cancelled an interactive prompt."""


def describe(question: Question) -> str:
    """The question in words, as the arrow-key menus show it.

    The plain adapter keeps its byte-stable ``field (default):`` line, because
    scripts and the homepage transcript parse it, and writes this above it so
    a person at a pipe or in CI reads the same question a terminal user does.
    Empty when a question carries neither a label nor help.
    """
    text = question.label
    if question.help:
        if not text:
            return question.help
        separator = " " if text.endswith(("?", ".", "!", ":")) else ". "
        text = f"{text}{separator}{question.help}"
    return text


class PlainPrompter:
    """The stable line-oriented adapter used by scripts and non-TTY sessions."""

    def __init__(self, stdin: TextIO, stdout: TextIO) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.last_input_was_explicit = False

    def _read_input(self) -> str | None:
        line = self.stdin.readline()
        if line == "":
            self.last_input_was_explicit = False
            return None
        value = line.strip()
        self.last_input_was_explicit = bool(value)
        return value

    def _describe(self, question: Question) -> None:
        description = describe(question)
        if description:
            self.stdout.write(f"{description}\n")

    def text(self, question: Question, default: str) -> str:
        self._describe(question)
        for _ in range(_MAX_ATTEMPTS):
            self.stdout.write(f"{question.prompt} ({default}): ")
            raw = self._read_input()
            if raw is None:
                return default
            self.stdout.write(f"{raw}\n" if raw else "\n")
            if not raw:
                return default
            if question.validator is None:
                return raw
            try:
                return question.validator(raw)
            except ValueError as exc:
                self.stdout.write(f"  {exc}\n")
        return default

    def secret(self, question: Question, default: str) -> str:
        self._describe(question)
        for _ in range(_MAX_ATTEMPTS):
            self.stdout.write(f"{question.prompt} ({default}): ")
            raw = self._read_input()
            if raw is None:
                return default
            self.stdout.write("\n")
            if not raw:
                return default
            if question.validator is None:
                return raw
            try:
                return question.validator(raw)
            except ValueError as exc:
                self.stdout.write(f"  {exc}\n")
        return default

    def choice(self, question: Question, default: str) -> str:
        # A validated choice was a text prompt before the TTY layer existed.
        # Keep injected-stream output stable while the TTY adapter renders it
        # as an arrow-key menu.
        if question.validator is not None:
            return self.text(question, default)
        choices = list(question.choices or ())
        default_index = choices.index(default) + 1 if default in choices else 1
        menu = "/".join(str(i) for i in range(1, len(choices) + 1))
        description = describe(question)
        heading = f"Select {question.prompt}" + (f": {description}" if description else "")

        for _ in range(_MAX_ATTEMPTS):
            self.stdout.write(f"{heading}\n")
            for index, choice in enumerate(choices, start=1):
                explanation = question.choice_help.get(choice, "")
                self.stdout.write(
                    f"{index} - {choice}" + (f": {explanation}\n" if explanation else "\n")
                )
            self.stdout.write(f"Choose from [{menu}] ({default_index}): ")
            raw = self._read_input()
            if raw is None:
                return default
            self.stdout.write(f"{raw}\n" if raw else "\n")
            if not raw:
                return default
            if raw in choices:
                return raw
            if raw.isdigit() and 1 <= int(raw) <= len(choices):
                return choices[int(raw) - 1]
            self.stdout.write(f"  {raw!r} is not one of {', '.join(choices)}.\n")
        return default

    def menu(self, title: str, options: Sequence[tuple[str, str]], default: str) -> str:
        values = [value for value, _label in options]
        default_index = values.index(default) + 1 if default in values else 1
        menu = "/".join(str(index) for index in range(1, len(options) + 1))

        for _ in range(_MAX_ATTEMPTS):
            self.stdout.write(f"Select {title}\n")
            for index, (_value, label) in enumerate(options, start=1):
                self.stdout.write(f"{index} - {label}\n")
            self.stdout.write(f"Choose from [{menu}] ({default_index}): ")
            raw = self._read_input()
            if raw is None:
                return default
            self.stdout.write(f"{raw}\n" if raw else "\n")
            if not raw:
                return default
            if raw in values:
                return raw
            if raw.isdigit() and 1 <= int(raw) <= len(values):
                return values[int(raw) - 1]
            self.stdout.write(f"  {raw!r} is not one of {', '.join(values)}.\n")
        return default

    def banner(self) -> None:
        """Keep the plain path byte-stable apart from explicitly asked questions."""

    def confirm(self, message: str, *, default: bool = True) -> bool:
        fallback = "y" if default else "n"
        self.stdout.write(f"{message} [{'Y/n' if default else 'y/N'}]: ")
        raw = self._read_input()
        if raw is None:
            return default
        self.stdout.write(f"{raw}\n" if raw else "\n")
        return (raw or fallback).lower() in {"y", "yes"}

    def note(self, message: str) -> None:
        self.stdout.write(f"{message}\n")

    def error(self, message: str) -> None:
        self.stdout.write(f"{message}\n")


class QuestionaryPrompter:
    """The styled arrow-key adapter, imported only for a supported TTY."""

    def __init__(self) -> None:
        self._questionary: ModuleType = import_module("questionary")
        self.last_input_was_explicit = False
        self._style = self._questionary.Style(
            [
                ("qmark", "fg:#5f87ff bold"),
                ("question", "bold"),
                ("answer", "fg:#5f87ff bold"),
                ("pointer", "fg:#5f87ff bold"),
                ("highlighted", "fg:#5f87ff bold"),
                ("selected", "fg:#5f87ff"),
                ("instruction", "fg:#808080"),
            ]
        )

    @staticmethod
    def _label(question: Question) -> str:
        return question.label or question.prompt

    @staticmethod
    def _required(answer: object | None) -> object:
        if answer is None:
            raise PromptAborted("Setup cancelled.")
        return answer

    @staticmethod
    def _validator(question: Question, default: str) -> Callable[[str], bool | str] | None:
        validator = question.validator
        if validator is None:
            return None

        def validate(value: str) -> bool | str:
            if value == default:
                return True
            try:
                validator(value)
            except ValueError as exc:
                return str(exc)
            return True

        return validate

    def _text_prompt(self, kind: str, question: Question, default: str) -> str:
        builder = getattr(self._questionary, kind)
        prompt = builder(
            self._label(question),
            default=default,
            qmark="?",
            style=self._style,
            instruction=question.help or None,
            validate=self._validator(question, default),
        )
        value = str(self._required(prompt.ask()))
        self.last_input_was_explicit = value != default
        return value

    def menu(self, title: str, options: Sequence[tuple[str, str]], default: str) -> str:
        choices = [
            self._questionary.Choice(
                title=label + ("  (recommended)" if value == default else ""),
                value=value,
            )
            for value, label in options
        ]
        prompt = self._questionary.select(
            title,
            choices=choices,
            default=default,
            qmark="?",
            pointer=">",
            style=self._style,
            show_selected=True,
        )
        value = str(self._required(prompt.ask()))
        self.last_input_was_explicit = value != default
        return value

    def confirm(self, message: str, *, default: bool = True) -> bool:
        prompt = self._questionary.confirm(
            message,
            default=default,
            qmark="?",
            style=self._style,
        )
        value = bool(self._required(prompt.ask()))
        self.last_input_was_explicit = value != default
        return value

    def note(self, message: str) -> None:
        self._questionary.print(f"  {message}", style="fg:#808080")

    def error(self, message: str) -> None:
        self._questionary.print(f"  {message}", style="fg:#d70000 bold")

    def banner(self) -> None:
        from sci_rag import __version__

        self._questionary.print(
            f"\n  Sci RAG Kit  v{__version__}",
            style="fg:#5f87ff bold",
        )
        self._questionary.print("\n  Setting up a new scientific knowledge base.\n")

    def text(self, question: Question, default: str) -> str:
        return self._text_prompt("text", question, default)

    def secret(self, question: Question, default: str) -> str:
        return self._text_prompt("password", question, default)

    def choice(self, question: Question, default: str) -> str:
        values = list(question.choices or ())
        width = max((len(value) for value in values), default=0)
        choices = []
        for value in values:
            description = question.choice_help.get(value, "")
            title = value.ljust(width)
            if description:
                title += f"  {description}"
            if value == default:
                title += "  (recommended)"
            choices.append(self._questionary.Choice(title=title, value=value))

        prompt = self._questionary.select(
            self._label(question),
            choices=choices,
            default=default,
            qmark="?",
            pointer=">",
            style=self._style,
            instruction=question.help or None,
            show_selected=True,
        )
        value = str(self._required(prompt.ask()))
        self.last_input_was_explicit = value != default
        return value


def make_prompter(
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    plain: bool = False,
) -> Prompter:
    """Select a prompt adapter once for the whole wizard session."""
    stdin = input_stream if input_stream is not None else sys.stdin
    stdout = output_stream if output_stream is not None else sys.stdout
    term = os.environ.get("TERM", "")
    force_plain = (
        plain
        or input_stream is not None
        or output_stream is not None
        or not (stdin.isatty() and stdout.isatty())
        or "NO_COLOR" in os.environ
        or term in {"", "dumb"}
    )
    if force_plain:
        return PlainPrompter(stdin, stdout)
    try:
        return QuestionaryPrompter()
    except ImportError:
        return PlainPrompter(stdin, stdout)
