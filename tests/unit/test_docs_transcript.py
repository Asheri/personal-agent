"""The homepage session has to be what the wizard actually asks.

The example on `docs/index.md` is the first thing a new user reads, and it is
the one place a stale document is invisible: a question added to
`questions.py` would simply not appear, and nothing would complain. So the page
is generated from the question list, and these tests assert the committed page
and cast still match a fresh render.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from runpy import run_path

REPO_ROOT = Path(__file__).parents[2]
_MODULE = run_path(str(REPO_ROOT / "scripts" / "render_cast.py"))


@cache
def _quick_transcript() -> str:
    return _MODULE["render_transcript"](quick=True)


@cache
def _advanced_transcript() -> str:
    return _MODULE["render_transcript"](quick=False)


def test_the_committed_page_matches_a_fresh_render() -> None:
    index = (REPO_ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    assert index == _MODULE["render_index"](index, _quick_transcript(), _advanced_transcript()), (
        "stale page; run make cast"
    )


def test_the_committed_cast_matches_a_fresh_render() -> None:
    name = "sci-rag-new.cast"
    cast = (REPO_ROOT / "docs" / "assets" / "casts" / name).read_text(encoding="utf-8")
    assert cast == _MODULE["render_cast"](_quick_transcript()), f"stale {name}; run make cast"


def test_the_advanced_session_is_static_only() -> None:
    index = (REPO_ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    advanced = index.partition("<summary>Show the Advanced setup</summary>")[2]

    assert 'class="highlight srag-term"' in advanced
    assert "sci-rag-new-advanced.cast" not in advanced
    assert "data-cast=" not in advanced


def test_every_question_appears_in_the_transcript() -> None:
    """The guard that catches a question added without updating the homepage."""
    from sci_rag.scaffold.questions import QUESTIONS, default_answers

    transcript = _advanced_transcript()
    asked = set(default_answers()) | {"openalex_topic", "max_results", "dependency_file"}
    for question in QUESTIONS:
        if question.name in asked:
            assert question.name in transcript, question.name


def test_the_transcript_asks_each_question_in_words() -> None:
    """A reader of the homepage sees the question, not only the field name."""
    from sci_rag.scaffold.questions import QUESTIONS

    transcript = _quick_transcript()
    labels = {q.name: q.label for q in QUESTIONS if q.label}
    for name in ("project_name", "credentials", "corpus_source"):
        assert labels[name] in transcript, name

    parsed = _MODULE["_parse_transcript"](transcript)
    kinds = [kind for _line, kind, _parts in parsed]
    assert "label" in kinds
    label_index = kinds.index("label")
    assert kinds[label_index + 1] in {"prompt", "select"}


def test_the_transcript_shows_the_result_not_just_the_questions() -> None:
    transcript = _quick_transcript()
    assert "Writing membrane-materials-kb/" in transcript
    assert "domain/domain.yaml" in transcript
    assert "LICENSE" in transcript
    assert "Done. Membrane Materials KB is set up." in transcript


def test_the_transcript_is_rendered_for_the_manager_it_selected() -> None:
    """The scripted session picks pixi, so no uv command may appear in it."""
    transcript = _advanced_transcript()
    assert "pixi install" in transcript
    assert "pixi run sci-rag doctor" in transcript
    assert "uv run" not in transcript


def test_the_transcript_has_no_trailing_whitespace() -> None:
    """The pre-commit hook strips it, which would make --check fail forever."""
    for transcript in (_quick_transcript(), _advanced_transcript()):
        for line in transcript.splitlines():
            assert line == line.rstrip(), repr(line)


def test_the_transcripts_never_expose_the_scripted_key() -> None:
    assert "cast-example-key" not in _quick_transcript()
    assert "cast-example-key" not in _advanced_transcript()


def test_the_transcripts_label_stubbed_model_work() -> None:
    for transcript in (_quick_transcript(), _advanced_transcript()):
        assert "check simulated for this recording; no model request sent" in transcript
        assert "answered in 90 ms" not in transcript


def test_the_transcripts_describe_ai_studio_without_cost_or_project_overclaims() -> None:
    for transcript in (_quick_transcript(), _advanced_transcript()):
        assert "Shortest local setup; no manual Cloud setup" in transcript
        assert "One free key, no cloud project" not in transcript


def test_quick_transcript_asks_the_six_base_questions_and_gated_key() -> None:
    from sci_rag.scaffold.questions import QUESTIONS

    transcript = _quick_transcript()
    expected = {
        "project_name",
        "description",
        "contact_email",
        "environment_manager",
        "credentials",
        "deepseek_api_key",
        "corpus_source",
    }
    for question in QUESTIONS:
        if question.name in expected:
            assert question.prompt in transcript
        else:
            assert f"Select {question.prompt}\n" not in transcript
            assert f"{question.prompt} (" not in transcript


def test_the_cast_is_valid_asciicast_v2() -> None:
    for transcript in (_quick_transcript(), _advanced_transcript()):
        lines = _MODULE["render_cast"](transcript).splitlines()
        header = json.loads(lines[0])
        assert header["version"] == 2
        assert header["width"] >= 80

        previous = -1.0
        for line in lines[1:]:
            timestamp, code, _ = json.loads(line)
            assert code == "o"
            assert timestamp > previous, "event timestamps must increase"
            previous = timestamp


def _plain_cast_text(payload: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", payload)


def test_the_cast_uses_bold_and_faint_ansi() -> None:
    """The player should match the static transcript: answers bold, prompts faint."""
    for transcript in (_quick_transcript(), _advanced_transcript()):
        cast = _MODULE["render_cast"](transcript)
        assert "\\u001b[1m" in cast
        assert "\\u001b[2m" in cast


def test_the_cast_pauses_after_commands_and_choices() -> None:
    """A choice has to sit on screen long enough to read before the next prompt."""
    events = [
        json.loads(line) for line in _MODULE["render_cast"](_advanced_transcript()).splitlines()[1:]
    ]
    plains = [_plain_cast_text(event[2]) for event in events]

    cmd = next(i for i, text in enumerate(plains) if text.startswith("$ sci-rag new"))
    assert events[cmd + 1][0] - events[cmd][0] >= 1.0

    choose = next(i for i, text in enumerate(plains) if "Choose from [1/2/3/4] (1): 2" in text)
    assert events[choose + 1][0] - events[choose][0] >= 1.2

    menu = next(i for i, text in enumerate(plains) if text.startswith("1 - uv"))
    assert events[menu + 1][0] - events[menu][0] < 0.3


def test_freeform_answers_are_typed_character_by_character() -> None:
    """The prompt lands first; the answer is keyed in so the cursor can blink."""
    events = [
        json.loads(line) for line in _MODULE["render_cast"](_quick_transcript()).splitlines()[1:]
    ]
    plains = [_plain_cast_text(event[2]) for event in events]

    prompt = next(i for i, text in enumerate(plains) if "project_name" in text)
    assert "Membrane" not in plains[prompt]
    assert plains[prompt].endswith(" ")

    typed = []
    for text in plains[prompt + 1 :]:
        if text == "\r\n":
            break
        if text:
            typed.append(text)
    assert typed == list("Membrane Materials KB")
    assert events[prompt + 1][0] - events[prompt][0] >= 0.8
    keystrokes = [
        events[prompt + i + 2][0] - events[prompt + i + 1][0] for i in range(len(typed) - 1)
    ]
    assert min(keystrokes) >= 0.04
    assert max(keystrokes) <= 0.2


def test_the_html_transcript_keeps_the_plain_text() -> None:
    """Styling wraps lines; copying the block must still yield the session."""
    import html as html_module
    import re

    for transcript in (_quick_transcript(), _advanced_transcript()):
        markup = _MODULE["format_transcript_html"](transcript)
        inner = re.search(r"<code>(.*)</code>", markup, re.DOTALL)
        assert inner is not None
        plain = html_module.unescape(re.sub(r"<[^>]+>", "", inner.group(1)))
        assert plain == transcript


def test_the_html_transcript_marks_commands_questions_and_answers() -> None:
    markup = _MODULE["format_transcript_html"](_advanced_transcript())
    assert 'class="highlight srag-term"' in markup
    assert "srag-term__cmd" in markup
    assert "srag-term__key" in markup
    assert "srag-term__value" in markup
    assert "srag-term__heading" in markup
    assert "srag-term__break" in markup
    assert "Membrane Materials KB" in markup
    assert "srag-term__line--next" in markup
    assert "pixi install" in markup


def test_an_empty_secret_default_keeps_its_prompt_roles() -> None:
    kind, parts = _MODULE["_parse_line"]("google_api_key ():", in_next=False)

    assert kind == "prompt"
    assert parts == [
        ("key", "google_api_key"),
        ("default", " ():"),
        ("value", ""),
    ]


def test_the_player_assets_are_vendored_not_fetched() -> None:
    """A CDN reference would break the hermetic build and the offline link check."""
    vendor = REPO_ROOT / "docs" / "assets" / "vendor" / "asciinema-player"
    assert (vendor / "asciinema-player.min.js").exists()
    assert (vendor / "asciinema-player.css").exists()
    assert (vendor / "LICENSE").exists()

    mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "assets/vendor/asciinema-player/asciinema-player.min.js" in mkdocs
    assert "assets/vendor/asciinema-player/asciinema-player.css" in mkdocs
    assert "cdn.jsdelivr.net" not in (REPO_ROOT / "docs" / "javascripts" / "cast.js").read_text(
        encoding="utf-8"
    )


def test_the_player_mounts_every_cast_on_the_page() -> None:
    script = (REPO_ROOT / "docs" / "javascripts" / "cast.js").read_text(encoding="utf-8")

    assert 'querySelectorAll(".srag-cast")' in script
    assert 'getElementById("srag-cast")' not in script


def test_the_player_autoplays_at_real_time() -> None:
    script = (REPO_ROOT / "docs" / "javascripts" / "cast.js").read_text(encoding="utf-8")
    index = (REPO_ROOT / "docs" / "index.md").read_text(encoding="utf-8")

    assert 'data-autoplay="true"' in index
    assert 'el.dataset.autoplay === "true" && !reduceMotion' in script
    assert "autoPlay: autoPlay" in script
    assert "loop: autoPlay" in script
    assert "controls: !autoPlay" in script
    assert 'classList.toggle("srag-cast--autoplaying", autoPlay)' in script
    assert "fit: false" in script
    assert 'terminalFontSize: "0.88em"' in script
    assert "speed: 1" in script
    assert "idleTimeLimit: 4" in script
