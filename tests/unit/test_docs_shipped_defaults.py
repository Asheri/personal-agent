"""Guards for prose that reports a shipped default or a support claim.

Both guards exist because a defect of this kind is silent, and because it has
now happened twice. Flipping `compression.enabled` in `domain/domain.yaml` is a
one-line edit no test notices, so the pages describing what the demo ships keep
asserting the old state: `docs/architecture.md` reported a paired judged-answer
gate as passed after the v0.3 benchmark re-ran it and it did not hold, and
`docs/evaluation.md` kept the superseded run's table under the sentence "the
demo adopts `compression.enabled: true`". Both are claims about evidence,
contradicted by the evidence. The first was found and corrected by hand; the
second survived that correction, which is the argument for a test.

The support range fails the same way. ADR 0008 sets it, several surfaces repeat
it, and the README kept saying `PostgreSQL 15+` for a floor nothing tested.

So each guard reads the source of truth (the domain profile, `CompressionTuning`,
the ADR) and holds the prose to it, rather than pinning the prose to a literal.
Changing a default is still one line; leaving the pages behind now fails.
"""

import re
from pathlib import Path

from sci_rag.domain import CompressionTuning, load_domain

ROOT = Path(__file__).resolve().parents[2]
DOMAIN_DIR = ROOT / "domain"
METHODOLOGY = ROOT / "docs" / "methodology.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
EVALUATION = ROOT / "docs" / "evaluation.md"
ROADMAP = ROOT / "docs" / "ROADMAP.md"
BENCHMARKS = ROOT / "docs" / "benchmarks.md"
CONFIGURATION = ROOT / "docs" / "configuration.md"
ADR_POSTGRES = ROOT / "docs" / "adr" / "0008-supported-postgresql-versions.md"
DEFAULT_INSTALL = "uv sync --extra modelscope-embedding --extra openai"

# Pages that state what the demo ships, and therefore have to be re-read when it
# changes. Each also carries the reasoning for why the default is corpus-specific,
# which is worth keeping whichever way the gate lands.
DEMO_CLAIM_PAGES = (METHODOLOGY, ARCHITECTURE, EVALUATION)

# The subset that also states what a reader gets before writing any domain
# profile at all. `docs/architecture.md` describes the demo; `docs/evaluation.md`
# describes running the gate. Only the specification states both defaults.
MODEL_DEFAULT_PAGES = (METHODOLOGY,)

# Phrasings that assert the demo compresses, and phrasings that assert it does
# not. Neither list can be exhaustive, and neither needs to be: the guard
# requires the page to make the claim matching the config *and* to be free of
# the claim contradicting it, so flipping the config without touching the prose
# fails on the stale half even if the new phrasing is one nobody predicted.
DEMO_COMPRESSES = (
    "on for the shipped demo",
    "demo enables compression",
    "enabled for the shipped demo",
    "shipped demo turns compression on",
    "demo adopts `compression.enabled: true`",
)
DEMO_DOES_NOT_COMPRESS = (
    "off for the shipped demo",
    "demo leaves compression off",
    "disabled for the shipped demo",
    "shipped demo ships with compression off",
    "demo keeps compression off",
    "demo keeps `compression.enabled: false`",
)

# The same shape for the other default a reader could act on: what they get
# before writing any domain profile at all.
MODEL_DEFAULT_COMPRESSES = ("on in the model default", "enabled in the model default")
MODEL_DEFAULT_DOES_NOT = ("off in the model default", "disabled in the model default")

# Summary pages must state the current shipped verdict, not leave it as a
# possibility or preserve the rejected floor's verdict as the current one.
SUMMARY_COMPRESSES = ("compression defaults on",)
SUMMARY_DOES_NOT_COMPRESS = ("compression defaults off",)
SUMMARY_HEDGES = ("compression may default on",)

# Surfaces a reader meets the support range through. `docs/planning/` is a
# historical record and excluded from the site, so it is excluded here too.
POSTGRES_CLAIM_PAGES = (
    ROOT / "README.md",
    ROOT / "docs" / "quickstart.md",
    ROOT / "docs" / "faq.md",
)

# Retired floors. The ADR discusses 15 as history and as what will probably keep
# working, so it is not held to this; support is a claim about what is tested.
RETIRED_POSTGRES_CLAIMS = ("postgresql 15+", "postgresql 15 or newer")


def _text(page: Path) -> str:
    """The page as one lowercase line, so a phrase split by wrapping still matches."""
    return re.sub(r"\s+", " ", page.read_text(encoding="utf-8")).casefold()


# "16 through 18" and "16 to 18" are the same claim; the numbers are what a
# page can get wrong, so the pattern pins those and lets the preposition vary.
SUPPORTED_RANGE = re.compile(r"postgresql (\d+) (?:through|to) (\d+)")


def _supported_range() -> tuple[str, str]:
    """The range as ADR 0008 states it, which is what every page has to repeat."""
    found = SUPPORTED_RANGE.search(_text(ADR_POSTGRES))
    assert found, f"ADR 0008 should state a supported range matching {SUPPORTED_RANGE.pattern!r}"
    return found.group(1), found.group(2)


def _assert_prose_matches(
    pages: tuple[Path, ...],
    enabled: bool,
    on_phrases: tuple[str, ...],
    off_phrases: tuple[str, ...],
    subject: str,
    source: str,
) -> None:
    """Hold every page to the claim `enabled` supports, and to no other."""
    wanted, unwanted = (on_phrases, off_phrases) if enabled else (off_phrases, on_phrases)
    state = "on" if enabled else "off"
    verb = "enables" if enabled else "disables"

    for page in pages:
        text = _text(page)
        where = page.relative_to(ROOT)

        assert any(phrase in text for phrase in wanted), (
            f"{where} should say compression is {state} {subject}, because {source} "
            f"{verb} it. Expected one of {list(wanted)}"
        )
        stale = [phrase for phrase in unwanted if phrase in text]
        assert not stale, (
            f"{where} still claims compression is not {state} {subject} ({stale}), "
            f"but {source} says otherwise"
        )


def test_compression_prose_matches_the_shipped_demo_default() -> None:
    _assert_prose_matches(
        pages=DEMO_CLAIM_PAGES,
        enabled=load_domain(DOMAIN_DIR).config.compression.enabled,
        on_phrases=DEMO_COMPRESSES,
        off_phrases=DEMO_DOES_NOT_COMPRESS,
        subject="for the shipped demo",
        source="domain/domain.yaml",
    )


def test_compression_prose_matches_the_model_default() -> None:
    _assert_prose_matches(
        pages=MODEL_DEFAULT_PAGES,
        enabled=CompressionTuning().enabled,
        on_phrases=MODEL_DEFAULT_COMPRESSES,
        off_phrases=MODEL_DEFAULT_DOES_NOT,
        subject="in the model default",
        source="CompressionTuning",
    )


def test_compression_summary_pages_match_the_shipped_demo_default() -> None:
    pages = (ROADMAP, BENCHMARKS)
    _assert_prose_matches(
        pages=pages,
        enabled=load_domain(DOMAIN_DIR).config.compression.enabled,
        on_phrases=SUMMARY_COMPRESSES,
        off_phrases=SUMMARY_DOES_NOT_COMPRESS,
        subject="for the shipped demo",
        source="domain/domain.yaml",
    )
    for page in pages:
        hedges = [phrase for phrase in SUMMARY_HEDGES if phrase in _text(page)]
        assert not hedges, f"{page.relative_to(ROOT)} still hedges the shipped default: {hedges}"


def test_configuration_reference_shows_the_shipped_compression_default() -> None:
    row = re.search(
        r"\| `compression\.enabled` \| bool \| (?P<default>true|false) \|",
        CONFIGURATION.read_text(encoding="utf-8"),
    )
    assert row is not None, "configuration.md should publish the compression.enabled row"

    enabled = load_domain(DOMAIN_DIR).config.compression.enabled
    assert row.group("default") == str(enabled).lower(), (
        "configuration.md should take the shipped compression default from domain/domain.yaml"
    )


def test_the_pages_keep_the_reasoning_for_a_per_corpus_default() -> None:
    """The verdict changes per corpus; the argument for gating it does not."""
    for page in DEMO_CLAIM_PAGES:
        text = _text(page)
        assert "gate" in text, (
            f"{page.relative_to(ROOT)} should keep the judged-answer gate in the picture"
        )
        assert "corpus" in text, (
            f"{page.relative_to(ROOT)} should keep why the default is corpus-specific"
        )
        assert "benchmarks.md" in text, (
            f"{page.relative_to(ROOT)} should point at docs/benchmarks.md for the run"
        )


def test_the_postgresql_support_range_is_stated_the_same_everywhere() -> None:
    floor, ceiling = _supported_range()

    for page in POSTGRES_CLAIM_PAGES:
        text = _text(page)
        where = page.relative_to(ROOT)

        stated = SUPPORTED_RANGE.search(text)
        assert stated, f"{where} should state a PostgreSQL range, as ADR 0008 does"
        assert stated.groups() == (floor, ceiling), (
            f"{where} says PostgreSQL {stated.group(1)} to {stated.group(2)}, but "
            f"ADR 0008 supports {floor} through {ceiling}"
        )

        stale = [claim for claim in RETIRED_POSTGRES_CLAIMS if claim in text]
        assert not stale, f"{where} still claims a retired PostgreSQL floor: {stale}"


def test_docs_document_new_default_providers() -> None:
    """The shipped configuration and its setup instructions must move together."""
    env = Path(".env.example").read_text(encoding="utf-8")
    assert "SCI_RAG_EMBEDDING_PROVIDER=modelscope" in env
    assert "SCI_RAG_LLM_PROVIDER=deepseek" in env
    assert "SCI_RAG_DEEPSEEK_API_KEY" in env
    assert "modelscope-embedding" in Path("README.md").read_text(encoding="utf-8")


def test_default_install_includes_both_provider_extras() -> None:
    """The shipped provider pair must work after one documented setup command."""
    pages = (
        ROOT / "README.md",
        ROOT / "docs" / "quickstart.md",
        CONFIGURATION,
        ROOT / "docs" / "faq.md",
    )
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert DEFAULT_INSTALL in text, f"{page.relative_to(ROOT)} must show the default install"

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(rf"(?m)^\t{re.escape(DEFAULT_INSTALL)}$", makefile), (
        "make setup must install the shipped ModelScope and DeepSeek dependencies"
    )


def test_google_quickstart_and_readme_switch_the_whole_google_provider_set() -> None:
    quickstart = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    sections = {
        "AI Studio": quickstart.partition('=== "AI Studio"')[2].partition('=== "Vertex AI"')[0],
        "Vertex AI": quickstart.partition('=== "Vertex AI"')[2].partition('=== "Offline"')[0],
    }
    expected = (
        "SCI_RAG_LLM_PROVIDER=google",
        "SCI_RAG_LLM_MODEL=gemini-3.6-flash",
        "SCI_RAG_EMBEDDING_PROVIDER=google",
        "SCI_RAG_EMBEDDING_MODEL=gemini-embedding-001",
        "SCI_RAG_EMBEDDING_DIM=1024",
    )
    for label, section in sections.items():
        missing = [claim for claim in expected if claim not in section]
        assert not missing, f"{label} snippet does not switch to Google: {missing}"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [claim for claim in expected if claim not in readme]
    assert not missing, f"README Google option is incomplete: {missing}"


def test_provider_docs_state_one_default_configuration() -> None:
    """A reader must get the same provider, model, dimension, and setup path on every page."""
    expected = {
        ROOT / "README.md": (
            "modelscope-embedding",
            "Qwen/Qwen3-Embedding-0.6B",
            "DeepSeek",
            "1024",
        ),
        CONFIGURATION: (
            "| `SCI_RAG_EMBEDDING_PROVIDER`",
            "| modelscope |",
            "| `SCI_RAG_LLM_PROVIDER`",
            "| deepseek |",
            "| `SCI_RAG_EMBEDDING_DIM` | int | 1024 |",
        ),
        ROOT / "docs" / "extend.md": (
            "modelscope",
            "deepseek",
            "modelscope-embedding",
            "SCI_RAG_DEEPSEEK_API_KEY",
        ),
        ROOT / "docs" / "faq.md": (
            "0012-modelscope-deepseek-providers.md",
            "1024",
            "embed reindex",
            "sci-rag doctor",
        ),
    }

    for page, claims in expected.items():
        text = page.read_text(encoding="utf-8")
        missing = [claim for claim in claims if claim not in text]
        assert not missing, f"{page.relative_to(ROOT)} is missing shipped-default claims: {missing}"

    default_generation_pages = (
        ROOT / "README.md",
        ROOT / "docs" / "quickstart.md",
        CONFIGURATION,
        ROOT / "docs" / "faq.md",
    )
    for page in default_generation_pages:
        text = page.read_text(encoding="utf-8")
        assert "SCI_RAG_DEEPSEEK_API_KEY" in text, f"{page.relative_to(ROOT)} omits the default key"
        assert "https://api.deepseek.com" in text, f"{page.relative_to(ROOT)} omits the default URL"
        assert "SCI_RAG_LLM_PROVIDER=google" in text, (
            f"{page.relative_to(ROOT)} must say Google credentials do not switch the provider"
        )

    env = Path(".env.example").read_text(encoding="utf-8")
    assigned_key = re.search(r"^[^#\n]*SCI_RAG_DEEPSEEK_API_KEY=(?P<value>\S+)", env, re.MULTILINE)
    assert assigned_key is None, ".env.example must show an empty DeepSeek key, never a real value"
    assert "# Default provider pair" in env, ".env.example must identify the shipped provider pair"


def test_explanatory_pages_do_not_keep_google_only_defaults() -> None:
    """Google remains available, but it cannot remain described as the default."""
    stale_claims = {
        ROOT / "docs" / "architecture.md": ("Google + offline", "default 1536"),
        ROOT / "docs" / "methodology.md": ("default dimension is **1536**",),
        ROOT / "docs" / "glossary.md": ("default Google embedding is cut to 1536",),
        ROOT / "docs" / "choosing-sci-rag-kit.md": ("Embeddings are Google-only",),
        ROOT / "docs" / "troubleshooting.md": ("No Google credentials configured",),
    }
    current_claims = {
        ROOT / "docs" / "architecture.md": ("ModelScope", "DeepSeek", "default 1024"),
        ROOT / "docs" / "methodology.md": ("default dimension is **1024**", "ModelScope"),
        ROOT / "docs" / "glossary.md": ("default ModelScope embedding", "1024 dimensions"),
        ROOT / "docs" / "choosing-sci-rag-kit.md": ("ModelScope", "DeepSeek", "Google"),
        ROOT / "docs" / "troubleshooting.md": (
            "SCI_RAG_DEEPSEEK_API_KEY",
            "SCI_RAG_LLM_PROVIDER=google",
        ),
    }

    for page, claims in stale_claims.items():
        text = page.read_text(encoding="utf-8")
        found = [claim for claim in claims if claim in text]
        assert not found, f"{page.relative_to(ROOT)} keeps stale provider defaults: {found}"

    for page, claims in current_claims.items():
        text = page.read_text(encoding="utf-8")
        missing = [claim for claim in claims if claim not in text]
        assert not missing, f"{page.relative_to(ROOT)} is missing current provider facts: {missing}"


def test_methodology_describes_embedding_prompts_by_provider() -> None:
    text = METHODOLOGY.read_text(encoding="utf-8")
    stale = "Queries and documents each embed with their own task hint"
    assert stale not in text
    assert "ModelScope uses the `query` prompt for queries and no prompt for documents" in text
    assert "Google uses `RETRIEVAL_QUERY` and `RETRIEVAL_DOCUMENT`" in text
