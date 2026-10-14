"""The manifest linter, one test per thing it is supposed to catch.

Two of these are the reason the linter does not simply call `load_manifest`.
`load_manifest` raises on the first malformed line, so it can report exactly one
problem per run; and `CorpusEntry` normalizes an unrecognized `license_class` to
`unknown`, which is correct fail-closed behaviour at ingestion and erases the
mistake here. `test_a_bad_line_does_not_hide_the_lines_after_it` and
`test_an_unrecognized_license_class_is_an_error` pin both.
"""

from pathlib import Path

from typer.testing import CliRunner

from sci_rag.cli.main import app
from sci_rag.ingest.manifest import LintReport, lint_manifest

REPO_ROOT = Path(__file__).parents[2]
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "300"})


def _manifest(tmp_path: Path, *lines: str, files: tuple[str, ...] = ("paper.pdf",)) -> Path:
    for name in files:
        (tmp_path / name).write_bytes(b"")
    path = tmp_path / "manifest.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _codes(report: LintReport) -> list[str]:
    return [finding.code for finding in report.findings]


def test_a_clean_manifest_reports_nothing(tmp_path: Path) -> None:
    path = _manifest(tmp_path, '{"path": "paper.pdf", "title": "A Paper"}')
    report = lint_manifest(path)

    assert report.ok
    assert report.findings == []
    assert report.entry_count == 1


def test_the_shipped_demo_manifest_is_clean() -> None:
    """The linter's tiers are only trustworthy if the corpus the kit ships passes."""
    report = lint_manifest(REPO_ROOT / "data" / "demo" / "manifest.jsonl")

    assert report.findings == [], f"demo manifest should lint clean, got {report.findings}"
    assert report.entry_count == 5


def test_comments_and_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        "# the demo manifest opens with a comment block",
        "",
        '{"path": "paper.pdf", "title": "A Paper"}',
        "   ",
    )
    report = lint_manifest(path)

    assert report.ok
    assert report.entry_count == 1


def test_a_missing_file_is_an_error(tmp_path: Path) -> None:
    path = _manifest(tmp_path, '{"path": "gone.pdf", "title": "Missing"}')
    report = lint_manifest(path)

    assert _codes(report) == ["missing_file"]
    assert not report.ok


def test_paths_resolve_against_the_manifests_own_directory(tmp_path: Path) -> None:
    """Same rule as `load_manifest`, so linting from elsewhere gives the same verdict."""
    nested = tmp_path / "corpus"
    nested.mkdir()
    (nested / "paper.pdf").write_bytes(b"")
    path = nested / "manifest.jsonl"
    path.write_text('{"path": "paper.pdf", "title": "A Paper"}\n', encoding="utf-8")

    assert lint_manifest(path).ok


def test_a_duplicate_path_names_the_line_that_claimed_it(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        '{"path": "paper.pdf", "title": "First"}',
        '{"path": "./paper.pdf", "title": "Second, same file"}',
    )
    report = lint_manifest(path)

    assert _codes(report) == ["duplicate_path"]
    assert report.findings[0].line == 2
    assert "line 1" in report.findings[0].message


def test_an_unrecognized_license_class_is_an_error(tmp_path: Path) -> None:
    """`CorpusEntry` would quietly demote this to `unknown`; the linter says so."""
    path = _manifest(
        tmp_path, '{"path": "paper.pdf", "title": "A Paper", "license_class": "CC-BY-NC-ND-4.0"}'
    )
    report = lint_manifest(path)

    assert _codes(report) == ["unknown_license_class"]
    assert "'unknown'" in report.findings[0].message


def test_a_known_license_alias_is_not_an_error(tmp_path: Path) -> None:
    """`cc-by` is a spelling of `open_commercial`, not a mistake."""
    path = _manifest(
        tmp_path, '{"path": "paper.pdf", "title": "A Paper", "license_class": "cc-by"}'
    )

    assert lint_manifest(path).ok


def test_declaring_unknown_explicitly_is_not_an_error(tmp_path: Path) -> None:
    """`unknown` is the documented answer for "nobody has said"; flagging it would be noise."""
    path = _manifest(
        tmp_path, '{"path": "paper.pdf", "title": "A Paper", "license_class": "unknown"}'
    )

    assert lint_manifest(path).ok


def test_a_missing_title_is_an_error(tmp_path: Path) -> None:
    path = _manifest(tmp_path, '{"path": "paper.pdf"}')
    report = lint_manifest(path)

    assert _codes(report) == ["missing_title"]
    assert "paper" in report.findings[0].message


def test_a_blank_title_is_an_error(tmp_path: Path) -> None:
    path = _manifest(tmp_path, '{"path": "paper.pdf", "title": "   "}')

    assert _codes(lint_manifest(path)) == ["missing_title"]


def test_an_unknown_key_warns_without_failing(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path, '{"path": "paper.pdf", "title": "A Paper", "lisence_class": "public"}'
    )
    report = lint_manifest(path)

    assert _codes(report) == ["unknown_key"]
    assert report.warnings and not report.errors
    assert report.ok, "an unknown key is forward compatibility, not a failure"
    assert "lisence_class" in report.findings[0].message


def test_an_unsupported_file_type_is_an_error(tmp_path: Path) -> None:
    """Not in the issue's list, but it fails ingestion as surely as a missing file."""
    path = _manifest(
        tmp_path,
        '{"path": "notes.docx", "title": "Wrong Type"}',
        files=("notes.docx",),
    )
    report = lint_manifest(path)

    assert _codes(report) == ["unsupported_file_type"]
    assert ".pdf" in report.findings[0].message


def test_an_invalid_field_type_is_an_error(tmp_path: Path) -> None:
    path = _manifest(tmp_path, '{"path": "paper.pdf", "title": "A Paper", "year": "last year"}')
    report = lint_manifest(path)

    assert _codes(report) == ["invalid_field"]
    assert report.findings[0].message.startswith("year:")


def test_a_line_that_is_not_an_object_is_an_error(tmp_path: Path) -> None:
    path = _manifest(tmp_path, '["paper.pdf"]')
    report = lint_manifest(path)

    assert _codes(report) == ["not_an_object"]
    assert "list" in report.findings[0].message


def test_a_bad_line_does_not_hide_the_lines_after_it(tmp_path: Path) -> None:
    """`load_manifest` raises on line 1 and never sees line 2. A linter has to."""
    path = _manifest(
        tmp_path,
        "{not json",
        '{"path": "gone.pdf", "title": "Missing"}',
    )
    report = lint_manifest(path)

    assert _codes(report) == ["invalid_json", "missing_file"]
    assert [finding.line for finding in report.findings] == [1, 2]


def test_every_finding_carries_a_line_number(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        "# header",
        '{"path": "gone.pdf", "title": "Missing"}',
        '{"path": "paper.pdf"}',
    )
    report = lint_manifest(path)

    assert [(f.line, f.code) for f in report.findings] == [
        (2, "missing_file"),
        (3, "missing_title"),
    ]


def test_the_cli_exits_zero_and_says_so_on_a_clean_manifest(tmp_path: Path) -> None:
    path = _manifest(tmp_path, '{"path": "paper.pdf", "title": "A Paper"}')
    result = runner.invoke(app, ["manifest", "lint", str(path)])

    assert result.exit_code == 0, result.output
    assert "1 entry checked" in result.output
    assert "ready to ingest" in result.output


def test_the_cli_exits_one_and_lists_the_problems(tmp_path: Path) -> None:
    path = _manifest(tmp_path, '{"path": "gone.pdf", "title": "Missing"}')
    result = runner.invoke(app, ["manifest", "lint", str(path)])

    assert result.exit_code == 1
    assert "missing_file" in result.output
    assert "1 error(s)" in result.output


def test_the_cli_does_not_fail_a_manifest_for_a_warning_alone(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path, '{"path": "paper.pdf", "title": "A Paper", "lisence_class": "public"}'
    )
    result = runner.invoke(app, ["manifest", "lint", str(path)])

    assert result.exit_code == 0, result.output
    assert "unknown_key" in result.output
    assert "ready to ingest" in result.output


def test_the_cli_reports_a_manifest_that_is_not_there(tmp_path: Path) -> None:
    result = runner.invoke(app, ["manifest", "lint", str(tmp_path / "nope.jsonl")])

    assert result.exit_code == 1
    assert "No manifest at" in result.output
