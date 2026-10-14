"""What a published benchmark number has to carry with it.

A clean reproduction of `make benchmark` from the committed commit produced a
materially different page: same five documents and 34 chunks, but 93 entities
against the committed 83, 106 relationships against 79, 12 communities against
7, and mean correctness 1.9 against 1.3. The route completed and exited 0, and
the page was rewritten in place, so the only visible evidence that anything had
moved was the diff nobody was asked to read.

Two separate problems live in that. The first is that the report did not record
enough to tell expected model variance apart from a changed input: the
retrieval report named no model at all, and the renderer printed whichever
model its own environment happened to have, not the one that produced the
numbers. The second is that a re-render silently replaced published values.

These guards cover the receipt and the refusals. The comparison itself is in
`test_benchmark_comparison.py`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from runpy import run_path
from typing import Any

import pytest

from sci_rag.evals.report import PROVENANCE_FIELDS, provenance_block, retrieval_payload

# The renderers are scripts rather than package modules, so they are loaded
# the way `test_doc_renderers.py` loads them.
_MODULE: dict | None = None


def _renderer() -> dict:  # type: ignore[type-arg]
    global _MODULE
    if _MODULE is None:
        _MODULE = run_path("scripts/render_benchmarks.py")
    return _MODULE


ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIGEST = "b" * 64
GRAPH_DIGEST = "d" * 64


def _artifact() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "extractor_contract_version": 1,
        "created_at": "2026-08-30T00:00:00+00:00",
        "source_commit": "abc1234",
        "corpus_digest": CORPUS_DIGEST,
        "extraction_model": "google:gemini-2.5-flash",
        "domain_digest": "0" * 64,
        "batch_size": 5,
        "generation_parameters": {
            "temperature": 0.0,
            "json_mode": True,
            "max_tokens": 8192,
        },
        "calls": [
            {
                "order": order,
                "input_digest": f"{order:064x}",
                "raw_completion": "{}",
            }
            for order in range(7)
        ],
        "successful_batches": 7,
        "split_batches": 0,
        "failed_batches": 0,
        "entity_count": 76,
        "relationship_count": 72,
        "graph_digest": GRAPH_DIGEST,
    }


def _artifact_sha256(artifact: object) -> str:
    canonical = json.dumps(
        artifact, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _graph_replay(**overrides: Any) -> dict[str, Any]:
    artifact_sha256 = _artifact_sha256(_artifact())
    receipt: dict[str, Any] = {
        "mode": "require",
        "artifact_path": f"data/demo/graph-replay/{artifact_sha256}.json",
        "artifact_sha256": artifact_sha256,
        "extraction_model": "google:gemini-2.5-flash",
        "domain_digest": "0" * 64,
        "corpus_digest": CORPUS_DIGEST,
        "snapshot": "benchmark-20260830-000000",
        "counts": {"entities": 76, "relationships": 72},
        "replayed_call_count": 7,
        "extracted_call_count": 0,
        "split_count": 0,
        "graph_digest": GRAPH_DIGEST,
    }
    receipt.update(overrides)
    return receipt


def _snapshot(**overrides: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "name": "benchmark-20260830-000000",
        "created_at": "2026-08-30T00:00:00+00:00",
        "git_commit": "abc1234",
        "corpus_digest": CORPUS_DIGEST,
        "counts": {
            "documents": 5,
            "chunks": 34,
            "entities": 76,
            "relationships": 72,
            "communities": 0,
        },
        "embedding_versions": ["local-hash-v1@64"],
        "documents": [
            {
                "id": f"document-{index}",
                "title": f"Document {index}",
                "content_hash": f"{index:064x}",
            }
            for index in range(5)
        ],
    }
    snapshot.update(overrides)
    return snapshot


def _evidence_paths(
    tmp_path: Path,
    *,
    receipt_overrides: dict[str, Any] | None = None,
    snapshot_overrides: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    receipt_path = tmp_path / "graph-receipt.json"
    receipt_path.write_text(
        json.dumps(_graph_replay(**(receipt_overrides or {}))), encoding="utf-8"
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot(**(snapshot_overrides or {}))), encoding="utf-8")
    artifact_path = tmp_path / _graph_replay()["artifact_path"]
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(_artifact(), indent=2), encoding="utf-8")
    return receipt_path, snapshot_path


def test_a_receipt_names_every_input_that_can_move_a_number() -> None:
    """Counts are outcomes. These are the inputs that produce them."""
    assert set(PROVENANCE_FIELDS) == {
        "embedding",
        "models",
        "domain_digest",
        "decoding",
    }


def test_provenance_records_the_effective_models_and_not_the_defaults() -> None:
    from sci_rag.config import Settings

    settings = Settings(
        _env_file=None,
        llm_provider="google",
        llm_model="gemini-2.5-flash",
        extraction_model="anthropic:claude-haiku-4-5",
        judge_model="openai-compatible:some/judge",
        embedding_model="gemini-embedding-001",
        embedding_dim=1536,
    )

    block = provenance_block(settings, domain_dir=ROOT / "domain")

    assert block["models"]["answer"] == "google:gemini-2.5-flash"
    assert block["models"]["extraction"] == "anthropic:claude-haiku-4-5"
    assert block["models"]["judge"] == "openai-compatible:some/judge"
    assert block["embedding"] == "gemini-embedding-001@1536"
    # Decoding is what makes a run repeatable at all, so it is on the receipt.
    assert "temperature" in block["decoding"]


def test_the_domain_digest_moves_when_the_ontology_or_a_prompt_moves(tmp_path: Path) -> None:
    """A prompt edit changes every extracted entity and no count records it."""
    from sci_rag.config import Settings

    domain = tmp_path / "domain"
    (domain / "prompts").mkdir(parents=True)
    (domain / "domain.yaml").write_text("name: a\n", encoding="utf-8")
    (domain / "prompts" / "entity_extraction.md").write_text("find things\n", encoding="utf-8")

    settings = Settings(_env_file=None)
    before = provenance_block(settings, domain_dir=domain)["domain_digest"]

    (domain / "prompts" / "entity_extraction.md").write_text(
        "find OTHER things\n", encoding="utf-8"
    )
    after = provenance_block(settings, domain_dir=domain)["domain_digest"]

    assert before != after


def test_a_retrieval_report_carries_the_receipt() -> None:
    """The retrieval ablation runs graph and HyDE, so it depends on a model."""
    payload = retrieval_payload([], {"documents": 5}, provenance={"models": {}})

    assert "provenance" in payload


# --- the renderer refuses an unusable receipt -------------------------------


def _report(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "retrieval",
        "git_commit": "abc1234",
        "snapshot": "benchmark-20260830-000000",
        "corpus": {
            "documents": 5,
            "chunks": 34,
            "entities": 76,
            "relationships": 72,
            "communities": 0,
            "embedding_versions": ["local-hash-v1@64"],
        },
        "provenance": {
            "embedding": "local-hash-v1@64",
            "models": {
                "answer": "google:gemini-2.5-flash",
                "extraction": "google:gemini-2.5-flash",
            },
            "domain_digest": "0" * 64,
            "decoding": {"temperature": 0.0},
        },
        "configs": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("field", ["provenance", "git_commit", "snapshot"])
def test_the_renderer_refuses_a_report_missing_a_required_field(tmp_path: Path, field: str) -> None:
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]

    report = _report()
    report.pop(field)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(tmp_path)

    with pytest.raises(ProvenanceError) as caught:
        render_benchmarks(
            path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )

    assert field in str(caught.value)


def test_the_renderer_refuses_a_missing_graph_receipt(tmp_path: Path) -> None:
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    _, snapshot_path = _evidence_paths(tmp_path)

    with pytest.raises(ProvenanceError, match="graph receipt"):
        render_benchmarks(
            path,
            None,
            graph_receipt=None,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


@pytest.mark.parametrize("artifact_state", ["missing", "substituted"])
def test_the_renderer_verifies_the_named_artifact_content(
    tmp_path: Path, artifact_state: str
) -> None:
    """A receipt string cannot stand in for the committed replay evidence."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(tmp_path)
    artifact_path = tmp_path / _graph_replay()["artifact_path"]

    if artifact_state == "missing":
        artifact_path.unlink()
    else:
        substitute = _artifact()
        substitute["entity_count"] = 77
        artifact_path.write_text(json.dumps(substitute), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="artifact"):
        render_benchmarks(
            report_path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("artifact_field", "bad_value", "expected_error"),
    [
        ("extraction_model", "google:forged-model", "extraction_model"),
        ("domain_digest", "1" * 64, "domain_digest"),
        ("corpus_digest", "2" * 64, "corpus_digest"),
        ("entity_count", 77, "entity_count"),
        ("relationship_count", 73, "relationship_count"),
        ("graph_digest", "3" * 64, "graph_digest"),
        (
            "generation_parameters",
            {"temperature": 0.4, "json_mode": True, "max_tokens": 8192},
            "generation_parameters",
        ),
        (
            "generation_parameters",
            {
                "temperature": 0.0,
                "json_mode": True,
                "max_tokens": 8192,
                "seed": 7,
            },
            "generation_parameters",
        ),
        ("split_batches", 1, "split_count"),
        ("failed_batches", 1, "failed_batches"),
        ("calls", [], "replayed_call_count"),
    ],
)
def test_the_renderer_binds_receipt_claims_to_the_hashed_artifact(
    tmp_path: Path,
    artifact_field: str,
    bad_value: object,
    expected_error: str,
) -> None:
    """A forged receipt and matching artifact hash cannot publish false replay claims."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")

    artifact = _artifact()
    artifact[artifact_field] = bad_value
    artifact_sha256 = _artifact_sha256(artifact)
    receipt = _graph_replay(
        artifact_path=f"data/demo/graph-replay/{artifact_sha256}.json",
        artifact_sha256=artifact_sha256,
    )
    receipt_path = tmp_path / "graph-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    artifact_path = tmp_path / receipt["artifact_path"]
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(ProvenanceError, match=expected_error):
        render_benchmarks(
            report_path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


@pytest.mark.parametrize("mismatch", ["successful", "split", "calls"])
def test_the_renderer_rejects_inconsistent_artifact_batch_accounting(
    tmp_path: Path, mismatch: str
) -> None:
    """Every recorded call must be classified as successful, split, or failed."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")

    artifact = _artifact()
    receipt_overrides: dict[str, object] = {}
    if mismatch == "successful":
        artifact["successful_batches"] = 6
    elif mismatch == "split":
        artifact["split_batches"] = 1
        receipt_overrides["split_count"] = 1
    else:
        artifact["calls"].append(
            {
                "order": 7,
                "input_digest": f"{7:064x}",
                "raw_completion": "{}",
            }
        )
        receipt_overrides["replayed_call_count"] = 8
    artifact_sha256 = _artifact_sha256(artifact)
    receipt = _graph_replay(
        artifact_path=f"data/demo/graph-replay/{artifact_sha256}.json",
        artifact_sha256=artifact_sha256,
        **receipt_overrides,
    )
    receipt_path = tmp_path / "graph-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    artifact_path = tmp_path / receipt["artifact_path"]
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="batch accounting") as caught:
        render_benchmarks(
            report_path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )

    message = str(caught.value)
    for field in ("successful_batches", "split_batches", "failed_batches", "calls"):
        assert field in message


def test_the_renderer_refuses_reports_that_disagree_about_their_inputs(tmp_path: Path) -> None:
    """Two halves of one page have to come from one run.

    A retrieval report from one commit and an answers report from another
    render into a single page that describes neither.
    """
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]

    retrieval = tmp_path / "retrieval.json"
    retrieval.write_text(json.dumps(_report()), encoding="utf-8")
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            _report(
                kind="answers",
                git_commit="def5678",
                config={"compression": False},
                summary={},
                records=[],
            )
        ),
        encoding="utf-8",
    )
    receipt_path, snapshot_path = _evidence_paths(tmp_path)

    with pytest.raises(ProvenanceError) as caught:
        render_benchmarks(
            retrieval,
            answers,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )

    assert "git_commit" in str(caught.value)


@pytest.mark.parametrize(
    ("receipt_field", "bad_value"),
    [
        ("artifact_sha256", "e" * 64),
        ("extraction_model", "google:not-the-extraction-model"),
        ("domain_digest", "e" * 64),
        ("corpus_digest", "e" * 64),
        ("snapshot", "benchmark-from-another-run"),
        ("counts", {"entities": 77, "relationships": 72}),
    ],
)
def test_the_renderer_rejects_a_graph_receipt_with_mismatched_identity(
    tmp_path: Path, receipt_field: str, bad_value: object
) -> None:
    """A replay receipt cannot lend its identity to a different report."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(
        tmp_path, receipt_overrides={receipt_field: bad_value}
    )

    with pytest.raises(ProvenanceError) as caught:
        render_benchmarks(
            path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )

    assert receipt_field in str(caught.value)


@pytest.mark.parametrize(
    ("snapshot_field", "bad_value"),
    [
        ("git_commit", "def5678"),
        ("embedding_versions", ["other-embedding@64"]),
    ],
)
def test_the_renderer_rejects_a_snapshot_with_mismatched_identity(
    tmp_path: Path, snapshot_field: str, bad_value: object
) -> None:
    """The named snapshot must identify the same code and embeddings as the report."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(
        tmp_path, snapshot_overrides={snapshot_field: bad_value}
    )

    with pytest.raises(ProvenanceError, match=snapshot_field):
        render_benchmarks(
            report_path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


@pytest.mark.parametrize(
    "count", ["documents", "chunks", "entities", "relationships", "communities"]
)
def test_the_renderer_rejects_a_snapshot_with_mismatched_corpus_counts(
    tmp_path: Path, count: str
) -> None:
    """Every reported corpus count belongs to the exact named snapshot."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    snapshot_counts = dict(_snapshot()["counts"])
    snapshot_counts[count] += 1
    receipt_path, snapshot_path = _evidence_paths(
        tmp_path, snapshot_overrides={"counts": snapshot_counts}
    )

    with pytest.raises(ProvenanceError, match=count):
        render_benchmarks(
            report_path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


def test_the_renderer_rejects_a_snapshot_embedding_that_disagrees_with_provenance(
    tmp_path: Path,
) -> None:
    """Configured and persisted embedding identities must describe one benchmark."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    report = _report()
    report["provenance"] = {**report["provenance"], "embedding": "other-embedding@64"}
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(tmp_path)

    with pytest.raises(ProvenanceError, match="embedding"):
        render_benchmarks(
            report_path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


@pytest.mark.parametrize("malformation", ["missing", "unexpected"])
def test_the_renderer_validates_the_complete_snapshot_shape(
    tmp_path: Path, malformation: str
) -> None:
    """Published evidence accepts only the versioned snapshot shape the CLI writes."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(tmp_path)
    snapshot = _snapshot()
    if malformation == "missing":
        snapshot.pop("created_at")
    else:
        snapshot["unexpected"] = True
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="snapshot shape"):
        render_benchmarks(
            report_path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


@pytest.mark.parametrize("malformation", ["missing_count", "boolean_count", "versions_not_list"])
def test_the_renderer_validates_snapshot_field_types_before_comparing_evidence(
    tmp_path: Path, malformation: str
) -> None:
    """Malformed snapshot values fail as provenance rather than raw indexing errors."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(tmp_path)
    snapshot = _snapshot()
    if malformation == "missing_count":
        snapshot["counts"].pop("communities")
    elif malformation == "boolean_count":
        snapshot["counts"]["communities"] = False
    else:
        snapshot["embedding_versions"] = "local-hash-v1@64"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ProvenanceError, match=r"counts|embedding_versions"):
        render_benchmarks(
            report_path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("receipt_overrides", "expected_error"),
    [
        ({"counts": None}, "counts"),
        ({"counts": {"entities": 76}}, "counts"),
        ({"counts": {"entities": "76", "relationships": 72}}, "counts"),
        ({"replayed_call_count": "7"}, "replayed_call_count"),
        ({"replayed_call_count": None}, "replayed_call_count"),
    ],
)
def test_the_renderer_validates_receipt_types_before_reading_the_artifact(
    tmp_path: Path,
    receipt_overrides: dict[str, object],
    expected_error: str,
) -> None:
    """Malformed receipt data fails as provenance, before artifact indexing or I/O."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(tmp_path, receipt_overrides=receipt_overrides)
    artifact_path = tmp_path / _graph_replay()["artifact_path"]
    artifact_path.unlink()

    with pytest.raises(ProvenanceError, match=expected_error):
        render_benchmarks(
            report_path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


def test_the_renderer_rejects_a_mixed_live_and_strict_replay_receipt(tmp_path: Path) -> None:
    """Strict replay cannot publish if even one extraction call was live."""
    ProvenanceError = _renderer()["ProvenanceError"]
    render_benchmarks = _renderer()["render_benchmarks"]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(
        tmp_path, receipt_overrides={"extracted_call_count": 1}
    )

    with pytest.raises(ProvenanceError, match=r"extracted_call_count|live extraction"):
        render_benchmarks(
            path,
            None,
            graph_receipt=receipt_path,
            snapshot_path=snapshot_path,
            artifact_root=tmp_path,
        )


def test_the_page_names_the_models_the_run_used_not_the_ambient_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The renderer used to print `get_settings().llm_model` from its own shell."""
    render_benchmarks = _renderer()["render_benchmarks"]

    monkeypatch.setenv("SCI_RAG_LLM_MODEL", "not-the-model-that-ran")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    receipt_path, snapshot_path = _evidence_paths(tmp_path)

    page = render_benchmarks(
        path,
        None,
        graph_receipt=receipt_path,
        snapshot_path=snapshot_path,
        artifact_root=tmp_path,
    )

    assert "google:gemini-2.5-flash" in page
    assert "not-the-model-that-ran" not in page
