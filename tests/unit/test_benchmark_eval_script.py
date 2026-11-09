"""The MultiHop-RAG adapter's pure parts: loading, sampling, pairing, report.

The network-facing half of `scripts/run_benchmark_eval.py` needs a database and
a model key. Everything here decides what a result means, so it is checked
without either: the corpus writer, the stratified sample, the question mapping,
and the paired test.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_benchmark_eval.py"


def _module():
    spec = importlib.util.spec_from_file_location("benchmark_eval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` looks its own module up in `sys.modules`; loading a file
    # without registering it first fails there before any test runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORPUS = [
    {
        "title": "Alpha Report",
        "body": "Alpha body about rice.",
        "source": "news-a",
        "published_at": "2023-05-01",
    },
    {
        "title": "Beta Report",
        "body": "Beta body about straw.",
        "source": "news-b",
        "published_at": "2024-06-02",
    },
    {"title": "Empty", "body": "   ", "source": "news-c", "published_at": ""},
]

QUERIES = [
    {
        "query": "Who wrote Alpha?",
        "answer": "Someone",
        "question_type": "inference",
        "evidence_list": [{"fact": "Alpha body about rice.", "source": "Alpha Report"}],
    },
    {
        "query": "Compare Alpha and Beta.",
        "answer": "They differ",
        "question_type": "comparison",
        "evidence_list": [
            {"fact": "Alpha body about rice.", "source": "Alpha Report"},
            {"fact": "Beta body about straw.", "source": "Beta Report"},
        ],
    },
    {
        "query": "When did Gamma happen?",
        "answer": "Never",
        "question_type": "temporal",
        "evidence_list": [{"fact": "Beta body about straw.", "source": "Beta Report"}],
    },
    {
        "query": "What is the budget of Delta?",
        "answer": "Not in the corpus",
        "question_type": "null",
        "evidence_list": [],
    },
]


@pytest.fixture()
def dataset(tmp_path: Path) -> Path:
    folder = tmp_path / "MultiHopRAG"
    folder.mkdir()
    (folder / "corpus.json").write_text(json.dumps(CORPUS), encoding="utf-8")
    (folder / "MultiHopRAG.json").write_text(json.dumps(QUERIES), encoding="utf-8")
    return folder


def test_loading_drops_empty_bodies_and_keeps_order(dataset: Path) -> None:
    module = _module()

    articles = module.load_corpus(dataset / "corpus.json")

    assert [article.title for article in articles] == ["Alpha Report", "Beta Report"]


def test_the_writer_emits_one_file_per_article_and_a_manifest(
    dataset: Path, tmp_path: Path
) -> None:
    module = _module()
    articles = module.load_corpus(dataset / "corpus.json")

    manifest = module.write_corpus(articles, tmp_path / "corpus")

    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["license_class"] == module.LICENSE == "open_commercial"
    assert rows[0]["year"] == 2023 and rows[1]["year"] == 2024
    for row in rows:
        written = tmp_path / "corpus" / row["path"]
        assert written.is_file()
        assert written.read_text(encoding="utf-8").startswith("# ")


def test_the_same_title_twice_is_written_once(tmp_path: Path) -> None:
    module = _module()
    duplicate = module.Article(title="Same", body="one")
    again = module.Article(title="Same", body="two")

    manifest = module.write_corpus([duplicate, again], tmp_path / "corpus")

    assert len(manifest.read_text(encoding="utf-8").splitlines()) == 1


def test_sampling_keeps_the_question_type_mix() -> None:
    module = _module()
    rows = [
        module.Query(query=f"q{index}", answer="a", question_type=kind, evidence=[])
        for index, kind in enumerate(
            ["inference"] * 8 + ["comparison"] * 8 + ["temporal"] * 3 + ["null"] * 1
        )
    ]

    sample = module.stratified_sample(rows, 10, seed=0)

    assert len(sample) == 10
    kinds = {row.question_type for row in sample}
    assert {"inference", "comparison", "temporal", "null"} <= kinds


def test_sampling_everything_returns_everything() -> None:
    module = _module()
    rows = [
        module.Query(query=f"q{index}", answer="a", question_type="inference", evidence=[])
        for index in range(5)
    ]

    assert module.stratified_sample(rows, 0) == rows
    assert module.stratified_sample(rows, 99) == rows


def test_a_null_question_becomes_an_unanswerable_seed(dataset: Path) -> None:
    module = _module()
    queries = module.load_queries(dataset / "MultiHopRAG.json")

    seeds = module.to_seed_questions(queries)

    null_seed = next(seed for seed in seeds if seed.tags[0] == "null")
    assert "unanswerable" in null_seed.tags
    assert not null_seed.answerable
    comparison = next(seed for seed in seeds if seed.tags[0] == "comparison")
    assert comparison.reference_titles == ["Alpha Report", "Beta Report"]
    assert comparison.evidence_phrases[0] == "Alpha body about rice."


def test_mcnemar_counts_discordant_pairs_only() -> None:
    module = _module()

    result = module.mcnemar([True, True, False, False, True], [True, False, True, False, True])

    assert result["a_only"] == 1
    assert result["b_only"] == 1
    assert result["n"] == 5
    assert result["p_value"] == pytest.approx(1.0)


def test_mcnemar_separates_a_clean_sweep() -> None:
    module = _module()

    result = module.mcnemar([False] * 10, [True] * 10)

    assert result["b_only"] == 10
    assert result["p_value"] < 0.01


def test_mcnemar_refuses_unpaired_input() -> None:
    module = _module()

    with pytest.raises(ValueError):
        module.mcnemar([True], [True, False])


def test_the_report_names_every_condition_and_the_pairs(dataset: Path, tmp_path: Path) -> None:
    module = _module()
    records = [
        module.ConditionRecord("q1", "inference", "plain", correctness=0, grounding=1),
        module.ConditionRecord("q1", "inference", "rag", correctness=2, grounding=2),
        module.ConditionRecord("q1", "inference", "kg", correctness=2, grounding=2),
        module.ConditionRecord("q2", "null", "plain", correctness=2, grounding=2),
        module.ConditionRecord("q2", "null", "rag", correctness=0, grounding=1),
        module.ConditionRecord("q2", "null", "kg", error="answer: boom"),
    ]

    summary = module.summarize(records)
    pairs = module.comparisons(records)
    text = module.render_markdown(
        summary,
        pairs,
        {
            "questions": 2,
            "dataset_questions": 4,
            "seed": 0,
            "limit": 6,
            "answer_model": "stub:answer",
            "judge_model": "stub:judge",
        },
    )

    assert summary["rag"]["answered"] == 2 and summary["rag"]["correct"] == 1
    assert summary["kg"]["errors"] == 1
    assert summary["plain"]["by_type"]["null"]["accuracy"] == 1.0
    assert "plain_vs_rag" in pairs
    assert "| Condition | Answered | Accuracy | Grounded | Errors |" in text
    assert "exact McNemar" in text
