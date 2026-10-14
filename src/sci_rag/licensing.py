"""A small, fail-closed license taxonomy for corpus documents.

Scientific corpora mix public-domain reports with paywalled papers, and a
RAG that redistributes retrieved text needs to know which is which. Every
document carries one of five classes, keyed to redistribution rights:

* ``public``: public domain or equivalent (for example US federal
  government works, CC0). Safe to redistribute anywhere.
* ``open_commercial``: openly licensed including commercial reuse
  (CC-BY, CC-BY-SA). Safe to redistribute with attribution.
* ``open_noncommercial``: openly licensed for noncommercial use only
  (CC-BY-NC and friends). Fine internally, not for commercial surfaces.
* ``restricted``: everything you may hold but not redistribute: paywalled
  PDFs, publisher versions of record, scraped pages.
* ``unknown``: the default when nobody has said otherwise.

The rule that makes this safe is fail-closed scoping: when a caller
restricts retrieval to particular classes, ``unknown`` is never included
unless they ask for it by name, and an empty scope means "return nothing",
not "return everything". Retrieval applies the scope inside every layer's
SQL, before ranking, so an out-of-scope document can never crowd out an
eligible one or leak into results.

You declare classes in your corpus manifest (see
``docs/bring-your-own-domain.md``). When in doubt, leave it ``unknown``;
that is exactly what the default is for.
"""

from __future__ import annotations

#: What a document carries when nobody has recorded its rights. Named because
#: the fail-closed rule is keyed on this exact value: `unknown` is never
#: included in a restricted scope unless a caller asks for it by name.
UNKNOWN_CLASS = "unknown"

LICENSE_CLASSES: tuple[str, ...] = (
    "public",
    "open_commercial",
    "open_noncommercial",
    "restricted",
    "unknown",
)

#: The classes safe to expose on surfaces you do not fully control
#: (a public API, an MCP server open to outside agents).
EXTERNAL_SAFE_CLASSES: tuple[str, ...] = ("public", "open_commercial")


def normalize_license_class(value: str | None) -> str:
    """Map a manifest value onto the taxonomy, defaulting to ``unknown``."""
    if value is None:
        return UNKNOWN_CLASS
    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in LICENSE_CLASSES:
        return cleaned
    aliases = {
        "cc0": "public",
        "public_domain": "public",
        "us_gov": "public",
        "cc_by": "open_commercial",
        "ccby": "open_commercial",
        "cc_by_sa": "open_commercial",
        "cc_by_nc": "open_noncommercial",
        "cc_by_nc_nd": "open_noncommercial",
        "cc_by_nc_sa": "open_noncommercial",
        "proprietary": "restricted",
        "paywalled": "restricted",
        "all_rights_reserved": "restricted",
    }
    return aliases.get(cleaned, UNKNOWN_CLASS)
