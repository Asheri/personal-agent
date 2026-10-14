"""Guards for the one page whose whole purpose is being honest about limits.

`choosing-sci-rag-kit.md` is the page a reader trusts to say what the kit does
not do. That makes it the page where a stale claim costs the most, and it is
structurally the most likely to go stale: every sentence is about a boundary,
and shipping a feature moves a boundary without touching this file. It said
other model providers were "a contribution away" for the whole time after ADR
0006 shipped three adapters.

These guards pin the two claims that go stale on their own. A shipped provider
adapter has to be named here, so growing the supported set forces a re-read.
Assertions about other projects have to carry a date, so a reader can judge how
old they are and a maintainer knows when they were last checked. And a count of
files is banned outright: it was wrong by a factor of six, it would need editing
most weeks to stay right, and it was never the claim worth making.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "choosing-sci-rag-kit.md"
LLM = ROOT / "src" / "sci_rag" / "llm"

# How each shipped adapter has to be recognisable on the page. The key is the
# module; the value is the spellings a reader would look for.
PROVIDER_NAMES = {
    "google": ("Gemini", "google"),
    "anthropic": ("Claude", "anthropic"),
    "openai_compat": ("OpenAI-compatible", "openai-compatible", "OpenAI"),
}

AS_OF = re.compile(
    r"\bas of\s+(?:\w+\s+)?(?:20\d\d|\d{4}-\d\d-\d\d)",
    re.IGNORECASE,
)
FILE_COUNT = re.compile(r"[~≈]?\s*\d[\d,]*\s+files\b", re.IGNORECASE)


def _shipped_adapters() -> list[str]:
    """Modules defining an `LLMClient` implementation, found by reading the source.

    Structural rather than a list of filenames, so a fourth adapter is picked up
    the day it lands, and `spec.py` or another helper never looks like one. Read
    with `ast` rather than imported because two of the three adapters sit behind
    optional SDK extras.
    """
    found = []
    for path in sorted(LLM.glob("*.py")):
        classes = [
            node
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.ClassDef)
        ]
        # The module that declares the interface also holds the mock that
        # implements it, and neither is a provider.
        if any(node.name == "LLMClient" for node in classes):
            continue
        if any(
            isinstance(base, ast.Name) and base.id == "LLMClient"
            for node in classes
            for base in node.bases
        ):
            found.append(path.stem)
    return found


def test_the_adapter_modules_are_discoverable() -> None:
    # Every assertion below is vacuous if this finds nothing.
    shipped = _shipped_adapters()
    assert len(shipped) >= 3, f"expected the shipped provider adapters, found {shipped}"
    assert set(shipped) <= set(PROVIDER_NAMES), (
        f"a new adapter needs a reader-facing spelling in PROVIDER_NAMES: {shipped}"
    )


def test_every_shipped_provider_is_named_on_the_comparison_page() -> None:
    """The page said other providers were 'a contribution away' after they shipped."""
    text = PAGE.read_text(encoding="utf-8")

    missing = [
        module
        for module in _shipped_adapters()
        if not any(name.casefold() in text.casefold() for name in PROVIDER_NAMES[module])
    ]

    assert missing == [], (
        f"these adapters ship but the comparison page does not mention them: {missing}"
    )


def test_claims_about_other_projects_carry_a_date() -> None:
    """A reader cannot judge 'is in maintenance mode' without knowing when."""
    section = re.search(
        r"^## The landscape.*?(?=^## )",
        PAGE.read_text(encoding="utf-8"),
        re.DOTALL | re.MULTILINE,
    )
    assert section is not None, "the page should still have its landscape section"

    assert AS_OF.search(section.group(0)), (
        "assertions about another project need an explicit 'as of <date>' the reader can weigh"
    )


def test_the_page_does_not_count_the_repositorys_files() -> None:
    """'~60 files' was wrong by a factor of six and would go stale most weeks."""
    offenders = FILE_COUNT.findall(PAGE.read_text(encoding="utf-8"))

    assert offenders == [], (
        f"a file count dates the page and says less than its shape does: {offenders}"
    )
