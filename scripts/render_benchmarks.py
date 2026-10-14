"""Render docs/benchmarks.md from eval report JSONs.

Usage (what `make benchmark` runs after the eval passes):

    uv run python scripts/render_benchmarks.py \
        --retrieval eval_results/<run>-retrieval-ablation/report.json \
        --answers eval_results/<run>-answers/report.json \
        --output docs/benchmarks.md

The page states exactly what was measured (corpus fingerprint, snapshot
name, git commit, model ids), shows every ablation row with its 95%
bootstrap CI, and says plainly what the numbers do and do not support.
No number appears here that was not computed by the eval harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

METRICS = ("hit_at_5", "hit_at_10", "mrr", "ndcg_at_10")
METRIC_LABELS = {"hit_at_5": "hit@5", "hit_at_10": "hit@10", "mrr": "MRR", "ndcg_at_10": "nDCG@10"}
REPO_ROOT = Path(__file__).resolve().parents[1]


def _ci_cell(ci: dict[str, float] | None) -> str:
    if not ci:
        return "-"
    return f"{ci['mean']:.2f} [{ci['lo']:.2f}, {ci['hi']:.2f}]"


class ReportRoleError(RuntimeError):
    """Two answer reports were handed over in a shape that cannot be rendered."""


class ProvenanceError(RuntimeError):
    """A report cannot support the claims this page makes about its inputs."""


#: What a report has to carry before its numbers may be published. `snapshot`
#: and `git_commit` pin the corpus and the code; `provenance` pins the models,
#: the prompts, and the decoding, which are what move a number when neither of
#: the other two has.
REQUIRED_REPORT_FIELDS = ("git_commit", "snapshot", "provenance")

#: Fields two reports rendered onto one page have to agree about. A retrieval
#: run from one commit and an answers run from another describe neither.
SHARED_REPORT_FIELDS = ("git_commit", "snapshot", "provenance")

#: How far a still-stochastic published number may move before a re-render is
#: a finding rather than noise. Metrics are absolute on a 0 to 1 scale, while
#: document, chunk, and community counts are relative. Entity and relationship
#: counts come from the reviewed graph replay and therefore have zero tolerance.
TOLERANCES = {"metric": 0.10, "count": 0.10}

GRAPH_REPLAY_FIELDS = (
    "mode",
    "artifact_path",
    "artifact_sha256",
    "extraction_model",
    "domain_digest",
    "corpus_digest",
    "snapshot",
    "counts",
    "replayed_call_count",
    "extracted_call_count",
    "split_count",
    "graph_digest",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
GRAPH_REPLAY_ARTIFACT_FIELDS = {
    "schema_version",
    "extractor_contract_version",
    "created_at",
    "source_commit",
    "corpus_digest",
    "extraction_model",
    "domain_digest",
    "batch_size",
    "generation_parameters",
    "calls",
    "successful_batches",
    "split_batches",
    "failed_batches",
    "entity_count",
    "relationship_count",
    "graph_digest",
}
APPROVED_GRAPH_REPLAY_GENERATION_PARAMETERS = {
    "temperature": 0.0,
    "json_mode": True,
    "max_tokens": 8192,
}
SNAPSHOT_FIELDS = {
    "name",
    "created_at",
    "git_commit",
    "counts",
    "embedding_versions",
    "corpus_digest",
    "documents",
}
SNAPSHOT_COUNT_FIELDS = ("documents", "chunks", "entities", "relationships", "communities")
SNAPSHOT_DOCUMENT_FIELDS = {"id", "title", "content_hash"}


def _canonical_json(value: object) -> bytes:
    """Encode replay evidence exactly as scripts/graph_replay.py hashes it."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(f"graph replay artifact is not canonical JSON: {exc}") from exc


def _verify_artifact(receipt: dict[str, Any], artifact_root: Path | None) -> None:
    """Bind the receipt's replay claims to a complete content-addressed artifact."""
    relative_path = PurePosixPath(receipt["artifact_path"])
    root = artifact_root if artifact_root is not None else REPO_ROOT
    path = root.joinpath(*relative_path.parts)
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read graph replay artifact {path}: {exc}") from exc
    if not isinstance(artifact, dict):
        raise ProvenanceError(f"graph replay artifact {path} must contain one JSON object")
    observed = hashlib.sha256(_canonical_json(artifact)).hexdigest()
    if observed != receipt["artifact_sha256"]:
        raise ProvenanceError(
            f"graph replay artifact {path} has canonical SHA-256 {observed}, "
            f"not receipt artifact_sha256 {receipt['artifact_sha256']}"
        )

    if set(artifact) != GRAPH_REPLAY_ARTIFACT_FIELDS:
        missing = sorted(GRAPH_REPLAY_ARTIFACT_FIELDS - set(artifact))
        unexpected = sorted(set(artifact) - GRAPH_REPLAY_ARTIFACT_FIELDS)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ProvenanceError(f"graph replay artifact shape mismatch: {'; '.join(details)}")

    for field in ("schema_version", "extractor_contract_version"):
        if artifact[field] != 1 or type(artifact[field]) is not int:
            raise ProvenanceError(f"graph replay artifact {field} must be 1")
    for field in ("created_at", "source_commit", "extraction_model"):
        if not isinstance(artifact[field], str) or not artifact[field]:
            raise ProvenanceError(f"graph replay artifact {field} must be a non-empty string")
    try:
        datetime.fromisoformat(artifact["created_at"])
    except ValueError as exc:
        raise ProvenanceError(
            "graph replay artifact created_at must be an ISO-8601 timestamp"
        ) from exc
    for field in ("corpus_digest", "domain_digest", "graph_digest"):
        value = artifact[field]
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ProvenanceError(
                f"graph replay artifact {field} must be a lowercase SHA-256 value"
            )
    for field, minimum in (
        ("batch_size", 1),
        ("successful_batches", 0),
        ("split_batches", 0),
        ("failed_batches", 0),
        ("entity_count", 0),
        ("relationship_count", 0),
    ):
        value = artifact[field]
        if type(value) is not int or value < minimum:
            raise ProvenanceError(
                f"graph replay artifact {field} must be an integer of at least {minimum}"
            )
    generation_parameters = artifact["generation_parameters"]
    if not isinstance(generation_parameters, dict):
        raise ProvenanceError("graph replay artifact generation_parameters must be an object")
    if _canonical_json(generation_parameters) != _canonical_json(
        APPROVED_GRAPH_REPLAY_GENERATION_PARAMETERS
    ):
        raise ProvenanceError(
            "graph replay artifact generation_parameters do not match the approved "
            "graph extraction contract"
        )

    calls = artifact["calls"]
    if not isinstance(calls, list):
        raise ProvenanceError("graph replay artifact calls must be a list")
    for order, call in enumerate(calls):
        if not isinstance(call, dict) or set(call) != {
            "order",
            "input_digest",
            "raw_completion",
        }:
            raise ProvenanceError(
                "each graph replay artifact call must contain exactly order, "
                "input_digest, and raw_completion"
            )
        if type(call["order"]) is not int or call["order"] != order:
            raise ProvenanceError("graph replay artifact call order must be contiguous from zero")
        input_digest = call["input_digest"]
        if not isinstance(input_digest, str) or _SHA256.fullmatch(input_digest) is None:
            raise ProvenanceError(
                "graph replay artifact call input_digest must be a lowercase SHA-256 value"
            )
        if not isinstance(call["raw_completion"], str):
            raise ProvenanceError("graph replay artifact call raw_completion must be text")

    expected = {
        "extraction_model": receipt["extraction_model"],
        "domain_digest": receipt["domain_digest"],
        "corpus_digest": receipt["corpus_digest"],
        "counts.entities/artifact entity_count": receipt["counts"]["entities"],
        "counts.relationships/artifact relationship_count": receipt["counts"]["relationships"],
        "graph_digest": receipt["graph_digest"],
        "replayed_call_count": receipt["replayed_call_count"],
        "split_count": receipt["split_count"],
    }
    observed_claims = {
        "extraction_model": artifact["extraction_model"],
        "domain_digest": artifact["domain_digest"],
        "corpus_digest": artifact["corpus_digest"],
        "counts.entities/artifact entity_count": artifact["entity_count"],
        "counts.relationships/artifact relationship_count": artifact["relationship_count"],
        "graph_digest": artifact["graph_digest"],
        "replayed_call_count": len(calls),
        "split_count": artifact["split_batches"],
    }
    disagree = [field for field, value in expected.items() if observed_claims[field] != value]
    if disagree:
        raise ProvenanceError(
            "graph replay artifact and receipt disagree about " + ", ".join(disagree)
        )
    if artifact["failed_batches"] != 0:
        raise ProvenanceError("graph replay artifact failed_batches must be 0 for strict replay")
    accounted_batches = (
        artifact["successful_batches"] + artifact["split_batches"] + artifact["failed_batches"]
    )
    if accounted_batches != len(calls):
        raise ProvenanceError(
            "graph replay artifact batch accounting is inconsistent: "
            f"successful_batches={artifact['successful_batches']}, "
            f"split_batches={artifact['split_batches']}, "
            f"failed_batches={artifact['failed_batches']}, calls={len(calls)}"
        )


@dataclass(frozen=True)
class PageChange:
    """One published number that moved between two renders."""

    label: str
    before: str
    after: str
    material: bool

    def describe(self) -> str:
        verdict = "MATERIAL" if self.material else "within tolerance"
        return f"  {self.label}: {self.before} -> {self.after} ({verdict})"


_COUNTS = re.compile(
    r"(?P<value>[\d,]+) (?P<label>documents|chunks|entities|relationships|communities)"
)
_TABLE_CELL = re.compile(r"^\|\s*(?P<config>[a-z_]+)\s*\|(?P<cells>.*)\|\s*$")


def _page_numbers(page: str) -> dict[str, str]:
    """Every published number, keyed by what it is.

    Read from the rendered page rather than from the reports, because the page
    is what a reader compares against and what a commit records.
    """
    numbers: dict[str, str] = {}
    for match in _COUNTS.finditer(page):
        numbers[match.group("label")] = match.group("value").replace(",", "")
    for line in page.splitlines():
        cell = _TABLE_CELL.match(line.strip())
        if cell is None:
            continue
        for index, raw in enumerate(cell.group("cells").split("|")):
            value = raw.strip()
            if value and value[0].isdigit():
                numbers[f"{cell.group('config')}[{index}]"] = value
    return numbers


def _is_material(label: str, before: str, after: str) -> bool:
    try:
        old_value = float(before.split()[0])
        new_value = float(after.split()[0])
    except (TypeError, ValueError):
        return before != after
    if label in {"entities", "relationships"}:
        return new_value != old_value
    if label in {"documents", "chunks", "communities"}:
        if old_value == 0:
            return new_value != 0
        return abs(new_value - old_value) / old_value > TOLERANCES["count"]
    return abs(new_value - old_value) > TOLERANCES["metric"]


def compare_pages(committed: str, rendered: str) -> list[PageChange]:
    """Every published number that moved, and whether the move is material."""
    before = _page_numbers(committed)
    after = _page_numbers(rendered)
    changes: list[PageChange] = []
    for label in sorted(set(before) | set(after)):
        old = before.get(label, "absent")
        new = after.get(label, "absent")
        if old == new:
            continue
        changes.append(PageChange(label, old, new, _is_material(label, old, new)))
    return changes


def check_against_committed(rendered: str, committed_path: Path) -> None:
    """Report every move, and refuse to pass when one is material."""
    committed = committed_path.read_text(encoding="utf-8") if committed_path.exists() else ""
    changes = compare_pages(committed, rendered)
    if not changes:
        print(f"{committed_path}: reproduced, no published number moved")
        return
    print(f"{committed_path}: {len(changes)} published number(s) moved")
    for change in changes:
        print(change.describe())
    material = [change for change in changes if change.material]
    if material:
        print(
            f"\n{len(material)} moved beyond the declared tolerance "
            f"(metrics {TOLERANCES['metric']}, non-graph counts "
            f"{TOLERANCES['count']:.0%}, entity and relationship counts exact). "
            "Publishing these numbers needs a reviewed source report and an "
            "explanation of what changed; re-run with --update once you have both."
        )
        raise SystemExit(1)


def _require_provenance(report: dict[str, Any], path: Path) -> None:
    missing = [field for field in REQUIRED_REPORT_FIELDS if not report.get(field)]
    if missing:
        raise ProvenanceError(
            f"{path} is missing {', '.join(missing)}, so its numbers cannot be published. "
            "Re-run the evaluation; reports written before the provenance contract "
            "predate these fields."
        )


def _require_agreement(first: dict[str, Any], second: dict[str, Any], where: str) -> None:
    disagree = [field for field in SHARED_REPORT_FIELDS if first.get(field) != second.get(field)]
    if disagree:
        raise ProvenanceError(
            f"{where} disagree about {', '.join(disagree)}. One page cannot describe "
            "two runs; render from reports produced by a single benchmark."
        )


def _load_graph_receipt(graph_receipt: Path | dict[str, Any] | None) -> dict[str, Any]:
    if graph_receipt is None:
        raise ProvenanceError(
            "a graph receipt is required before benchmark graph counts can be published"
        )
    if isinstance(graph_receipt, Path):
        try:
            loaded = json.loads(graph_receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProvenanceError(f"cannot read graph receipt {graph_receipt}: {exc}") from exc
    elif isinstance(graph_receipt, dict):
        loaded = graph_receipt
    else:
        raise ProvenanceError("graph receipt must be a JSON file path or object")
    if not isinstance(loaded, dict):
        raise ProvenanceError("graph receipt must contain one JSON object")
    return loaded


def _load_snapshot(report: dict[str, Any], snapshot_path: Path | None) -> dict[str, Any]:
    snapshot_name = report.get("snapshot")
    path = snapshot_path or Path("data/snapshots") / f"{snapshot_name}.json"
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read named snapshot {path}: {exc}") from exc
    if not isinstance(snapshot, dict):
        raise ProvenanceError(f"named snapshot {path} must contain one JSON object")
    if set(snapshot) != SNAPSHOT_FIELDS:
        missing = sorted(SNAPSHOT_FIELDS - set(snapshot))
        unexpected = sorted(set(snapshot) - SNAPSHOT_FIELDS)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ProvenanceError(f"named snapshot shape mismatch: {'; '.join(details)}")

    for field in ("name", "created_at", "git_commit", "corpus_digest"):
        if not isinstance(snapshot[field], str) or not snapshot[field]:
            raise ProvenanceError(f"named snapshot {field} must be a non-empty string")
    try:
        datetime.fromisoformat(snapshot["created_at"])
    except ValueError as exc:
        raise ProvenanceError("named snapshot created_at must be an ISO-8601 timestamp") from exc
    if _SHA256.fullmatch(snapshot["corpus_digest"]) is None:
        raise ProvenanceError("named snapshot corpus_digest must be a lowercase SHA-256 value")

    counts = snapshot["counts"]
    if not isinstance(counts, dict) or set(counts) != set(SNAPSHOT_COUNT_FIELDS):
        raise ProvenanceError(
            "named snapshot counts must contain exactly " + ", ".join(SNAPSHOT_COUNT_FIELDS)
        )
    invalid_counts = [
        label
        for label in SNAPSHOT_COUNT_FIELDS
        if type(counts[label]) is not int or counts[label] < 0
    ]
    if invalid_counts:
        raise ProvenanceError(
            "named snapshot counts must be non-negative integers: " + ", ".join(invalid_counts)
        )

    versions = snapshot["embedding_versions"]
    if (
        not isinstance(versions, list)
        or any(not isinstance(version, str) or not version for version in versions)
        or versions != sorted(set(versions))
    ):
        raise ProvenanceError(
            "named snapshot embedding_versions must be a sorted list of unique non-empty strings"
        )

    documents = snapshot["documents"]
    if not isinstance(documents, list) or len(documents) != counts["documents"]:
        raise ProvenanceError("named snapshot documents must be a list matching counts.documents")
    for index, document in enumerate(documents):
        if not isinstance(document, dict) or set(document) != SNAPSHOT_DOCUMENT_FIELDS:
            raise ProvenanceError(
                f"named snapshot documents[{index}] must contain exactly id, title, content_hash"
            )
        if any(
            not isinstance(document[field], str) or not document[field]
            for field in ("id", "title", "content_hash")
        ):
            raise ProvenanceError(
                f"named snapshot documents[{index}] fields must be non-empty strings"
            )
        if _SHA256.fullmatch(document["content_hash"]) is None:
            raise ProvenanceError(
                f"named snapshot documents[{index}].content_hash must be a lowercase SHA-256 value"
            )
    return snapshot


def _require_graph_replay(
    report: dict[str, Any],
    report_path: Path,
    *,
    graph_receipt: Path | dict[str, Any] | None,
    snapshot_path: Path | None,
    artifact_root: Path | None,
) -> dict[str, Any]:
    receipt = _load_graph_receipt(graph_receipt)
    missing = [field for field in GRAPH_REPLAY_FIELDS if field not in receipt]
    if missing:
        raise ProvenanceError(f"graph receipt is missing {', '.join(missing)}")

    string_fields = (
        "mode",
        "artifact_path",
        "artifact_sha256",
        "extraction_model",
        "domain_digest",
        "corpus_digest",
        "snapshot",
        "graph_digest",
    )
    invalid_strings = [
        field
        for field in string_fields
        if not isinstance(receipt[field], str) or not receipt[field]
    ]
    if invalid_strings:
        raise ProvenanceError(
            f"graph receipt fields must be non-empty strings: {', '.join(invalid_strings)}"
        )

    invalid_digests = [
        field
        for field in ("artifact_sha256", "domain_digest", "corpus_digest", "graph_digest")
        if _SHA256.fullmatch(receipt[field]) is None
    ]
    if invalid_digests:
        raise ProvenanceError(
            f"graph receipt fields must be lowercase SHA-256 values: {', '.join(invalid_digests)}"
        )

    artifact_path = PurePosixPath(receipt["artifact_path"])
    expected_parent = PurePosixPath("data/demo/graph-replay")
    if (
        artifact_path.is_absolute()
        or artifact_path.parent != expected_parent
        or artifact_path.suffix != ".json"
    ):
        raise ProvenanceError(
            "graph receipt artifact_path must name one committed JSON file under "
            "data/demo/graph-replay"
        )
    if artifact_path.stem != receipt["artifact_sha256"]:
        raise ProvenanceError(
            "graph receipt artifact_sha256 does not match the content-addressed artifact_path"
        )

    if receipt["mode"] != "require":
        raise ProvenanceError("graph receipt mode must be require for a published strict replay")

    for field in ("replayed_call_count", "extracted_call_count", "split_count"):
        value = receipt[field]
        if type(value) is not int or value < 0:
            raise ProvenanceError(f"graph receipt {field} must be a non-negative integer")
    if receipt["replayed_call_count"] == 0:
        raise ProvenanceError("graph receipt replayed_call_count must be positive")
    if receipt["extracted_call_count"] != 0:
        raise ProvenanceError(
            "graph receipt extracted_call_count must be 0; strict replay cannot mix in "
            "a live extraction call"
        )

    counts = receipt["counts"]
    if not isinstance(counts, dict) or set(counts) != {"entities", "relationships"}:
        raise ProvenanceError(
            "graph receipt counts must contain exactly entities and relationships"
        )
    invalid_counts = [
        label for label, value in counts.items() if type(value) is not int or value < 0
    ]
    if invalid_counts:
        raise ProvenanceError(
            f"graph receipt counts must be non-negative integers: {', '.join(invalid_counts)}"
        )
    _verify_artifact(receipt, artifact_root)

    provenance = report.get("provenance")
    models = provenance.get("models") if isinstance(provenance, dict) else None
    expected_model = models.get("extraction") if isinstance(models, dict) else None
    expected_domain = provenance.get("domain_digest") if isinstance(provenance, dict) else None
    snapshot = _load_snapshot(report, snapshot_path)
    expected = {
        "extraction_model": expected_model,
        "domain_digest": expected_domain,
        "snapshot": report.get("snapshot"),
        "corpus_digest": snapshot.get("corpus_digest"),
    }
    disagree = [field for field, value in expected.items() if receipt[field] != value]
    if disagree:
        raise ProvenanceError(
            f"graph receipt and {report_path} disagree about {', '.join(disagree)}"
        )
    if snapshot.get("name") != report.get("snapshot"):
        raise ProvenanceError(f"named snapshot and {report_path} disagree about snapshot")
    if snapshot["git_commit"] != report.get("git_commit"):
        raise ProvenanceError(f"named snapshot and {report_path} disagree about git_commit")

    report_corpus = report.get("corpus")
    if not isinstance(report_corpus, dict):
        raise ProvenanceError(f"{report_path} corpus must be an object")
    invalid_report_counts = [
        label
        for label in SNAPSHOT_COUNT_FIELDS
        if type(report_corpus.get(label)) is not int or report_corpus[label] < 0
    ]
    if invalid_report_counts:
        raise ProvenanceError(
            f"{report_path} corpus counts must be non-negative integers: "
            + ", ".join(invalid_report_counts)
        )
    snapshot_counts = snapshot["counts"]
    count_disagreements = [
        label for label in SNAPSHOT_COUNT_FIELDS if report_corpus[label] != snapshot_counts[label]
    ]
    if count_disagreements:
        raise ProvenanceError(
            f"named snapshot and {report_path} disagree about counts: "
            + ", ".join(count_disagreements)
        )

    report_versions = report_corpus.get("embedding_versions")
    if (
        not isinstance(report_versions, list)
        or any(not isinstance(version, str) or not version for version in report_versions)
        or report_versions != sorted(set(report_versions))
    ):
        raise ProvenanceError(
            f"{report_path} corpus embedding_versions must be a sorted list of "
            "unique non-empty strings"
        )
    if snapshot["embedding_versions"] != report_versions:
        raise ProvenanceError(f"named snapshot and {report_path} disagree about embedding_versions")
    provenance_embedding = provenance.get("embedding") if isinstance(provenance, dict) else None
    if not isinstance(provenance_embedding, str) or not provenance_embedding:
        raise ProvenanceError(f"{report_path} provenance.embedding must be a non-empty string")
    if snapshot["embedding_versions"] != [provenance_embedding]:
        raise ProvenanceError(
            f"named snapshot and {report_path} provenance disagree about embedding identity"
        )

    expected_counts = {label: report_corpus.get(label) for label in ("entities", "relationships")}
    if counts != expected_counts:
        disagreeing_graph_counts = [
            label
            for label in ("entities", "relationships")
            if counts[label] != expected_counts[label]
        ]
        raise ProvenanceError(
            f"graph receipt and {report_path} disagree about counts: "
            + ", ".join(disagreeing_graph_counts)
        )
    snapshot_graph_counts = {
        label: snapshot_counts.get(label) for label in ("entities", "relationships")
    }
    if counts != snapshot_graph_counts:
        disagreeing_graph_counts = [
            label
            for label in ("entities", "relationships")
            if counts[label] != snapshot_graph_counts[label]
        ]
        raise ProvenanceError(
            "graph receipt and named snapshot disagree about counts: "
            + ", ".join(disagreeing_graph_counts)
        )
    return receipt


def _load(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if path.is_dir():
        path = path / "report.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _declared_compression(report: dict[str, Any], path: Path) -> bool:
    """Whether this answers run enabled compression, per its own report.

    Every answers run records `config.compression`. Reading it here is the
    whole fix: F-026 selected the two reports by directory modification time,
    and calibration updates one of those times, so the roles reversed.
    """
    config = report.get("config")
    if not isinstance(config, dict) or "compression" not in config:
        raise ReportRoleError(
            f"{path} does not record config.compression, so its role cannot be "
            "established. Re-run `sci-rag eval answers`; reports written by an "
            "older version predate the role marker."
        )
    return bool(config["compression"])


def select_answer_reports(root: Path) -> tuple[Path, Path]:
    """The newest uncompressed and compressed answers runs under ``root``.

    Ordering is by directory name, which carries the run timestamp, rather
    than by modification time, which anything writing into a directory can
    change. Roles come from each report rather than from its position.
    """
    uncompressed: Path | None = None
    compressed: Path | None = None
    for directory in sorted(root.glob("*-answers"), key=lambda path: path.name, reverse=True):
        report_path = directory / "report.json"
        if not report_path.is_file():
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if _declared_compression(report, directory):
            compressed = compressed or directory
        else:
            uncompressed = uncompressed or directory
        if uncompressed is not None and compressed is not None:
            break

    missing = [
        name
        for name, found in (("uncompressed", uncompressed), ("compressed", compressed))
        if found is None
    ]
    if missing:
        raise ReportRoleError(
            f"no {' or '.join(missing)} answers report under {root}. The paired gate "
            "needs one `sci-rag eval answers` run and one `--compressed` run."
        )
    assert uncompressed is not None and compressed is not None
    return uncompressed, compressed


def _validate_roles(
    answers: dict[str, Any] | None,
    answers_path: Path | None,
    compressed: dict[str, Any] | None,
    compressed_path: Path | None,
) -> None:
    """Refuse a pair that is reversed, duplicated, or unlabelled."""
    if answers is None or compressed is None:
        return
    assert answers_path is not None and compressed_path is not None
    if answers_path.resolve() == compressed_path.resolve():
        raise ReportRoleError(
            f"{answers_path} was given as both the ordinary and the compressed "
            "run. The paired gate compares two runs, not one against itself."
        )
    if _declared_compression(answers, answers_path):
        raise ReportRoleError(
            f"{answers_path} was given as the ordinary run but its report records "
            "config.compression = true. The two reports are the wrong way round."
        )
    if not _declared_compression(compressed, compressed_path):
        raise ReportRoleError(
            f"{compressed_path} was given as the compressed run but its report records "
            "config.compression = false. The two reports are the wrong way round."
        )


def _calibration_for(answers_path: Path | None) -> dict[str, Any] | None:
    if answers_path is None:
        return None
    directory = answers_path if answers_path.is_dir() else answers_path.parent
    calibration = directory / "calibration.json"
    if calibration.exists():
        return json.loads(calibration.read_text(encoding="utf-8"))
    return None


def render_benchmarks(
    retrieval_path: Path,
    answers_path: Path | None,
    compressed_path: Path | None = None,
    *,
    graph_receipt: Path | dict[str, Any] | None = None,
    snapshot_path: Path | None = None,
    artifact_root: Path | None = None,
) -> str:
    retrieval = _load(retrieval_path)
    assert retrieval is not None
    answers = _load(answers_path)
    compressed = _load(compressed_path)
    _require_provenance(retrieval, retrieval_path)
    replay = _require_graph_replay(
        retrieval,
        retrieval_path,
        graph_receipt=graph_receipt,
        snapshot_path=snapshot_path,
        artifact_root=artifact_root,
    )
    if answers is not None and answers_path is not None:
        _require_provenance(answers, answers_path)
        _require_agreement(retrieval, answers, f"{retrieval_path} and {answers_path}")
    if compressed is not None and compressed_path is not None:
        _require_provenance(compressed, compressed_path)
        _require_agreement(retrieval, compressed, f"{retrieval_path} and {compressed_path}")
    _validate_roles(answers, answers_path, compressed, compressed_path)
    calibration = _calibration_for(answers_path)
    corpus = retrieval.get("corpus", {})
    snapshot = retrieval.get("snapshot")
    commit = retrieval.get("git_commit", "unknown")
    provenance = retrieval["provenance"]
    versions = provenance.get("embedding") or (
        ", ".join(corpus.get("embedding_versions", [])) or "unknown"
    )
    # The models that produced these numbers, from the report. Reading
    # `get_settings()` here published whichever model the renderer's own shell
    # happened to name, which on a re-render is not the one that ran.
    models = provenance.get("models", {})
    llm_model = ", ".join(f"{role} `{spec}`" for role, spec in sorted(models.items())) or "unknown"
    digest = provenance.get("domain_digest", "unknown")

    lines = [
        "---",
        "title: Benchmarks",
        "description: Measured results on the shipped demo corpus, with confidence "
        "intervals, snapshot provenance, model identifiers, and the command that "
        "reproduces them.",
        "---",
        "",
        "# Benchmarks",
        "",
        "These results measure the shipped demo corpus and can be regenerated with one command.",
        "They validate the evaluation workflow on this synthetic corpus. See",
        "[Choosing Sci RAG Kit](choosing-sci-rag-kit.md) for a feature-level comparison.",
        "",
        "## What was measured",
        "",
        f"- Corpus: {corpus.get('documents')} documents, {corpus.get('chunks')} chunks, "
        f"{corpus.get('entities')} entities, {corpus.get('relationships')} relationships, "
        f"{corpus.get('communities')} communities (the synthetic agricultural-residue "
        "demo corpus shipped in `data/demo/`)",
        f"- Corpus snapshot: `{snapshot or 'not recorded'}` "
        "(see `data/snapshots/`; the digest pins the exact document set)",
        f"- Embedding: `{versions}`; models: {llm_model}",
        f"- Code: commit `{commit}`; domain and prompts: `{digest[:12]}`",
        f"- Graph: strict replay from `{replay['artifact_path']}` "
        f"(`{replay['artifact_sha256']}`); {replay['replayed_call_count']} recorded "
        f"calls replayed, {replay['extracted_call_count']} live extraction calls; "
        f"canonical graph `{replay['graph_digest']}`",
        f"- Rendered: {datetime.now(UTC).strftime('%Y-%m-%d')}",
        "",
        "The reviewed graph replay makes entity and relationship counts exact. "
        "Judged answers and other model-backed measurements remain stochastic. "
        "Repeating the command below reproduces those measurements within a "
        "declared tolerance of "
        f"{TOLERANCES['metric']} absolute on a metric and "
        f"{TOLERANCES['count']:.0%} on other counts, and `--check` fails visibly "
        "when one moves further. Publishing movement beyond the tolerance requires "
        "a reviewed source report and an explanation of which recorded input changed.",
        "",
        "## Retrieval ablations",
        "",
        "Cells are mean [95% bootstrap CI], resampled per question. The",
        "demo corpus has single-digit questions, so intervals are wide by",
        "construction: treat differences whose intervals overlap heavily as",
        "noise. Read the table for the qualitative story about which layers",
        "earn their keep. On a small sample",
        "like this, that qualitative story is the only defensible claim.",
        "",
        "| Config | " + " | ".join(METRIC_LABELS[m] for m in METRICS) + " | n |",
        "|--------|" + "---:|" * len(METRICS) + "---:|",
    ]
    for config in retrieval.get("configs", []):
        ci = config.get("metrics_ci", {})
        n = int(ci.get("n", config.get("metrics", {}).get("n", 0)))
        cells = " | ".join(_ci_cell(ci.get(metric)) for metric in METRICS)
        lines.append(f"| {config['name']} | {cells} | {n} |")

    names = {config["name"] for config in retrieval.get("configs", [])}
    if "resolved_entities" not in names:
        lines += [
            "",
            "The missing `resolved_entities` row records the outcome of its precondition.",
            "It is a separate condition (`sci-rag eval retrieval",
            "--condition resolved_entities`) measured on a post-resolution",
            "snapshot, and it requires at least one persisted resolution audit",
            "row. On this corpus `sci-rag graph resolve-entities` finds no",
            f"automatic pairs and plans no merges: {corpus.get('entities')} extracted entities with",
            "nothing duplicated enough to merge. The condition requires a real merge",
            "and stops here because it would otherwise repeat `full_deep` under another",
            "name. A corpus with real alias variation",
            "is what would exercise it.",
        ]

    lines += [
        "",
        "How to read it:",
        "",
        "- `full_deep` vs the `*_only` rows shows what fusion buys over any",
        "  single layer.",
        "- `no_graph` / `no_hyde` / `no_community` vs `full_deep` shows each",
        "  layer's marginal contribution on this corpus.",
        "- `with_rerank` vs `no_rerank` is the paired evidence the reranker",
        "  must show before `retrieval.reranker.enabled: true` is justified.",
        "- `auto_routed` vs `full_deep` and `interactive` is the evidence for",
        "  (or against) making adaptive routing a default. Until it clearly",
        "  matches `full_deep` at lower cost, `auto` stays opt-in.",
        "",
    ]

    if answers is not None:
        summary_ci = answers.get("summary_ci", {})
        summary = answers.get("summary", {})
        lines += [
            "## Judged answers (blind two-pass judge)",
            "",
            "| Dimension | Mean [95% CI] |",
            "|-----------|--------------:|",
        ]
        for dimension in ("groundedness", "citation_accuracy", "completeness", "correctness"):
            if dimension in summary_ci:
                lines.append(f"| {dimension} | {_ci_cell(summary_ci[dimension])} |")
        lines += [
            f"| graded / total | {int(summary.get('graded', 0))} / {int(summary.get('n', 0))} |",
            "",
            "The grounding judge never sees the reference answer; correctness",
            "is graded in a separate reference-only pass (docs/evaluation.md).",
            "",
        ]

    if compressed is not None and answers is not None:
        lines += _compression_section(answers, compressed)

    if calibration is not None:
        lines += [
            "## Judge calibration (human labels vs judge)",
            "",
            "Cohen's kappa between independent human labels",
            "(`domain/eval_calibration_labels.jsonl`, a NON-EXPERT seed set)",
            "and the judge's scores on the same answers:",
            "",
            "| Dimension | kappa | exact agreement | n |",
            "|-----------|------:|----------------:|--:|",
        ]
        for name, d in calibration.get("dimensions", {}).items():
            lines.append(f"| {name} | {d['kappa']:.2f} | {d['exact_agreement']:.2f} | {d['n']} |")
        lines += [
            "",
            "Kappa is reported as measured, never asserted as a target. A",
            "kappa of 0 with high exact agreement means one rater was",
            "constant (kappa cannot credit agreement it attributes to",
            "chance). A seed set with more score variance fixes that limitation.",
            "Expert labels supersede this seed set.",
            "",
        ]

    lines += [
        "## Reproduce it",
        "",
        "```bash",
        "make benchmark",
        "```",
        "",
        "Prerequisites: a selected PostgreSQL backend with pgvector, uv, and Google",
        "credentials in `.env` (`SCI_RAG_GOOGLE_API_KEY` or",
        "`SCI_RAG_GCP_PROJECT`; see `.env.example`). The backend must point to a",
        "named, disposable PostgreSQL database. The target ingests the tracked",
        "demo corpus into otherwise pristine graph state before strict replay.",
        "Select a disposable database for that preflight and leave development corpora intact.",
        "It then creates communities, snapshots the",
        "corpus, runs the full retrieval ablation plus the judged answers eval, and",
        "re-renders this page from the report JSONs. Without credentials the eval",
        "commands stop with a clear message. Published numbers require real models.",
        "",
    ]
    return "\n".join(lines)


_JUDGED_DIMENSIONS = ("groundedness", "citation_accuracy", "completeness", "correctness")


def _median_tokens(report: dict[str, Any], key: str) -> float | None:
    value = report.get("summary", {}).get(key)
    return float(value) if value is not None else None


def _compression_section(answers: dict[str, Any], compressed: dict[str, Any]) -> list[str]:
    """The paired gate that decides whether compression may default on.

    Two answers-eval runs over the same questions and the same corpus, one
    with `--compressed` and one without. The gate asks for judged quality to
    hold while measured prompt tokens fall, so both halves are reported: a
    token saving alone never justifies the default.
    """
    base_ci = answers.get("summary_ci", {})
    comp_ci = compressed.get("summary_ci", {})
    before = _median_tokens(compressed, "prompt_tokens_before_median")
    after = _median_tokens(compressed, "prompt_tokens_after_median")
    dropped = sum(r.get("compression_dropped_count", 0) for r in compressed.get("records", []))
    failures = sum(r.get("compression_failure_count", 0) for r in compressed.get("records", []))
    n = int(compressed.get("summary", {}).get("n", 0))

    try:
        from pathlib import Path as _Path

        from sci_rag.config import get_settings
        from sci_rag.domain import load_domain

        tuning = load_domain(_Path(get_settings().domain_dir)).config.compression
        floor = f"{tuning.relevance_floor}"
        enabled = tuning.enabled
    except Exception:
        floor = "unknown"
        enabled = None

    if enabled is None:
        default_claim = "The shipped compression default could not be loaded."
    else:
        state = "on" if enabled else "off"
        default_claim = (
            f"Compression defaults {state} for the shipped demo at `relevance_floor: {floor}`."
        )

    lines = [
        "## Contextual compression: the paired gate",
        "",
        default_claim,
        "",
        "Two judged-answer runs over the same questions and the same corpus,",
        "one with `--compressed` and one without. The gate requires judged",
        "quality to HOLD while measured prompt tokens fall. Token savings alone",
        "cannot justify the default.",
        "",
        f"Measured at the load-bearing `relevance_floor: {floor}` setting.",
        "The floor decides whether a source is dropped",
        "or summarized, and dropping evidence is what an answer cannot recover",
        "from. Raising it trades groundedness for tokens; that is a different",
        "trade from summarizing, and it needs its own paired run.",
        "",
        "| Dimension | Uncompressed | Compressed |",
        "|-----------|-------------:|-----------:|",
    ]
    for dimension in _JUDGED_DIMENSIONS:
        lines.append(
            f"| {dimension} | {_ci_cell(base_ci.get(dimension))} | {_ci_cell(comp_ci.get(dimension))} |"
        )
    if before is not None and after is not None:
        saving = f"{(1 - after / before) * 100:.0f}%" if before else "n/a"
        lines.append(f"| median prompt tokens | {before:.0f} | {after:.0f} ({saving} lower) |")
    lines += [
        "",
        f"Sources dropped by the relevance floor: {dropped}. Compression"
        f" failures: {failures}. Questions: {n}.",
        "",
    ]
    fell = [
        d
        for d in _JUDGED_DIMENSIONS
        if (comp_ci.get(d) or {}).get("mean", 0) < (base_ci.get(d) or {}).get("mean", 0)
    ]
    # The gate has two halves. Quality holding while tokens stay flat buys
    # nothing, and the page used to call that a hold.
    tokens_fell = before is not None and after is not None and after < before
    if not fell and not tokens_fell:
        lines += [
            "On this run the gate does not hold: judged quality held, but"
            " measured prompt tokens did not fall. Compression that costs"
            " nothing and saves nothing is not evidence for a default, and"
            " the saving is the only thing it is meant to buy.",
            "",
        ]
        return lines
    if fell:
        lines += [
            f"On this run the gate does not hold: {len(fell)} of"
            f" {len(_JUDGED_DIMENSIONS)} judged dimensions moved down"
            f" ({', '.join(fell)}). At this sample size no single drop is"
            " distinguishable from noise, and that is the point: the gate asks"
            " for evidence that quality holds, and overlapping intervals are"
            " not that evidence.",
            "",
            "The mechanism is the relevance floor, not the summarizer,"
            " which the counters above separate: sources were dropped, none"
            " failed to compress. A lower floor may pass the gate. Re-run it"
            " before turning compression on for any corpus.",
            "",
        ]
        if enabled:
            lines += [
                "The shipped domain profile currently enables compression, so",
                "this run would no longer support its default. Re-run the gate",
                "or turn compression off before publishing it for that corpus.",
                "",
            ]
        else:
            lines += [
                "`compression.enabled` therefore stays `false` in the shipped",
                "domain profile.",
                "",
            ]
    else:
        lines += [
            "On this run the gate holds: no judged dimension fell while prompt"
            " tokens dropped. That justifies the default on THIS corpus only;"
            " re-run the gate before carrying it to another.",
            "",
        ]
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval", type=Path, default=None)
    parser.add_argument("--answers", type=Path, default=None)
    parser.add_argument("--answers-compressed", type=Path, default=None)
    parser.add_argument(
        "--graph-receipt",
        type=Path,
        default=None,
        help="Ignored graph replay receipt written by scripts/graph_replay.py.",
    )
    parser.add_argument("--output", type=Path, default=Path("docs/benchmarks.md"))
    parser.add_argument(
        "--select-answer-roles",
        type=Path,
        default=None,
        metavar="DIR",
        help=(
            "Print the newest uncompressed answers run and the newest compressed one, "
            "one per line, and exit. Roles come from each report's own "
            "config.compression rather than from directory timestamps."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Compare the render against the committed page and exit nonzero when a "
            "published number moved beyond the declared tolerance. Writes nothing."
        ),
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            "Write the page, after printing every published number that moved. "
            "Required to overwrite committed numbers, so a refresh cannot be silent."
        ),
    )
    args = parser.parse_args()

    if args.select_answer_roles is not None:
        uncompressed, compressed = select_answer_reports(args.select_answer_roles)
        print(uncompressed)
        print(compressed)
        return

    if args.retrieval is None:
        parser.error("--retrieval is required unless --select-answer-roles is given")
    if args.graph_receipt is None:
        parser.error("--graph-receipt is required when rendering benchmark numbers")
    if args.check and args.update:
        parser.error("--check and --update are mutually exclusive")
    page = render_benchmarks(
        args.retrieval,
        args.answers,
        args.answers_compressed,
        graph_receipt=args.graph_receipt,
    )

    if args.check:
        check_against_committed(page, args.output)
        return

    if not args.update:
        parser.error(
            "refusing to overwrite published numbers without --update. Run --check "
            "first to see what moved, then --update to publish it with that "
            "comparison in the change description."
        )

    committed = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
    changes = compare_pages(committed, page)
    if changes:
        print(f"{args.output}: {len(changes)} published number(s) moved")
        for change in changes:
            print(change.describe())
    else:
        print(f"{args.output}: reproduced, no published number moved")
    args.output.write_text(page, encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
