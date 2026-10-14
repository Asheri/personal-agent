"""The benchmark page renderer: report JSONs in, honest markdown out."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import pytest
from scripts.render_benchmarks import ReportRoleError, select_answer_reports
from scripts.render_benchmarks import render_benchmarks as _render_benchmarks

CORPUS_DIGEST = "b" * 64
GRAPH_DIGEST = "d" * 64


def artifact_fixture() -> dict:
    return {
        "schema_version": 1,
        "extractor_contract_version": 1,
        "created_at": "2026-08-30T00:00:00+00:00",
        "source_commit": "abc1234",
        "corpus_digest": CORPUS_DIGEST,
        "extraction_model": "google:gemini-2.5-flash",
        "domain_digest": "a" * 64,
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


def artifact_sha256() -> str:
    canonical = json.dumps(
        artifact_fixture(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def graph_replay_fixture() -> dict:
    digest = artifact_sha256()
    return {
        "mode": "require",
        "artifact_path": f"data/demo/graph-replay/{digest}.json",
        "artifact_sha256": digest,
        "extraction_model": PROVENANCE["models"]["extraction"],
        "domain_digest": PROVENANCE["domain_digest"],
        "corpus_digest": CORPUS_DIGEST,
        "snapshot": "v0.2-demo",
        "counts": {"entities": 76, "relationships": 72},
        "replayed_call_count": 7,
        "extracted_call_count": 0,
        "split_count": 0,
        "graph_digest": GRAPH_DIGEST,
    }


def snapshot_fixture() -> dict:
    return {
        "name": "v0.2-demo",
        "created_at": "2026-08-27T16:00:00+00:00",
        "git_commit": "abc1234",
        "corpus_digest": CORPUS_DIGEST,
        "counts": {
            "documents": 5,
            "chunks": 34,
            "entities": 76,
            "relationships": 72,
            "communities": 10,
        },
        "embedding_versions": ["gemini-embedding-001@1536"],
        "documents": [
            {
                "id": f"document-{index}",
                "title": f"Document {index}",
                "content_hash": f"{index:064x}",
            }
            for index in range(5)
        ],
    }


def retrieval_fixture() -> dict:
    def config(name: str, hit5: float) -> dict:
        return {
            "name": name,
            "description": f"{name} description",
            "metrics": {
                "n": 9.0,
                "hit_at_5": hit5,
                "hit_at_10": hit5,
                "mrr": hit5,
                "ndcg_at_10": hit5,
            },
            "metrics_ci": {
                "n": 9,
                "hit_at_5": {"mean": hit5, "lo": hit5 - 0.1, "hi": 1.0, "n": 9.0},
                "hit_at_10": {"mean": hit5, "lo": hit5 - 0.1, "hi": 1.0, "n": 9.0},
                "mrr": {"mean": hit5, "lo": hit5 - 0.15, "hi": 1.0, "n": 9.0},
                "ndcg_at_10": {"mean": hit5, "lo": hit5 - 0.12, "hi": 1.0, "n": 9.0},
            },
            "records": [],
        }

    return {
        "kind": "retrieval",
        "generated_at": "2026-08-27T16:00:00+00:00",
        "git_commit": "abc1234",
        "snapshot": "v0.2-demo",
        "provenance": PROVENANCE,
        "corpus": {
            "documents": 5,
            "chunks": 34,
            "entities": 76,
            "relationships": 72,
            "communities": 10,
            "embedding_versions": ["gemini-embedding-001@1536"],
        },
        "configs": [
            config("full_deep", 1.0),
            config("keyword_only", 0.33),
            config("with_rerank", 1.0),
            config("auto_routed", 0.89),
        ],
    }


#: The receipt every fixture carries. Reports rendered onto one page have to
#: agree about their inputs, so they share one.
PROVENANCE = {
    "embedding": "gemini-embedding-001@1536",
    "models": {
        "answer": "google:gemini-2.5-flash",
        "extraction": "google:gemini-2.5-flash",
        "judge": "google:gemini-2.5-flash",
    },
    "domain_digest": "a" * 64,
    "decoding": {"temperature": 0.0, "judge_temperature": 0.0, "json_mode": True},
}


def answers_fixture() -> dict:
    return {
        "kind": "answers",
        "git_commit": "abc1234",
        "snapshot": "v0.2-demo",
        "provenance": PROVENANCE,
        "corpus": {"documents": 5, "chunks": 34},
        "summary": {"n": 10.0, "graded": 10.0, "failed": 0.0},
        "summary_ci": {
            "groundedness": {"mean": 2.0, "lo": 2.0, "hi": 2.0, "n": 10.0},
            "correctness": {"mean": 1.6, "lo": 1.1, "hi": 2.0, "n": 10.0},
        },
        "config": {"compression": False},
        "records": [],
    }


def render_benchmarks(
    retrieval_path: Path,
    answers_path: Path | None,
    compressed_path: Path | None = None,
) -> str:
    """Render through the external replay receipt contract used by Make."""
    report_path = retrieval_path / "report.json" if retrieval_path.is_dir() else retrieval_path
    snapshot_path = report_path.parent / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot_fixture()), encoding="utf-8")
    replay = graph_replay_fixture()
    artifact_root = report_path.parent
    artifact_path = artifact_root / replay["artifact_path"]
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact_fixture(), indent=2), encoding="utf-8")
    return _render_benchmarks(
        retrieval_path,
        answers_path,
        compressed_path,
        graph_receipt=replay,
        snapshot_path=snapshot_path,
        artifact_root=artifact_root,
    )


def test_renders_full_page(tmp_path: Path) -> None:
    retrieval = tmp_path / "retrieval.json"
    answers = tmp_path / "answers.json"
    retrieval.write_text(json.dumps(retrieval_fixture()))
    answers.write_text(json.dumps(answers_fixture()))
    page = render_benchmarks(retrieval, answers)
    assert "full_deep" in page and "with_rerank" in page and "auto_routed" in page
    assert "1.00 [0.90, 1.00]" in page  # CI formatting
    assert "v0.2-demo" in page  # snapshot name
    assert "abc1234" in page  # commit
    assert "gemini-embedding-001@1536" in page
    assert "make benchmark" in page  # reproduction command
    assert "groundedness" in page  # answers table present
    assert "small" in page.lower()  # small-sample honesty
    assert "76 extracted entities" in page
    assert "67 extracted entities" not in page
    assert "10% on other counts" in page
    assert "named, disposable PostgreSQL database" in page
    assert "Select a disposable database for that preflight" in page
    assert "leave development corpora intact" in page


def test_the_renderer_names_the_committed_strict_graph_replay(tmp_path: Path) -> None:
    """The page says which graph was replayed and that no live draw leaked in."""
    page = render_benchmarks(
        _write(tmp_path, "retrieval", retrieval_fixture()),
        _write(tmp_path, "answers", answers_fixture()),
    )

    assert "strict replay" in page.lower()
    assert artifact_sha256() in page
    assert "0 live extraction calls" in page


def test_renders_without_answers(tmp_path: Path) -> None:
    retrieval = tmp_path / "retrieval.json"
    retrieval.write_text(json.dumps(retrieval_fixture()))
    page = render_benchmarks(retrieval, None)
    assert "full_deep" in page
    assert "groundedness" not in page


def test_includes_calibration_when_present(tmp_path: Path) -> None:
    retrieval = tmp_path / "retrieval.json"
    answers_dir = tmp_path / "answers-run"
    answers_dir.mkdir()
    answers = answers_dir / "report.json"
    retrieval.write_text(json.dumps(retrieval_fixture()))
    answers.write_text(json.dumps(answers_fixture()))
    (answers_dir / "calibration.json").write_text(
        json.dumps(
            {
                "matched_n": 10,
                "unmatched_label_ids": [],
                "dimensions": {
                    "groundedness": {
                        "kappa": 1.0,
                        "n": 10,
                        "exact_agreement": 1.0,
                        "band": "almost perfect",
                        "matrix": [[0, 0, 0], [0, 0, 0], [0, 0, 10]],
                    }
                },
            }
        )
    )
    page = render_benchmarks(retrieval, answers)
    assert "kappa" in page.lower()
    assert "1.00" in page


def compressed_fixture(*, quality_holds: bool) -> dict:
    """A second answers run, paired against `answers_fixture` on the same set."""
    scores = (
        {"groundedness": 2.0, "correctness": 1.6}
        if quality_holds
        else {
            "groundedness": 1.6,
            "correctness": 1.1,
        }
    )
    return {
        "kind": "answers",
        "git_commit": "abc1234",
        "snapshot": "v0.2-demo",
        "provenance": PROVENANCE,
        "corpus": {"documents": 5, "chunks": 34},
        "summary": {
            "n": 10.0,
            "graded": 10.0,
            "failed": 0.0,
            "prompt_tokens_before_median": 1280.0,
            "prompt_tokens_after_median": 378.0,
        },
        "summary_ci": {
            name: {"mean": value, "lo": value - 0.5, "hi": 2.0, "n": 10.0}
            for name, value in scores.items()
        },
        "config": {"compression": True},
        "records": [{"compression_dropped_count": 61, "compression_failure_count": 0}],
    }


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    directory = tmp_path / name
    directory.mkdir()
    (directory / "report.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory


def test_a_failing_compression_gate_is_reported_as_failing(tmp_path: Path) -> None:
    """The whole point of the gate: a token saving alone must not read as a win."""
    page = render_benchmarks(
        _write(tmp_path, "retrieval", retrieval_fixture()),
        _write(tmp_path, "answers", answers_fixture()),
        _write(tmp_path, "compressed", compressed_fixture(quality_holds=False)),
    )

    assert "## Contextual compression: the paired gate" in page
    assert "the gate does not hold" in page
    assert "70% lower" in page, "the token saving is still reported"
    assert "Sources dropped by the relevance floor: 61" in page
    assert "no longer support its default" in page


def test_a_holding_compression_gate_says_so(tmp_path: Path) -> None:
    page = render_benchmarks(
        _write(tmp_path, "retrieval", retrieval_fixture()),
        _write(tmp_path, "answers", answers_fixture()),
        _write(tmp_path, "compressed", compressed_fixture(quality_holds=True)),
    )

    assert "the gate holds" in page
    assert "Compression defaults on" in page
    assert "THIS corpus only" in page


def test_the_compression_section_is_absent_without_a_paired_run(tmp_path: Path) -> None:
    page = render_benchmarks(
        _write(tmp_path, "retrieval", retrieval_fixture()),
        _write(tmp_path, "answers", answers_fixture()),
    )
    assert "Contextual compression" not in page


def test_a_missing_resolved_entities_condition_is_explained(tmp_path: Path) -> None:
    """Absent because the corpus has nothing to resolve, not because it was skipped."""
    page = render_benchmarks(
        _write(tmp_path, "retrieval", retrieval_fixture()),
        _write(tmp_path, "answers", answers_fixture()),
    )
    assert "missing `resolved_entities` row records the outcome" in page


# --- which report is which ---------------------------------------------------
#
# F-026 in the 2026-08-29 documentation route audit. `make benchmark` created
# the uncompressed report, created the compressed one, then calibrated the
# uncompressed one, which updated that directory's modification time. The
# `ls -td` selectors that followed therefore handed the compressed report in as
# `--answers` and the uncompressed one as `--answers-compressed`.
#
# The published page then used the compressed run as the ordinary judged-answer
# table, reversed the compression columns into "1318 to 1318, 0% lower", still
# claimed the gate held, and dropped calibration because it sat beside a report
# nothing was pointing at any more.
#
# Roles are now read from each report's own configuration, and the renderer
# refuses a pair that does not make sense.

MAKEFILE = Path(__file__).parents[2] / "Makefile"


def _answers_run(root: Path, name: str, *, compressed: bool) -> Path:
    payload = compressed_fixture(quality_holds=True) if compressed else answers_fixture()
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "report.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory


def test_roles_survive_calibration_touching_the_older_directory(tmp_path: Path) -> None:
    """The exact sequence the audit ran: calibrate, then select."""
    runs = tmp_path / "eval_results"
    uncompressed = _answers_run(runs, "20260829-174654-answers", compressed=False)
    compressed = _answers_run(runs, "20260829-174908-answers", compressed=True)

    # Calibration writes into the uncompressed directory, so it becomes the
    # most recently modified. This is what reversed the roles.
    (uncompressed / "calibration.json").write_text("{}", encoding="utf-8")
    os.utime(uncompressed, (2_000_000_000, 2_000_000_000))
    os.utime(compressed, (1_000_000_000, 1_000_000_000))
    assert uncompressed.stat().st_mtime > compressed.stat().st_mtime

    selected_uncompressed, selected_compressed = select_answer_reports(runs)

    assert selected_uncompressed == uncompressed
    assert selected_compressed == compressed


def test_selection_prefers_the_newest_run_of_each_role(tmp_path: Path) -> None:
    runs = tmp_path / "eval_results"
    _answers_run(runs, "20260101-000000-answers", compressed=False)
    _answers_run(runs, "20260101-000001-answers", compressed=True)
    newest_uncompressed = _answers_run(runs, "20260829-174654-answers", compressed=False)
    newest_compressed = _answers_run(runs, "20260829-174908-answers", compressed=True)

    assert select_answer_reports(runs) == (newest_uncompressed, newest_compressed)


def test_selection_refuses_when_a_role_is_missing(tmp_path: Path) -> None:
    runs = tmp_path / "eval_results"
    _answers_run(runs, "20260829-174654-answers", compressed=False)

    with pytest.raises(ReportRoleError, match="compressed"):
        select_answer_reports(runs)


def test_reversed_roles_are_refused(tmp_path: Path) -> None:
    """The audit's exact failure: the two reports handed over the wrong way."""
    with pytest.raises(ReportRoleError, match="compression"):
        render_benchmarks(
            _write(tmp_path, "retrieval", retrieval_fixture()),
            _write(tmp_path, "answers", compressed_fixture(quality_holds=True)),
            _write(tmp_path, "compressed", answers_fixture()),
        )


def test_the_same_report_twice_is_refused(tmp_path: Path) -> None:
    both = _write(tmp_path, "answers", answers_fixture())
    with pytest.raises(ReportRoleError):
        render_benchmarks(_write(tmp_path, "retrieval", retrieval_fixture()), both, both)


def test_a_report_with_no_declared_role_is_refused(tmp_path: Path) -> None:
    """A report that does not say what it is cannot be assigned a role."""
    unlabelled = answers_fixture()
    unlabelled.pop("config")
    with pytest.raises(ReportRoleError, match="does not record"):
        render_benchmarks(
            _write(tmp_path, "retrieval", retrieval_fixture()),
            _write(tmp_path, "answers", unlabelled),
            _write(tmp_path, "compressed", compressed_fixture(quality_holds=True)),
        )


def test_the_gate_cannot_claim_a_hold_when_tokens_do_not_fall(tmp_path: Path) -> None:
    """Quality holding is half the gate. The page claimed a hold on one half."""
    flat = compressed_fixture(quality_holds=True)
    flat["summary"]["prompt_tokens_before_median"] = 1318.0
    flat["summary"]["prompt_tokens_after_median"] = 1318.0

    page = render_benchmarks(
        _write(tmp_path, "retrieval", retrieval_fixture()),
        _write(tmp_path, "answers", answers_fixture()),
        _write(tmp_path, "compressed", flat),
    )

    assert "the gate holds" not in page, "0% lower is not a token saving"
    assert "the gate does not hold" in page


def test_calibration_is_read_from_the_report_passed_as_the_ordinary_run(
    tmp_path: Path,
) -> None:
    answers = _write(tmp_path, "answers", answers_fixture())
    (answers / "calibration.json").write_text(
        json.dumps({"kappa": {"groundedness": 0.61}, "n": 10}), encoding="utf-8"
    )

    page = render_benchmarks(
        _write(tmp_path, "retrieval", retrieval_fixture()),
        answers,
        _write(tmp_path, "compressed", compressed_fixture(quality_holds=True)),
    )

    assert "Judge calibration" in page


def test_the_benchmark_target_does_not_pick_reports_by_modification_time() -> None:
    """Calibration updates an mtime. Selection must not depend on one."""
    recipe = MAKEFILE.read_text(encoding="utf-8").partition("\nbenchmark:")[2].partition("\n\n")[0]
    assert "ls -td" not in recipe, (
        "the benchmark target still selects report directories by modification time"
    )
    assert "select-answer-roles" in recipe, "roles should come from the reports themselves"
