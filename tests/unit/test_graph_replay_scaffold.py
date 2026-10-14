"""Generated projects prune graph-replay tests with the demo they exercise."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sci_rag.scaffold import apply
from sci_rag.scaffold.answers import ProjectAnswers
from sci_rag.scaffold.fetch import fetch_template
from sci_rag.scaffold.questions import default_answers

REPO_ROOT = Path(__file__).parents[2]


@pytest.fixture
def replay_template(tmp_path: Path) -> Path:
    """The demo-only surfaces that pruning must remove or retain together."""
    root = tmp_path / "template"
    for relative in ("Makefile", "docs/STYLE.md", "docs/faq.md", "mkdocs.yml"):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, destination)
    _install_graph_replay_surfaces(root)
    return root


def _no_demo_answers() -> ProjectAnswers:
    raw = dict(default_answers())
    raw.update(
        {
            "project_name": "Membrane Materials KB",
            "repo_name": "membrane-materials-kb",
            "include_demo_corpus": "No",
            "initialize_git": "No",
        }
    )
    return ProjectAnswers.from_raw(raw)


def _answers(**overrides: object) -> ProjectAnswers:
    raw = dict(default_answers())
    raw.update({key: str(value) for key, value in overrides.items()})
    return ProjectAnswers.from_raw(raw)


def _install_graph_replay_surfaces(root: Path) -> None:
    """Copy the tracked replay surfaces a generated project will inherit."""
    replay_files = (
        "scripts/graph_replay.py",
        "tests/unit/test_graph_replay_contract.py",
        "tests/integration/test_graph_replay.py",
        "tests/unit/test_graph_replay_makefile.py",
        "tests/unit/test_graph_replay_scaffold.py",
        "docs/adr/0011-committed-benchmark-graph-replay.md",
    )
    for relative in replay_files:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, destination)

    replay_script = root / "scripts" / "graph_replay.py"
    (replay_script.parent / "keep_me.py").write_text("# unrelated helper\n", encoding="utf-8")

    artifact = root / "data" / "demo" / "graph-replay" / "reviewed.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('{"schema_version": 1}\n', encoding="utf-8")

    makefile = root / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    text = text.replace(
        "GRAPH_REPLAY_RECEIPT :=",
        "BENCH_GRAPH_REPLAY := data/demo/graph-replay/reviewed.json\nGRAPH_REPLAY_RECEIPT :=",
        1,
    )
    makefile.write_text(text, encoding="utf-8")


def _graph_replay_references(root: Path) -> list[str]:
    needles = ("graph_replay.py", "graph-replay", "BENCH_GRAPH_REPLAY")
    references: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(needle in text for needle in needles):
            references.append(str(path.relative_to(root)))
    return sorted(references)


def _dangling_replay_test_references(root: Path) -> list[str]:
    """Test modules that would import or copy the removed replay script."""
    replay_script = "scripts/graph_replay.py"
    offenders: list[str] = []
    for path in sorted((root / "tests").rglob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        imports_script = any(
            marker in text
            for marker in (
                "from scripts.graph_replay import",
                "import scripts.graph_replay",
            )
        )
        copies_script = replay_script in text and "shutil.copy" in text
        if imports_script or copies_script:
            offenders.append(str(path.relative_to(root)))
    return offenders


def test_no_demo_generation_prunes_every_test_that_depends_on_graph_replay(
    tmp_path: Path,
) -> None:
    """The complete generated test tree never reaches for a removed asset."""
    generated = tmp_path / "membrane-materials-kb"
    fetch_template(generated, template_path=REPO_ROOT)

    # Local TDD runs before this new module is tracked. Install it at the same
    # path the committed template will carry so this check exercises its own
    # pruning contract both locally and in CI.
    relative_test_path = Path(__file__).relative_to(REPO_ROOT)
    copied_test = generated / relative_test_path
    copied_test.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(__file__, copied_test)

    apply.apply_all(_no_demo_answers(), generated, year=2026, allow_git=False)

    replay_only_tests = (
        "tests/unit/test_graph_replay_contract.py",
        "tests/integration/test_graph_replay.py",
        "tests/unit/test_graph_replay_makefile.py",
        "tests/unit/test_graph_replay_scaffold.py",
    )
    retained = [relative for relative in replay_only_tests if (generated / relative).exists()]
    assert retained == [], f"no-demo project retained replay-only tests: {retained}"
    assert _dangling_replay_test_references(generated) == []


def test_declining_demo_prunes_graph_replay_surfaces(replay_template: Path) -> None:
    """A project without the demo retains no demo-only replay entry point."""
    apply.apply_pruning(_answers(include_demo_corpus="No"), replay_template)

    assert not (replay_template / "data" / "demo" / "graph-replay").exists()
    assert not (replay_template / "scripts" / "graph_replay.py").exists()
    for relative in (
        "tests/unit/test_graph_replay_contract.py",
        "tests/integration/test_graph_replay.py",
        "tests/unit/test_graph_replay_makefile.py",
        "tests/unit/test_graph_replay_scaffold.py",
        "docs/adr/0011-committed-benchmark-graph-replay.md",
    ):
        assert not (replay_template / relative).exists()
    assert (replay_template / "scripts" / "keep_me.py").exists()
    makefile = (replay_template / "Makefile").read_text(encoding="utf-8")
    phony = next(line for line in makefile.splitlines() if line.startswith(".PHONY:"))
    assert "benchmark-refresh-graph:" not in makefile
    assert "benchmark-refresh-graph" not in phony
    faq = (replay_template / "docs" / "faq.md").read_text(encoding="utf-8")
    assert "Why commit model output for the demo benchmark?" not in faq
    for relative in ("docs/STYLE.md", "docs/faq.md", "mkdocs.yml"):
        assert "0011-committed-benchmark-graph-replay.md" not in (
            replay_template / relative
        ).read_text(encoding="utf-8")
    assert _graph_replay_references(replay_template) == []


def test_demo_project_retains_graph_replay_surfaces(replay_template: Path) -> None:
    """Keeping the demo keeps its reviewed replay workflow intact."""
    apply.apply_pruning(_answers(include_demo_corpus="Yes"), replay_template)

    assert (replay_template / "data" / "demo" / "graph-replay" / "reviewed.json").exists()
    assert (replay_template / "scripts" / "graph_replay.py").exists()
    for relative in (
        "tests/unit/test_graph_replay_contract.py",
        "tests/integration/test_graph_replay.py",
        "tests/unit/test_graph_replay_makefile.py",
        "tests/unit/test_graph_replay_scaffold.py",
        "docs/adr/0011-committed-benchmark-graph-replay.md",
    ):
        assert (replay_template / relative).exists()
    makefile = (replay_template / "Makefile").read_text(encoding="utf-8")
    phony = next(line for line in makefile.splitlines() if line.startswith(".PHONY:"))
    assert "benchmark-refresh-graph:" in makefile
    assert "benchmark-refresh-graph" in phony
    assert "BENCH_GRAPH_REPLAY := data/demo/graph-replay/reviewed.json" in makefile
    faq = (replay_template / "docs" / "faq.md").read_text(encoding="utf-8")
    assert "Why commit model output for the demo benchmark?" in faq
    assert "0011-committed-benchmark-graph-replay.md" in faq
