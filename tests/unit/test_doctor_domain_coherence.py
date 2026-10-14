"""What `sci-rag doctor` can tell you about a domain profile without a database.

The doctor already proves the profile loads and the prompts exist. Loading is
not coherence: an ontology of one type loads, a seed set with no honesty probe
loads, a manifest pointing at deleted files loads. Each of those is a silent
way for an evaluation to stop measuring what its owner thinks it measures, so
each gets a row.
"""

from __future__ import annotations

from pathlib import Path

from sci_rag.cli.doctor import (
    _drafted_ground_truth_check,
    _manifest_check,
    _ontology_coherence_check,
    _seed_coherence_check,
)
from sci_rag.domain import DomainConfig
from sci_rag.evals.seeds import SeedQuestion

REPO_ROOT = Path(__file__).parents[2]


def _config(**overrides: object) -> DomainConfig:
    base: dict[str, object] = {
        "name": "Test KB",
        "entity_types": [
            {"name": "Feedstock"},
            {"name": "Product"},
            {"name": "Region"},
        ],
        "relation_types": [{"name": "CONVERTED_BY"}],
        "query_classes": [{"name": "availability"}],
    }
    return DomainConfig.model_validate(base | overrides)


def test_the_shipped_ontology_is_coherent() -> None:
    from sci_rag.domain import load_domain

    check = _ontology_coherence_check(load_domain(REPO_ROOT / "domain").config)

    assert check.status == "ok"


def test_a_thin_ontology_warns() -> None:
    check = _ontology_coherence_check(_config(entity_types=[{"name": "Thing"}]))

    assert check.status == "warn"
    assert "entity type" in check.detail


def test_duplicate_type_names_fail() -> None:
    check = _ontology_coherence_check(
        _config(entity_types=[{"name": "Feedstock"}, {"name": "Feedstock"}, {"name": "Product"}])
    )

    assert check.status == "fail"
    assert "Feedstock" in check.detail


def test_a_relation_that_is_not_screaming_snake_warns() -> None:
    check = _ontology_coherence_check(_config(relation_types=[{"name": "convertedBy"}]))

    assert check.status == "warn"
    assert "convertedBy" in check.detail


def test_a_seed_set_with_a_probe_is_coherent() -> None:
    questions = [
        SeedQuestion(id="a", question="q", reference_titles=["Doc"], evidence_phrases=["x"]),
        SeedQuestion(id="probe", question="q", tags=["unanswerable"]),
    ]

    check = _seed_coherence_check(questions)

    assert check.status == "ok"


def test_a_seed_set_with_no_honesty_probe_warns() -> None:
    check = _seed_coherence_check([SeedQuestion(id="a", question="q", evidence_phrases=["x"])])

    assert check.status == "warn"
    assert "unanswerable" in check.detail


def test_an_answerable_question_with_no_evidence_warns() -> None:
    questions = [
        SeedQuestion(id="bare", question="q"),
        SeedQuestion(id="probe", question="q", tags=["unanswerable"]),
    ]

    check = _seed_coherence_check(questions)

    assert check.status == "warn"
    assert "bare" in check.detail


def test_drafted_questions_are_counted() -> None:
    questions = [
        SeedQuestion(id="a", question="q", tags=["drafted"]),
        SeedQuestion(id="b", question="q"),
    ]

    check = _drafted_ground_truth_check(questions)

    assert check.status == "warn"
    assert "1 of 2" in check.detail
    assert "drafted" in check.fix


def test_a_fully_reviewed_seed_set_passes() -> None:
    check = _drafted_ground_truth_check([SeedQuestion(id="a", question="q")])

    assert check.status == "ok"


def test_a_manifest_whose_paths_are_gone_fails(tmp_path: Path) -> None:
    manifest = tmp_path / "corpus.jsonl"
    manifest.write_text(
        '{"path": "raw/missing.pdf", "license_class": "public"}\n', encoding="utf-8"
    )

    check = _manifest_check(manifest)

    assert check.status == "fail"
    assert "missing.pdf" in check.detail


def test_a_manifest_of_unknown_rights_warns(tmp_path: Path) -> None:
    document = tmp_path / "present.md"
    document.write_text("# Present\n", encoding="utf-8")
    manifest = tmp_path / "corpus.jsonl"
    manifest.write_text('{"path": "present.md"}\n', encoding="utf-8")

    check = _manifest_check(manifest)

    assert check.status == "warn"
    assert "1" in check.detail
    assert "rights" in check.detail.lower() or "unknown" in check.detail.lower()
    assert document.exists()


def test_no_manifest_is_not_a_finding(tmp_path: Path) -> None:
    assert _manifest_check(tmp_path / "corpus.jsonl") is None
