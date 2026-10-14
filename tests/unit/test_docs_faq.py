"""Guards for the FAQ, which is a synthesis and therefore goes stale silently.

Every other page owns its subject. The FAQ borrows one: it restates, briefly,
what the decision records already argue at length, so the decision records can
stay the place a reversal condition lives. That shape has one failure mode. Add
a ninth ADR and nothing breaks, nothing warns, and the page that a reader treats
as the index of "why is it built this way" quietly stops being one. ADR 0008
landed between this page being planned and being written, which is the same
failure caught early.

So the first guard is the one that matters: every decision record is reachable
from a question. The rest keep the page's shape (topic groups, questions phrased
as questions) and keep it from becoming an orphan that only the nav links to.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
FAQ = DOCS / "faq.md"
MKDOCS = ROOT / "mkdocs.yml"

# The pages whose readers are asking the questions: the two hub pages, the
# comparison page that hands off its definitional half, and the README.
EXPECTED_INBOUND = (
    DOCS / "learn.md",
    DOCS / "get-started.md",
    DOCS / "choosing-sci-rag-kit.md",
    ROOT / "README.md",
)


def _body(page: Path) -> str:
    """Return the page's Markdown with any YAML front matter stripped."""
    text = page.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        _, _, rest = text.partition("---\n")
        _, _, body = rest.partition("---\n")
        return body
    return text


def _headings(level: int) -> list[str]:
    marker = "#" * level
    headings = re.findall(rf"^{marker} (?!#)(.+)$", _body(FAQ), re.MULTILINE)
    return [re.sub(r"\s+\{#[^}]+\}\s*$", "", heading) for heading in headings]


def test_the_faq_is_a_page_in_the_nav() -> None:
    assert FAQ.is_file(), "docs/faq.md should exist"

    # MkDocs config uses Python-specific YAML tags, so load it as plain strings.
    nav = yaml.dump(yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)["nav"])

    assert "faq.md" in nav, "mkdocs.yml runs under --strict, so an unlisted page fails the build"


def test_every_decision_record_is_reachable_from_a_question() -> None:
    """A new ADR that no question links to is an FAQ that has stopped indexing."""
    records = sorted(path.name for path in DOCS.joinpath("adr").glob("0*.md"))
    assert len(records) >= 8, f"expected the decision records, found {records}"

    faq = FAQ.read_text(encoding="utf-8")
    missing = [name for name in records if f"adr/{name}" not in faq]

    assert missing == [], f"no FAQ question links to these decision records: {missing}"


def test_the_faq_does_not_hard_code_the_decision_record_count() -> None:
    """Full and no-demo templates contain different, evolving ADR sets."""
    number = r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+"

    assert re.search(rf"\b(?:{number}) decision records?\b", _body(FAQ), re.IGNORECASE) is None


def test_the_page_is_topic_groups_of_questions() -> None:
    """toc_depth is 3 and toc.integrate is on, so every H3 lands in the sidebar."""
    groups = _headings(2)
    questions = _headings(3)

    assert len(groups) >= 5, f"expected topic groups, found {groups}"
    assert len(questions) >= 20, f"expected a question per heading, found {len(questions)}"

    statements = [text for text in questions if not text.rstrip().endswith("?")]

    assert statements == [], f"an FAQ heading should be the question a reader asks: {statements}"


def test_the_pages_that_should_send_readers_here_do() -> None:
    """A synthesis nothing links to is a page only the nav knows about."""
    orphaned = [
        str(page.relative_to(ROOT))
        for page in EXPECTED_INBOUND
        if not re.search(r"\]\((?:docs/)?faq\.md[)#]", page.read_text(encoding="utf-8"))
    ]

    assert orphaned == [], f"these pages should link to the FAQ: {orphaned}"
