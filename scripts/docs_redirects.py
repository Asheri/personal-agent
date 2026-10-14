"""MkDocs hook: write a redirect stub for every page this site has retired.

A documentation page that moves leaves links behind, in issues, in chat logs,
in other people's notes. Deleting the page turns every one of them into a
404. This hook writes a small HTML stub at each old address that sends the
browser to the new one, so those links keep working.

The map lives in ``mkdocs.yml`` under ``extra.redirects`` as ``old.md:
new.md`` (an anchor on the target is allowed), next to the nav it corrects.
A target that the build did not produce fails the build, because a redirect
to nowhere is a 404 with extra steps. Stubs carry ``http-equiv="refresh"``,
which is how the page-head tests tell them apart from documentation pages.
"""

from __future__ import annotations

import html
import posixpath
from pathlib import Path
from typing import Any

STUB = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Redirecting...</title>
<link rel="canonical" href="{target}">
<meta name="robots" content="noindex">
<meta http-equiv="refresh" content="0; url={target}">
</head>
<body>This page moved. Continue to <a href="{target}">{target}</a>.</body>
</html>
"""


def _site_path(source: str) -> str:
    """The site-relative directory a Markdown source renders into."""
    stem = source[: -len(".md")] if source.endswith(".md") else source
    return "" if stem == "index" else stem.rstrip("/") + "/"


def write_redirects(site_dir: Path, redirects: dict[str, str]) -> list[Path]:
    """Write one stub per ``old -> new`` pair and return the stub paths."""
    written: list[Path] = []
    for old, new in redirects.items():
        target_page, _, anchor = new.partition("#")
        old_dir = _site_path(old)
        new_dir = _site_path(target_page)
        if not (site_dir / new_dir / "index.html").is_file():
            raise ValueError(f"redirect target {new!r} for {old!r} was not built")
        relative = posixpath.relpath(new_dir or ".", old_dir or ".")
        href = relative + "/" if relative != "." else "./"
        if anchor:
            href += f"#{anchor}"
        stub = site_dir / old_dir / "index.html"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(STUB.format(target=html.escape(href, quote=True)), encoding="utf-8")
        written.append(stub)
    return written


def on_post_build(config: Any, **_: Any) -> None:
    """MkDocs calls this after the site is written."""
    redirects = dict(config.get("extra", {}).get("redirects", {}) or {})
    if redirects:
        write_redirects(Path(config["site_dir"]), redirects)
