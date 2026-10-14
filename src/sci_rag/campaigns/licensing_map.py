"""Map explicit upstream license signals onto the corpus taxonomy."""

from __future__ import annotations

import re


def license_class_for(oa_status: str | None, license_string: str | None) -> str:
    """Classify only recognized licenses, never OA status by itself.

    An open-access status describes availability, not redistribution rights.
    Keeping it in this signature makes that distinction explicit at the call
    site while every missing, implied, or publisher-specific license fails
    closed to ``unknown``.
    """
    del oa_status
    if not isinstance(license_string, str) or not license_string.strip():
        return "unknown"

    value = license_string.strip().casefold()
    value = value.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    compact = re.sub(r"[\s_]+", "-", value)

    if (
        compact in {"cc0", "cc-zero", "public-domain", "public-domain-mark", "pdm"}
        or "/publicdomain/zero/" in f"{compact}/"
        or "/publicdomain/mark/" in f"{compact}/"
    ):
        return "public"

    creative_commons = compact
    marker = "creativecommons.org/licenses/"
    if marker in creative_commons:
        creative_commons = creative_commons.split(marker, 1)[1]
    creative_commons = re.sub(r"[/_]+", "-", creative_commons).strip("-")
    creative_commons = creative_commons.removeprefix("cc-")
    if creative_commons == "by-nc" or creative_commons.startswith("by-nc-"):
        return "open_noncommercial"
    if creative_commons == "by" or creative_commons.startswith("by-"):
        return "open_commercial"
    return "unknown"
