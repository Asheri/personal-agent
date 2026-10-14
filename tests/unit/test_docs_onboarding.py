"""The public onboarding path recommends one command before listing alternatives."""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from platform_checks import posix_shell, windows_acl_snapshot

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_readme_and_homepage_lead_with_pipx_and_the_main_cli() -> None:
    readme_lead = _read("README.md").partition("## Components")[0]
    homepage = _read("docs/index.md")
    start = homepage.partition("## Start a new project")[2].partition(
        "<!-- END KIT ONBOARDING -->"
    )[0]

    assert "pipx install sci-rag-kit" in readme_lead
    assert "`sci-rag new`" in readme_lead
    assert "`sci-rag-new`" not in readme_lead

    assert "$ pipx install sci-rag-kit\n$ sci-rag new" in start
    assert "quickstart.md#other-entrypoints" in start
    assert "Install with pipx, the GitHub template, or a clone." not in homepage

    # The install route names pipx from the site footer now, so it states the
    # same thing on every page rather than only on the home page.
    footer = _read("docs/overrides/partials/copyright.html")
    assert "Install with pipx" in footer


def test_quickstart_puts_the_wizard_before_all_other_routes() -> None:
    quickstart = _read("docs/quickstart.md")
    wizard_at = quickstart.index("### The setup wizard")
    alternatives_at = quickstart.index("### Other entrypoints")
    wizard = quickstart[wizard_at:alternatives_at]
    alternatives = quickstart[alternatives_at:].partition("## 2.")[0]

    assert wizard_at < alternatives_at
    assert "$ pipx install sci-rag-kit\n$ sci-rag new" in wizard
    assert "git clone" not in wizard
    assert "git clone" in alternatives
    assert "Use this template" in alternatives
    assert "`sci-rag init`" in alternatives
    assert "dev container" in alternatives


def test_get_started_opens_with_the_install_and_wizard_route() -> None:
    page = _read("docs/get-started.md")
    opening = page.partition("# Getting started")[2].partition('<div class="srag-rows"')[0]

    assert "`pipx install sci-rag-kit`" in opening
    assert "`sci-rag new`" in opening
    assert "clean clone" not in opening

    assert "live template repository rather than a generator" not in page
    assert "generator configures the live template" in page
    assert "choose Offline" in page


def test_troubleshooting_explains_all_three_credential_recovery_choices() -> None:
    page = _read("docs/troubleshooting.md")
    credentials = page.partition("## A command needs LLM provider credentials")[2].partition(
        "## Retrieval is empty"
    )[0]

    assert "Try a different credential" in credentials
    assert "Switch to an AI Studio key" in credentials
    assert "Continue without a model" in credentials
    assert "keeps your chosen credential mode" in credentials
    assert "worked example ontology" in credentials


def test_generated_projects_strip_the_kit_onboarding_and_both_casts() -> None:
    from sci_rag.scaffold.apply import _strip_marked_regions

    stripped = _strip_marked_regions(_read("docs/index.md"))

    assert "pipx install sci-rag-kit" not in stripped
    assert "sci-rag-new.cast" not in stripped
    assert "sci-rag-new-advanced.cast" not in stripped
    assert "## What's in the kit?" in stripped


def test_current_guides_name_the_main_project_command() -> None:
    for path in (
        "docs/faq.md",
        "docs/bring-your-own-domain.md",
        "docs/choosing-sci-rag-kit.md",
    ):
        page = _read(path)

        assert "`sci-rag new`" in page, path
        assert "`sci-rag-new`" not in page, path

    readme = _read("README.md")
    assert "| `sci-rag new` |" in readme

    faq = _read("docs/faq.md")
    assert "**Use this template** or cloning" in faq
    assert "same appliers" in faq
    assert "All three leave you with the same tree" not in faq


def test_quick_mode_docs_distinguish_setup_decisions_from_credential_input() -> None:
    homepage = _read("docs/index.md")
    homepage_start = homepage.partition("## Start a new project")[2].partition(
        "<!-- END KIT ONBOARDING -->"
    )[0]
    quickstart = _read("docs/quickstart.md")
    quickstart_wizard = quickstart.partition("### The setup wizard")[2].partition(
        "### Other entrypoints"
    )[0]

    for section in (homepage_start, quickstart_wizard):
        assert re.search(r"LLM (?:provider )?credentials", section)
        assert "Offline" in section

    assert "six setup decisions" in quickstart_wizard
    assert "six setup decisions" not in homepage_start
    assert "The setup wizard will ask a series" in homepage_start
    assert "The wizard asks" not in homepage_start

    assert "holding down Enter" not in homepage_start
    assert "pressing Enter" not in _read("docs/faq.md")


def test_quickstart_documents_tty_conveniences_without_changing_defaults() -> None:
    quickstart = _read("docs/quickstart.md")
    wizard = quickstart.partition("### The setup wizard")[2].partition("### Other entrypoints")[0]

    assert "first supported environment manager found on `PATH`" in wizard
    assert "`--defaults` or an answers file" in wizard
    assert "`SCI_RAG_GOOGLE_API_KEY`" in wizard
    assert "`GOOGLE_API_KEY`" in wizard
    assert "without displaying its value" in wizard
    assert "masked" in wizard


def test_homepage_uses_the_requested_plain_language() -> None:
    homepage = _read("docs/index.md")

    assert "provides a blueprint for scientific RAG development" in homepage
    assert "Fully\nextensible and ready to serve over API and MCP." in homepage
    assert "## Configure around your domain" in homepage
    assert "[Project structure](get-started.md#project-structure)" in homepage
    assert "## Configure, do not code" not in homepage
    assert (
        "<figcaption>End-to-end RAG architecture that ships with Sci RAG Kit.</figcaption>"
        in homepage
    )


def test_checkout_setup_documents_modes_and_preflight_boundary() -> None:
    tutorial = _read("docs/bring-your-own-domain.md")
    setup = tutorial.partition("## Step 0: run the setup wizard")[2].partition(
        "## Step 1: collect your documents"
    )[0]

    assert "uv run sci-rag init --advanced" in setup
    assert "`--quick`" in setup
    assert "`--no-tty`" in setup
    assert "does not run the live credential check" in setup
    assert "pressing Enter" not in setup
    assert "| Setup area | Where to review it |" in tutorial
    assert "| Setup area | Quick | Advanced | Where it went |" not in tutorial

    drafting = tutorial.partition("## Drafting with a model")[2].partition(
        "## Offline: what you can prove without a model"
    )[0]
    assert "`sci-rag new` and `sci-rag init`" in drafting
    assert "Only `sci-rag new` checks the credential" in drafting


def test_advanced_only_project_choices_are_labeled_as_advanced() -> None:
    postgres = _read("docs/run-postgres.md")
    deploy = _read("docs/deploy-gcp.md")

    assert "`sci-rag new --advanced`" in postgres
    assert "`sci-rag new --advanced`" in deploy
    assert "Quick keeps the default" in postgres
    assert "Generated projects include the production Terraform module by default" in deploy


def test_troubleshooting_documents_prompt_and_preflight_escape_hatches() -> None:
    page = _read("docs/troubleshooting.md")
    normalized = " ".join(page.split())

    assert "`--no-tty`" in page
    assert "`NO_COLOR`" in page
    assert "`TERM=dumb`" in page
    assert "`--no-preflight`" in page
    assert "only available on `sci-rag new`" in normalized
    assert "does not validate the credential" in normalized
    assert "15-second deadline" in normalized
    assert "never prints the raw provider exception or credential value" in normalized


def test_current_records_describe_the_main_command_and_compatibility_alias() -> None:
    adr = _read("docs/adr/0007-interactive-project-generator.md")
    versioning = _read("docs/VERSIONING.md")
    roadmap = _read("docs/ROADMAP.md")

    assert "**Amended:** 2026-08-28" in adr
    assert "`sci-rag new` is the primary command" in adr
    assert "compatibility alias" in adr
    assert "probe/bin/sci-rag new --defaults" in versioning
    assert "probe/bin/sci-rag-new --help" in versioning
    assert "main `sci-rag new` command" in roadmap


def test_the_changelog_records_the_guided_onboarding_batch() -> None:
    """Anchored to the entries, not to the heading they sit under.

    This read from `## [Unreleased]` to `## [0.3.0]`, so it passed only while
    the batch was unreleased. Cutting 0.5.0 renamed that heading, the partition
    returned nothing, and every assertion below failed at once, describing a
    missing feature rather than a moved heading.

    The batch is what has to stay recorded. Which released section carries it
    is the release process's business.
    """
    unreleased = _read("CHANGELOG.md").partition("## [0.3.0]")[0]

    assert "`sci-rag new`" in unreleased
    assert "Quick and Advanced" in unreleased
    assert "credential preflight" in unreleased
    assert "plain numbered fallback" in unreleased
    assert "environment manager found on `PATH`" in unreleased
    assert "existing environment key" in unreleased
    assert "shared completion report" in unreleased


def test_wizard_environment_file_is_owner_readable() -> None:
    quickstart = _read("docs/quickstart.md")
    assert "owner-only mode `0600`" in quickstart


# --- the clone and template route creates the same file ----------------------
#
# F-031 in the 2026-08-29 documentation route audit: the wizard chmods its
# generated .env to 0600, but the clone and GitHub-template routes told the
# reader to `cp .env.example .env`, which inherits the public example's mode.
# In a clean clone under a normal umask that produced 0644, so every local
# user could read the key the next paragraph asks the reader to paste in.
#
# These tests run the documented sequence rather than reading it, because the
# only thing that settles a file mode question is a file.

ENV_SETUP_PAGES = ("docs/quickstart.md", "README.md")

# The sequence may only use commands that exist on every supported macOS and
# Linux shell. This is a portability guard, and it also keeps the test from
# executing anything surprising that lands in a documentation block later.
PORTABLE_COMMANDS = frozenset({"cp", "chmod", "install", "umask"})


def _env_file_commands(page: str) -> list[str]:
    """The documented commands that create `.env` from the example.

    Takes the command that reads `.env.example` plus every command
    immediately after it that still concerns `.env`, so a `chmod` on the next
    line is part of the sequence and an unrelated `make setup` is not.
    """
    for block in re.findall(r"^(?:```|~~~)[^\n]*\n(.*?)^(?:```|~~~)", page, re.DOTALL | re.M):
        lines = [
            line.removeprefix("$ ").strip()
            for line in block.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        starts = [index for index, line in enumerate(lines) if ".env.example" in line]
        if not starts:
            continue
        sequence = [lines[starts[0]]]
        for line in lines[starts[0] + 1 :]:
            if ".env" not in line:
                break
            sequence.append(line)
        return sequence
    return []


def _code_block(page: str, language: str) -> str:
    match = re.search(rf"```{language}\n(.*?)^```", page, re.DOTALL | re.MULTILINE)
    assert match is not None, f"the page has no {language} command block"
    return match.group(1)


@pytest.mark.parametrize("page", ENV_SETUP_PAGES)
def test_the_documented_clone_sequence_uses_portable_commands(page: str) -> None:
    commands = _env_file_commands(_read(page))
    assert commands, f"{page} no longer documents creating .env from the example"
    programs = {command.split()[0] for command in commands}
    assert programs <= PORTABLE_COMMANDS, (
        f"{page} creates .env with something that is not portable: {programs}"
    )


@pytest.mark.parametrize("page", ENV_SETUP_PAGES)
def test_the_documented_clone_sequence_produces_an_owner_only_file(
    page: str, tmp_path: Path
) -> None:
    """Run it in a scratch clone under a normal umask and stat the result."""
    example = tmp_path / ".env.example"
    example.write_text("SCI_RAG_DATABASE_URL=\n", encoding="utf-8")
    example.chmod(0o644)  # what a fresh checkout gives you

    commands = _env_file_commands(_read(page))
    script = "umask 022\n" + "\n".join(commands)
    shell_path, shell_dir = posix_shell("sh")
    environment = os.environ.copy()
    if shell_dir is not None:
        environment["PATH"] = f"{shell_dir}{os.pathsep}{environment.get('PATH', '')}"
    subprocess.run(
        [shell_path, "-c", script],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
    )

    created = tmp_path / ".env"
    assert created.is_file(), f"{page} did not create .env"
    if os.name == "nt":
        # Git's chmod is a POSIX-mode emulation; Windows ACL ownership is
        # asserted separately for apply_env_file() below.
        assert "chmod 600 .env" in commands, f"{page} does not request owner-only mode"
    else:
        mode = stat.S_IMODE(created.stat().st_mode)
        assert mode == 0o600, (
            f"{page} leaves .env at {oct(mode)}; a credential file must be owner only"
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL semantics are not available here")
@pytest.mark.parametrize("page", ENV_SETUP_PAGES)
def test_the_windows_clone_sequence_produces_an_owner_only_file(page: str, tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("SCI_RAG_DATABASE_URL=\n", encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text("fixture\n", encoding="utf-8")
    subprocess.run(
        ["icacls", str(env_path), "/grant:r", "*S-1-1-0:(M)"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    script = _code_block(_read(page), "powershell")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None, "PowerShell is required for the documented Windows route"
    subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    acl = windows_acl_snapshot(env_path)
    assert acl["Protected"] is True
    assert acl["Count"] == 1
    assert acl["Sid"] == acl["CurrentSid"]
    assert "FullControl" in str(acl["Rights"])
    assert acl["AccessType"] == "Allow"
    assert acl["Inherited"] is False


def test_both_routes_state_the_same_owner_only_contract() -> None:
    """A reader must not have to guess which route protects the file."""
    quickstart = _read("docs/quickstart.md")
    readme = _read("README.md")

    assert "owner-only mode `0600`" in quickstart
    assert "0600" in quickstart.partition("## 2. Choose a credential mode")[2]
    assert "600" in readme


def test_the_example_file_is_still_ignored_and_holds_no_credential() -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", ".env"], cwd=ROOT, capture_output=True, text=True
    )
    assert ignored.returncode == 0, ".env must stay ignored"

    example = _read(".env.example")
    for line in example.splitlines():
        if line.startswith("SCI_RAG_GOOGLE_API_KEY=") or line.startswith("SCI_RAG_API_KEYS="):
            assert line.split("=", 1)[1].strip() == "", "the example must not carry a value"
