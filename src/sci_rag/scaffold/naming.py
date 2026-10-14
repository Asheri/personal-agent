"""Slug rules shared by the wizard, the appliers, and scripts/init_domain.py."""

from __future__ import annotations

import re

_FALLBACK_SLUG = "my-sci-rag"


def slugify(name: str) -> str:
    """A distribution- and directory-safe name derived from a human one."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or _FALLBACK_SLUG
