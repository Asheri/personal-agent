"""The report is not a gate, and `--strict` is the opt-in that makes it one.

The exit code is the whole contract with CI, and it has two failure modes that
are opposite and both silent. Exiting 1 by default turns a report into a build
break for every corpus with an undeclared document. Exiting 0 under `--strict`
makes the CI check decorative: it runs, it passes, and it never once tells you
your rights posture slipped. These pin both, with no database.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from sci_rag.cli.main import app
from sci_rag.license_report import (
    ClassCount,
    LicenseReport,
    UndeclaredDocument,
    report_payload,
)
from sci_rag.licensing import LICENSE_CLASSES

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "300"})


def _report(*, undeclared: int) -> LicenseReport:
    counts = {"public": 3, "restricted": 1, "unknown": undeclared}
    total = sum(counts.values())
    report = LicenseReport(total_documents=total, total_chunks=total * 2)
    report.by_class = [
        ClassCount(
            license_class=license_class,
            documents=counts.get(license_class, 0),
            chunks=counts.get(license_class, 0) * 2,
            document_share=round(100.0 * counts.get(license_class, 0) / total, 1),
            chunk_share=round(100.0 * counts.get(license_class, 0) / total, 1),
        )
        for license_class in LICENSE_CLASSES
    ]
    report.undeclared = [
        UndeclaredDocument(id=f"d{i}", title=f"Undeclared {i}", source="web")
        for i in range(undeclared)
    ]
    report.undeclared_by_source = {"web": undeclared} if undeclared else {}
    return report


@pytest.fixture()
def stub(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Swap the database out; the exit-code contract does not need one."""
    from sci_rag import license_report as module
    from sci_rag.cli import main as cli_main

    async def _no_db() -> None:
        return None

    monkeypatch.setattr(cli_main, "_check_db", _no_db)

    def _install(report: LicenseReport) -> None:
        async def _build(_factory):  # type: ignore[no-untyped-def]
            return report

        monkeypatch.setattr(module, "build_license_report", _build)

    return _install


def test_a_clean_corpus_exits_zero_and_says_so(stub) -> None:  # type: ignore[no-untyped-def]
    stub(_report(undeclared=0))

    result = runner.invoke(app, ["corpus", "license-report"])

    assert result.exit_code == 0
    assert "Every document has a recorded license class" in result.output


def test_undeclared_documents_do_not_fail_the_report_by_default(stub) -> None:  # type: ignore[no-untyped-def]
    """A report that breaks the build is a report nobody runs."""
    stub(_report(undeclared=2))

    result = runner.invoke(app, ["corpus", "license-report"])

    assert result.exit_code == 0
    assert "Undeclared rights" in result.output


def test_strict_turns_undeclared_documents_into_a_failure(stub) -> None:  # type: ignore[no-untyped-def]
    stub(_report(undeclared=2))

    result = runner.invoke(app, ["corpus", "license-report", "--strict"])

    assert result.exit_code == 1


def test_strict_still_passes_when_every_right_is_recorded(stub) -> None:  # type: ignore[no-untyped-def]
    """Otherwise the CI check is decorative: it can never distinguish the two."""
    stub(_report(undeclared=0))

    result = runner.invoke(app, ["corpus", "license-report", "--strict"])

    assert result.exit_code == 0


def test_strict_and_json_compose(stub) -> None:  # type: ignore[no-untyped-def]
    """CI wants the exit code AND the artifact from one run."""
    stub(_report(undeclared=1))

    result = runner.invoke(app, ["corpus", "license-report", "--json", "--strict"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["undeclared"]["count"] == 1


def test_json_output_is_parseable_and_complete(stub) -> None:  # type: ignore[no-untyped-def]
    stub(_report(undeclared=2))

    result = runner.invoke(app, ["corpus", "license-report", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["total_documents"] == 6
    assert len(payload["by_class"]) == len(LICENSE_CLASSES)
    assert len(payload["undeclared"]["documents"]) == 2


def test_the_table_truncates_a_long_list_and_says_how_many_it_left_out(stub) -> None:  # type: ignore[no-untyped-def]
    """Silent truncation would read as "that is all of them"."""
    from sci_rag.cli.main import _UNDECLARED_TABLE_LIMIT

    stub(_report(undeclared=_UNDECLARED_TABLE_LIMIT + 5))

    result = runner.invoke(app, ["corpus", "license-report"])

    assert result.exit_code == 0
    assert "and 5 more" in result.output
    assert "--json" in result.output


def test_json_never_truncates_what_the_table_did(stub) -> None:  # type: ignore[no-untyped-def]
    from sci_rag.cli.main import _UNDECLARED_TABLE_LIMIT

    count = _UNDECLARED_TABLE_LIMIT + 5
    stub(_report(undeclared=count))

    result = runner.invoke(app, ["corpus", "license-report", "--json"])

    assert len(json.loads(result.stdout)["undeclared"]["documents"]) == count


def test_the_output_explains_that_unknown_is_fail_closed(stub) -> None:  # type: ignore[no-untyped-def]
    """The number is useless without knowing that `unknown` means excluded."""
    stub(_report(undeclared=1))

    result = runner.invoke(app, ["corpus", "license-report"])

    assert "never assumed safe" in result.output
    assert "excluded unless the scope names `unknown` explicitly" in result.output


def test_the_payload_matches_what_the_command_prints(stub) -> None:  # type: ignore[no-untyped-def]
    """`--json` and the table read the same report, not two computations."""
    report = _report(undeclared=3)
    stub(report)

    result = runner.invoke(app, ["corpus", "license-report", "--json"])

    assert json.loads(result.stdout) == report_payload(report)
