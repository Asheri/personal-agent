from __future__ import annotations

from pathlib import Path

from sci_rag.campaigns.state import CampaignState


def test_campaign_state_round_trips_append_only_records(tmp_path: Path) -> None:
    path = tmp_path / "campaign" / "state.jsonl"
    state = CampaignState(path)

    state.append(
        doi="10.7717/peerj.4375",
        status="discovered",
        payload={"title": "The state of OA"},
    )
    state.append(
        doi="10.7717/peerj.4375",
        status="resolved",
        payload={"oa_status": "gold"},
    )

    loaded = CampaignState(path)
    assert [record.status for record in loaded.records] == ["discovered", "resolved"]
    assert loaded.latest["10.7717/peerj.4375"].status == "resolved"
    assert loaded.processed_dois == {"10.7717/peerj.4375"}


def test_campaign_state_tolerates_only_a_truncated_final_line(tmp_path: Path) -> None:
    path = tmp_path / "state.jsonl"
    state = CampaignState(path)
    state.append(doi="10.7717/peerj.4375", status="discovered")
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"doi":"10.1038/s41586')

    loaded = CampaignState(path)

    assert len(loaded.records) == 1
    assert loaded.truncated_final_line is True

    loaded.append(doi="10.1038/s41586-020-2649-2", status="discovered")
    recovered = CampaignState(path)
    assert [record.doi for record in recovered.records] == [
        "10.7717/peerj.4375",
        "10.1038/s41586-020-2649-2",
    ]
    assert recovered.truncated_final_line is False


def test_campaign_state_repairs_a_complete_final_record_without_newline(tmp_path: Path) -> None:
    path = tmp_path / "state.jsonl"
    state = CampaignState(path)
    state.append(doi="10.7717/peerj.4375", status="discovered")
    path.write_bytes(path.read_bytes().rstrip(b"\n"))

    loaded = CampaignState(path)
    loaded.append(doi="10.1038/s41586-020-2649-2", status="discovered")

    recovered = CampaignState(path)
    assert [record.doi for record in recovered.records] == [
        "10.7717/peerj.4375",
        "10.1038/s41586-020-2649-2",
    ]


def test_campaign_state_normalizes_dois_and_skips_processed_candidates(tmp_path: Path) -> None:
    state = CampaignState(tmp_path / "state.jsonl")
    state.append(doi="HTTPS://DOI.ORG/10.7717/PEERJ.4375", status="discovered")

    assert state.is_processed("10.7717/peerj.4375")
    assert not state.is_processed("10.1038/s41586-020-2649-2")
