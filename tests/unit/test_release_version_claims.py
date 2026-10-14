"""What the documentation claims about the version a reader can install.

F-002: the quickstart said "Tested with v0.3" and told a reader to
`pipx install sci-rag-kit` and then run `sci-rag new`. Published v0.3.0 has no
`new` subcommand, so the flagship route stopped at `No such command 'new'`.
The command existed on `main`, and nothing connected the badge on the page to
the version that actually shipped.

Two things follow from that, and both are checkable. Every page that states a
tested version has to state the same one, and it has to be the version this
tree packages. And the entry point the public pages lead with has to be the
one the generated CLI reference documents, since that reference is written
from the command tree rather than from prose.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: The meta strip's version claim, as `docs/STYLE.md` requires every tutorial
#: and how-to to carry.
TESTED_WITH = re.compile(r"<strong>Tested with</strong>v(?P<version>[0-9]+\.[0-9]+(?:\.[0-9]+)?)")


def _packaged_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _claims() -> dict[str, str]:
    found: dict[str, str] = {}
    for page in sorted((ROOT / "docs").rglob("*.md")):
        if "planning" in page.parts:
            continue
        match = TESTED_WITH.search(page.read_text(encoding="utf-8"))
        if match:
            found[page.name] = match.group("version")
    return found


def test_every_tested_version_claim_matches_what_this_tree_packages() -> None:
    """A badge naming a release that behaves differently is what F-002 was."""
    packaged = _packaged_version()
    major_minor = ".".join(packaged.split(".")[:2])

    offenders = {
        page: claimed
        for page, claimed in _claims().items()
        if claimed not in (packaged, major_minor)
    }

    assert offenders == {}, (
        f"pages claim a version this tree does not package ({packaged}): {offenders}"
    )


def test_the_site_footer_names_the_same_version() -> None:
    """The claim sits in the site footer, so it is on every page at once.

    `mkdocs.yml` holds the string and `partials/copyright.html` renders it, so
    this is the one place a release has to bump besides `pyproject.toml`.
    """
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    declared = re.search(r"^  package_version: \"(?P<version>[^\"]+)\"", config, re.MULTILINE)

    assert declared is not None, "mkdocs.yml should set extra.package_version"
    assert declared.group("version") == _packaged_version()

    footer = (ROOT / "docs" / "overrides" / "partials" / "copyright.html").read_text(
        encoding="utf-8"
    )
    assert "config.extra.package_version" in footer, "the footer should render that version"
    assert "https://pypi.org/project/sci-rag-kit/" in footer, (
        "the install route should link to the artefact it installs"
    )


def test_the_public_pages_and_the_generated_reference_agree_on_the_entry_point() -> None:
    """`sci-rag new` is what the front door leads with, so it has to exist."""
    reference = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    assert "| `sci-rag new` |" in reference

    for surface in ("README.md", "docs/index.md", "docs/quickstart.md"):
        page = (ROOT / surface).read_text(encoding="utf-8")
        assert "pipx install sci-rag-kit" in page, surface
        assert "sci-rag new" in page, surface


def test_release_validation_runs_the_public_two_command_route() -> None:
    """The route F-002 broke is the one a release has to prove.

    Installing the wheel and running `--help` cannot catch it: `sci-rag new`
    fetches the template at its own tag, so the failure only shows up when the
    documented pair actually runs from a clean install.
    """
    import yaml

    workflow = yaml.load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    # Quotes around the interpolated bin directory sit between the executable
    # and the subcommand, so the shape is compared rather than the literal.
    scripts = re.sub(
        r"[\"']", "", "\n".join(step.get("run", "") for step in workflow["jobs"]["verify"]["steps"])
    )

    assert "pipx install" in scripts, "the public route starts at pipx, not at uv pip"
    assert "PIPX_HOME" in scripts, "a clean pipx home, so a local install cannot mask a failure"
    assert "sci-rag new --defaults" in scripts, "the wizard has to actually run"
    # The existence probe asks the CLI, and does not read the rendered help
    # table. The first attempt grepped that table for " new " and failed on a
    # runner even though the command was there: Rich decides the layout from
    # terminal detection, so the check was testing the renderer. Typer exits 2
    # with "No such command" when a subcommand is missing, which is F-002's
    # own symptom and does not depend on how anything is drawn.
    assert "sci-rag new --help" in scripts, "probe the command, not its help table"
    assert "grep -q  new " not in scripts


def test_release_downloaders_have_nonpublishing_pull_request_evidence() -> None:
    """The tag-only release downloaders need an equivalent PR smoke path."""
    import yaml

    ci = yaml.load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    release = yaml.load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    ci_downloaders = [
        step["uses"]
        for step in ci["jobs"]["docs"]["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    ]
    release_downloaders = [
        step["uses"]
        for job_name in ("testpypi", "pypi")
        for step in release["jobs"][job_name]["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    ]

    assert ci_downloaders == ["actions/download-artifact@v8"]
    assert release_downloaders == [
        "actions/download-artifact@v8",
        "actions/download-artifact@v8",
    ]
