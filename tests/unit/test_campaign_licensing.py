from __future__ import annotations

import pytest

from sci_rag.campaigns.licensing_map import license_class_for


@pytest.mark.parametrize(
    ("oa_status", "license_string", "expected"),
    [
        ("gold", "cc-by", "open_commercial"),
        ("gold", "CC-BY-SA", "open_commercial"),
        ("hybrid", "https://creativecommons.org/licenses/by/4.0/", "open_commercial"),
        ("gold", "cc-by-nd", "open_commercial"),
        ("gold", "cc-by-nc", "open_noncommercial"),
        ("green", "cc-by-nc-sa", "open_noncommercial"),
        (
            "hybrid",
            "https://creativecommons.org/licenses/by-nc-nd/4.0/",
            "open_noncommercial",
        ),
        ("gold", "cc0", "public"),
        ("gold", "https://creativecommons.org/publicdomain/zero/1.0/", "public"),
        ("gold", "public-domain", "public"),
        ("green", None, "unknown"),
        ("gold", "implied-oa", "unknown"),
        ("gold", "acs-specific: authorchoice", "unknown"),
        ("gold", "not-a-license", "unknown"),
        (None, None, "unknown"),
    ],
)
def test_license_class_for_fails_closed(
    oa_status: str | None,
    license_string: str | None,
    expected: str,
) -> None:
    assert license_class_for(oa_status, license_string) == expected
