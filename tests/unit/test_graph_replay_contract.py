"""The committed benchmark graph replay artifact contract fails closed."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[2]))

import pytest
import scripts.graph_replay as graph_replay
from scripts.graph_replay import (
    GraphReplayError,
    ReplayArtifact,
    ReplayCall,
    ReplayLLM,
    _canonical_graph,
    artifact_sha256,
    call_input_digest,
    write_candidate,
)

GENERATION_PARAMETERS = {"temperature": 0.0, "json_mode": True, "max_tokens": 8192}
RAW_COMPLETION = '{"entities": [], "relationships": []}'


def _recorded_call(*, prompt: str = "extract this graph") -> ReplayCall:
    return ReplayCall(
        order=0,
        input_digest=call_input_digest(
            order=0,
            prompt=prompt,
            system=None,
            temperature=0.0,
            json_mode=True,
            max_tokens=8192,
            generation_parameters=GENERATION_PARAMETERS,
            extractor_contract_version=1,
        ),
        raw_completion=RAW_COMPLETION,
    )


def _artifact() -> ReplayArtifact:
    return ReplayArtifact(
        schema_version=1,
        extractor_contract_version=1,
        created_at="2026-09-01T00:00:00+00:00",
        source_commit="abc1234",
        corpus_digest="a" * 64,
        extraction_model="google:gemini-2.5-flash",
        domain_digest="b" * 64,
        batch_size=2,
        generation_parameters=GENERATION_PARAMETERS,
        calls=[_recorded_call()],
        successful_batches=1,
        split_batches=0,
        failed_batches=0,
        entity_count=0,
        relationship_count=0,
        graph_digest="c" * 64,
    )


@pytest.mark.parametrize(
    ("field", "drifted_value", "expected_error"),
    [
        ("corpus_digest", "d" * 64, "replay identity drift: corpus digest"),
        ("domain_digest", "e" * 64, "replay identity drift: domain digest"),
        ("batch_size", 3, "replay identity drift: batch size"),
        (
            "generation_parameters",
            {"temperature": 0.0, "json_mode": True, "max_tokens": 4096},
            "replay identity drift: generation parameters",
        ),
        ("schema_version", 2, "unsupported replay schema version 2; expected 1"),
        (
            "extractor_contract_version",
            2,
            "unsupported extractor contract version 2; expected 1",
        ),
    ],
    ids=(
        "corpus-digest",
        "domain-digest",
        "batch-size",
        "generation-parameters",
        "schema-version",
        "extractor-contract-version",
    ),
)
async def test_require_rejects_identity_drift_matrix_without_provider_or_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    drifted_value: object,
    expected_error: str,
) -> None:
    """Every strict identity mismatch stops before provider or output side effects."""
    raw_artifact = _artifact().to_dict()
    raw_artifact[field] = drifted_value
    canonical = json.dumps(
        raw_artifact,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    artifact_path = artifact_dir / f"{hashlib.sha256(canonical).hexdigest()}.json"
    artifact_path.write_text(json.dumps(raw_artifact), encoding="utf-8")
    original_artifact = artifact_path.read_bytes()

    async def corpus_state(_session_factory: object) -> SimpleNamespace:
        return SimpleNamespace(
            digest="a" * 64,
            document_count=1,
            chunk_count=1,
            non_demo_count=0,
            non_public_count=0,
            stamped_chunk_count=0,
            entity_count=0,
            relationship_count=0,
            community_count=0,
            resolution_audit_count=0,
        )

    def accept_tracked_demo(_state: object, _manifest_path: Path) -> None:
        return None

    monkeypatch.setattr(graph_replay, "_corpus_state", corpus_state)
    monkeypatch.setattr(graph_replay, "_require_tracked_demo", accept_tracked_demo)
    monkeypatch.setattr(graph_replay, "domain_digest", lambda _directory: "b" * 64)

    provider_calls = 0

    def forbidden_provider() -> Any:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("strict identity drift constructed a live provider")

    receipt_path = tmp_path / "receipt.json"
    candidate_dir = tmp_path / "candidates"
    files_before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}

    with pytest.raises(GraphReplayError, match=expected_error):
        await graph_replay.run_graph_replay(
            mode="require",
            receipt_path=receipt_path,
            session_factory=object(),  # type: ignore[arg-type]
            domain=SimpleNamespace(directory=tmp_path),  # type: ignore[arg-type]
            extraction_model="google:gemini-2.5-flash",
            llm_factory=forbidden_provider,
            artifact_path=artifact_path,
            artifact_dir=candidate_dir,
            manifest_path=tmp_path / "manifest.jsonl",
            batch_size=2,
            rate_limit_s=0.0,
        )

    assert provider_calls == 0
    assert artifact_path.read_bytes() == original_artifact
    assert not receipt_path.exists()
    assert not candidate_dir.exists()
    files_after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}
    assert files_after == files_before


def test_candidate_is_content_addressed_and_never_overwritten(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact_dir = tmp_path / "graph-replay"

    candidate = write_candidate(artifact, artifact_dir)

    assert candidate == artifact_dir / f"{artifact_sha256(artifact)}.json"
    original = candidate.read_bytes()
    with pytest.raises(GraphReplayError, match="already exists"):
        write_candidate(artifact, artifact_dir)
    assert candidate.read_bytes() == original


async def test_replay_rejects_call_drift_and_requires_exact_consumption() -> None:
    artifact = _artifact()
    replay = ReplayLLM(
        artifact.calls,
        extractor_contract_version=artifact.extractor_contract_version,
        generation_parameters=artifact.generation_parameters,
    )

    with pytest.raises(GraphReplayError, match="call 0"):
        await replay.generate_json("a changed prompt", max_tokens=8192)
    with pytest.raises(GraphReplayError, match="unused"):
        replay.assert_consumed()

    exact = ReplayLLM(
        artifact.calls,
        extractor_contract_version=artifact.extractor_contract_version,
        generation_parameters=artifact.generation_parameters,
    )
    assert await exact.generate_json("extract this graph", max_tokens=8192) == {
        "entities": [],
        "relationships": [],
    }
    exact.assert_consumed()
    with pytest.raises(GraphReplayError, match="missing recorded call"):
        await exact.generate_json("extract this graph", max_tokens=8192)


async def test_canonical_entities_do_not_inherit_database_order_for_equal_semantic_keys() -> None:
    """Casefold-equivalent rows use their complete ID-free payload as a tie-break."""

    class Result:
        def __init__(self, rows: list[Any]) -> None:
            self.rows = rows

        def all(self) -> list[Any]:
            return self.rows

        def scalars(self) -> Result:
            return self

    class Session:
        def __init__(self, entities: list[Any]) -> None:
            self.results = iter((Result([]), Result([]), Result(entities), Result([])))

        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def execute(self, statement: object) -> Result:
            return next(self.results)

    first = SimpleNamespace(
        id="database-id-first",
        name="Straße",
        entity_type="Feedstock",
        description="zeta payload",
        aliases=["beta"],
        document_ids=[],
        chunk_ids=[],
    )
    second = SimpleNamespace(
        id="database-id-second",
        name="STRASSE",
        entity_type="Feedstock",
        description="alpha payload",
        aliases=["alpha"],
        document_ids=[],
        chunk_ids=[],
    )

    forward, _, _ = await _canonical_graph(lambda: Session([first, second]))  # type: ignore[arg-type]
    reversed_rows, _, _ = await _canonical_graph(
        lambda: Session([second, first])  # type: ignore[arg-type]
    )

    assert forward == reversed_rows
    assert "database-id" not in repr(forward)
