"""Adapt retained raw hits for the standard eval diff without inventing a rerun."""

import argparse
import json
from pathlib import Path

from sci_rag.evals.report import domain_digest


def render(directory: Path) -> None:
    samples = {
        phase: json.loads((directory / (phase + ".json")).read_text(encoding="utf-8"))
        for phase in ["before", "after"]
    }
    assert samples["before"]["corpus_sha256"] == samples["after"]["corpus_sha256"]
    for phase, data in samples.items():
        records = []
        for index, row in enumerate(data["results"]):
            expected = {key.zfill(32) for key in row["expected"]}
            ranks = [rank for rank, key in enumerate(row["hits"], 1) if key in expected]
            records.append(
                dict(
                    question_id=f"boundary-{index:03}",
                    query=row["query"],
                    first_relevant_rank=min(ranks) if ranks else None,
                    relevant_ranks=ranks,
                    target_document_recall=row["recall"],
                    hit_at_5=bool(ranks and min(ranks) <= 5),
                    hit_at_10=bool(ranks and min(ranks) <= 10),
                    retrieved=len(row["hits"]),
                    degraded_stages=[],
                )
            )
        payload = dict(
            kind="retrieval",
            snapshot="retained-raw-keyword-boundary-" + phase,
            corpus=dict(
                documents=len(data["fixtures"]),
                chunks=len(data["fixtures"]),
                content_sha256=data["corpus_sha256"],
            ),
            ground_truth=dict(drafted=24, reviewed=0),
            provenance=dict(
                embedding="not used; keyword-only",
                models={},
                domain_digest=domain_digest(Path(__file__).resolve().parents[1] / "domain"),
                decoding={},
            ),
            configs=[
                dict(
                    name="keyword_only",
                    description="Derived only from retained measured keyword hits",
                    records=records,
                    metrics=dict(
                        target_document_recall=sum(row["recall"] for row in data["results"])
                        / len(data["results"])
                    ),
                )
            ],
            note="This adaptation is not a new retrieval or model run. Standard first-hit metrics can remain unchanged even while target-document coverage improves; use the raw recall matrix for that distinction.",
        )
        (directory / (phase + "-eval-report.json")).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    render(parser.parse_args().directory)
