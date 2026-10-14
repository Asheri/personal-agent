"""Which questions a demo target scores against, and whose they are.

`domain/eval_seed_questions.jsonl` is the reader's ground truth. The wizard
resets it to a guided blank for every corpus source except `demo_only`,
because scoring somebody's own corpus against the synthetic one's answers is
worse than not scoring it. That reset left the retained `demo`, `demo-cloud`,
and `benchmark` targets reading a file with no questions in it, so `make demo`
ingested and retrieved and then exited 2 on `No questions found`.

`local_files` is the wizard's default corpus source and the demo corpus
defaults to Yes, so that is the project a reader gets by pressing Enter
through Quick setup and then following the quickstart.

The rule here is one sentence: the demo corpus carries its own ground truth,
and the demo targets name it. `domain/eval_seed_questions.jsonl` stays the
reader's, and a bare `sci-rag eval retrieval` still refuses when it is blank.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sci_rag.scaffold import apply
from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.questions import default_answers

REPO_ROOT = Path(__file__).parents[2]
DEMO_QUESTIONS = "data/demo/eval_seed_questions.jsonl"

_NEEDS_MAKE = pytest.mark.skipif(shutil.which("make") is None, reason="needs make")


@pytest.fixture
def template(tmp_path: Path) -> Path:
    root = tmp_path / "template"
    root.mkdir(parents=True)
    for name in ("pyproject.toml", "Makefile", ".env.example", "README.md", "uv.lock"):
        shutil.copy(REPO_ROOT / name, root / name)
    shutil.copytree(REPO_ROOT / "domain", root / "domain")
    shutil.copytree(REPO_ROOT / "data" / "demo", root / "data" / "demo")
    (root / "infra" / "terraform").mkdir(parents=True)
    (root / "infra" / "terraform" / "main.tf").write_text("# terraform\n", encoding="utf-8")
    (root / "examples").mkdir()
    (root / "examples" / "library_quickstart.py").write_text("# example\n", encoding="utf-8")
    return root


def _answers(**overrides: object) -> ProjectAnswers:
    raw = dict(default_answers())
    raw.update({k: str(v) for k, v in overrides.items()})
    return ProjectAnswers.from_raw(raw)


def _questions(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("{")]


def _recipe(root: Path, target: str) -> str:
    result = subprocess.run(
        ["make", "-n", target],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


@pytest.mark.parametrize("corpus_source", ("local_files", "doi_list", "openalex_topic"))
def test_the_demo_corpus_carries_its_questions_when_it_is_not_the_corpus(
    template: Path, corpus_source: str
) -> None:
    """The reader's file stays blank; the demo's ground truth goes with the demo."""
    apply.apply_seed_questions(_answers(corpus_source=corpus_source), template)

    assert _questions(template / "domain" / "eval_seed_questions.jsonl") == []
    assert _questions(template / DEMO_QUESTIONS), "the demo has to keep its own answers"


def test_a_demo_only_project_holds_the_same_questions_in_both_places(template: Path) -> None:
    """There the demo is the corpus, so the reader's ground truth is the demo's."""
    apply.apply_seed_questions(_answers(corpus_source="demo_only"), template)

    own = (template / "domain" / "eval_seed_questions.jsonl").read_text(encoding="utf-8")
    demo = (template / DEMO_QUESTIONS).read_text(encoding="utf-8")

    assert _questions(template / DEMO_QUESTIONS)
    assert own == demo


def test_declining_the_demo_corpus_writes_no_demo_questions(template: Path) -> None:
    apply.apply_seed_questions(_answers(include_demo_corpus="No"), template)

    assert not (template / DEMO_QUESTIONS).exists()


@_NEEDS_MAKE
@pytest.mark.parametrize("corpus_source", ("local_files", "demo_only"))
def test_the_demo_targets_score_the_demo_and_the_readers_do_not(
    template: Path, corpus_source: str
) -> None:
    """One rule, both directions.

    A demo target names the demo's questions whatever the corpus source is.
    `eval` and `eval-ablation` are the reader's own and must not, or a project
    with its own corpus would silently score it against synthetic answers.
    """
    answers = _answers(corpus_source=corpus_source)
    apply.apply_seed_questions(answers, template)
    apply.apply_makefile(answers, template)

    for target in ("demo", "demo-cloud", "benchmark"):
        assert DEMO_QUESTIONS in _recipe(template, target), target

    for target in ("eval", "eval-ablation"):
        assert DEMO_QUESTIONS not in _recipe(template, target), target
