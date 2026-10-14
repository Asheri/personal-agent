"""The license file a generated project ships.

F-013 in the 2026-08-29 documentation route audit: the wizard offered
`Apache-2.0`, the completion report said `LICENSE Apache-2.0`, the module
comment said the offered texts were stored verbatim, and the generated file
was a nineteen-line notice pointing at the real terms. BSD-3-Clause and MIT
shipped complete, so one of three menu entries meant something different from
the other two.

These tests are deliberately byte level. A legal text is the one kind of
string in this repository that must not be reflowed, rewrapped, or tidied,
and a test asserting "contains the word Apache" would not notice any of that
happening.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from sci_rag.scaffold.licenses import LICENSE_KEYS, render_license

OFFERED = tuple(key for key in LICENSE_KEYS if key != "none")

# The canonical Apache License 2.0 as published by the Apache Software
# Foundation, taken from the SPDX license list and cross-checked against the
# independent copy shipped by `packaging`. Their terms sections are identical;
# the SPDX copy additionally carries the appendix, which is part of the
# published text.
APACHE_2_0_SHA256 = "50e6751797c50dedd75ef1b8a0d9e42f5f8472e9fbce91f34718e9f97b0c780a"
APACHE_2_0_LINES = 201


def _render(key: str) -> str:
    text = render_license(key, author="A Scientist", year=2026)
    assert text is not None
    return text


def test_no_license_means_no_file() -> None:
    assert render_license("none", author="A Scientist", year=2026) is None


def test_an_unknown_license_names_the_ones_that_exist() -> None:
    with pytest.raises(KeyError, match=re.escape("Apache-2.0")):
        render_license("GPL-3.0", author="A Scientist", year=2026)


@pytest.mark.parametrize("key", OFFERED)
def test_every_offered_license_ships_its_full_terms(key: str) -> None:
    """The menu offers licenses. All three have to be licenses."""
    text = _render(key)

    assert len(text.splitlines()) > 20, f"{key} is too short to be a license text"
    # Each of the three words its disclaimer differently, so match the shape
    # rather than one license's phrasing.
    assert "WARRANT" in text.upper(), f"{key} carries no warranty disclaimer"
    assert "full license text is at" not in text, (
        f"{key} points at its terms instead of containing them"
    )


def test_the_apache_text_is_the_canonical_one_byte_for_byte() -> None:
    """The whole point of the fix. Compare the bytes, not the vibe."""
    text = _render("Apache-2.0")

    assert len(text.splitlines()) == APACHE_2_0_LINES
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == APACHE_2_0_SHA256, (
        "the Apache License 2.0 text changed. It is a published legal document, "
        "so the only correct edit is none: restore it rather than reformatting it."
    )


def test_the_apache_terms_a_user_relies_on_are_actually_present() -> None:
    """A hash alone would pass on any text. Name what has to be in it."""
    text = _render("Apache-2.0")

    for clause in (
        "1. Definitions.",
        "2. Grant of Copyright License.",
        "3. Grant of Patent License.",
        "4. Redistribution.",
        "5. Submission of Contributions.",
        "6. Trademarks.",
        "7. Disclaimer of Warranty.",
        "8. Limitation of Liability.",
        "9. Accepting Warranty or Additional Liability.",
        "END OF TERMS AND CONDITIONS",
        "APPENDIX: How to apply the Apache License to your work.",
    ):
        assert clause in text, f"the Apache text is missing {clause!r}"


def test_the_apache_appendix_keeps_its_placeholders() -> None:
    """Apache says put your copyright in NOTICE, not in the license.

    Filling the appendix in would be editing a published document to say
    something it does not say.
    """
    text = _render("Apache-2.0")

    assert "Copyright [yyyy] [name of copyright owner]" in text
    assert "A Scientist" not in text
    assert "2026" not in text


@pytest.mark.parametrize("key", ("BSD-3-Clause", "MIT"))
def test_the_copyright_licenses_still_carry_the_author_and_year(key: str) -> None:
    """Unlike Apache, these two put the copyright line inside the file."""
    text = _render(key)

    assert "A Scientist" in text
    assert "2026" in text


def test_rendering_is_deterministic() -> None:
    """Generation runs offline and must produce the same bytes every time."""
    for key in OFFERED:
        assert _render(key) == _render(key)
