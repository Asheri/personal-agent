"""The personal ontology reports rejected data instead of silently losing it."""

from pathlib import Path

from sci_rag.domain import load_domain
from sci_rag.graph.extractor import ExtractionStats, parse_extraction


def test_unknown_entity_type_has_a_rejection_receipt() -> None:
    domain = load_domain(Path(__file__).resolve().parents[2] / "domain-personal")
    stats = ExtractionStats()
    entities, _ = parse_extraction(
        {"entities": [{"name": "Invented", "type": "NotInOntology"}]},
        domain,
        1,
        stats=stats,
    )
    assert entities == []
    assert stats.entities_dropped == 1


def test_invalid_entity_container_is_rejected_without_crashing() -> None:
    domain = load_domain(Path(__file__).resolve().parents[2] / "domain-personal")
    stats = ExtractionStats()
    assert parse_extraction({"entities": 123}, domain, 1, stats=stats) == ([], [])
    assert stats.entities_dropped == 1


def test_empty_book_title_cannot_become_an_entity():
    domain = load_domain(Path(__file__).resolve().parents[2] / "domain-personal")
    stats = ExtractionStats()
    assert parse_extraction(
        {"entities": [{"name": "《》", "type": "Document"}]}, domain, 1, stats=stats
    ) == ([], [])
    assert stats.entities_dropped == 1


def test_personal_names_and_endpoint_types_are_enforced():
    domain = load_domain(Path(__file__).resolve().parents[2] / "domain-personal")
    stats = ExtractionStats()
    entities, edges = parse_extraction(
        {
            "entities": [
                {"name": "远山项目", "type": "Project", "passages": [1]},
                {"name": "激光定位技术", "type": "Technology", "passages": [1]},
                {"name": "生物技术", "type": "Technology", "passages": [1]},
                {"name": "林舟", "type": "Person", "passages": [1]},
                {"name": "评审报告", "type": "Document", "passages": [1]},
                {"name": "本文件", "type": "Document", "passages": [1]},
            ],
            "relationships": [
                {"source": "远山项目", "target": "激光定位技术", "type": "USES", "passage": 1},
                {"source": "林舟", "target": "评审报告", "type": "AUTHORED_BY", "passage": 1},
                {"source": "评审报告", "target": "林舟", "type": "AUTHORED_BY", "passage": 1},
            ],
        },
        domain,
        1,
        stats=stats,
    )
    assert {e.name for e in entities} == {"远山", "激光定位", "生物技术", "林舟", "评审报告"}
    assert next(e for e in entities if e.name == "远山").aliases == ["远山项目"]
    assert {(e.source, e.relation_type, e.target) for e in edges} == {
        ("远山", "USES", "激光定位"),
        ("评审报告", "AUTHORED_BY", "林舟"),
    }
    assert stats.entities_dropped == 1 and stats.relationships_dropped == 1
