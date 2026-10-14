from __future__ import annotations

import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from sci_rag.campaigns.discovery import CandidateWork
from sci_rag.campaigns.state import CampaignState

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "campaigns"


def test_campaign_build_dry_run_cli_reports_licenses_without_pdfs(tmp_path: Path) -> None:
    payload = (FIXTURES / "unpaywall_cc_by.json").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        root = tmp_path / "campaigns"
        state = CampaignState(root / "dry-run" / "state.jsonl")
        work = CandidateWork(
            doi="10.7717/peerj.4375",
            title="The state of OA",
            source="crossref",
        )
        state.append(
            doi=work.doi,
            status="discovered",
            payload={
                "doi": work.doi,
                "title": work.title,
                "year": None,
                "authors": [],
                "journal": None,
                "oa_status_hint": None,
                "license_hint": None,
                "source": work.source,
            },
        )
        doi_file = tmp_path / "seeds.txt"
        doi_file.write_text(f"{work.doi}\n", encoding="utf-8")
        env = os.environ.copy()
        env["SCI_RAG_UNPAYWALL_BASE_URL"] = f"http://127.0.0.1:{server.server_port}/v2"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sci_rag.cli.main",
                "campaign",
                "build",
                "--doi-file",
                str(doi_file),
                "--name",
                "dry-run",
                "--mailto",
                "researcher@example.org",
                "--dry-run",
                "--campaign-root",
                str(root),
            ],
            cwd=Path(__file__).parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert "Dry run" in result.stdout
    assert "open_commercial=1" in result.stdout
    assert "1 resolved" in result.stdout
    assert not (root / "dry-run" / "pdfs").exists()
    assert not (root / "dry-run" / "corpus.jsonl").exists()
    assert CampaignState(root / "dry-run" / "state.jsonl").latest[work.doi].status == "resolved"
