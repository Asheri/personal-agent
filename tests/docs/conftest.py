"""Shared plumbing for the tests that measure the built site in a browser.

Both modules in this tier need the same three things: the pages the build
emitted, a real HTTP origin to load them from, and a browser to load them with.
Serving matters because ``file://`` resolves the stylesheets differently.

The browser is handed over as a function that runs one measurement pass rather
than as a live object, and that is deliberate. Playwright's synchronous API
drives its event loop from a greenlet on the main thread, and holding that open
past this tier deadlocks the asyncio tiers that run after it: a full ``pytest``
run wedges with the main thread parked in ``kevent`` inside the greenlet. Every
launch therefore opens and closes inside a single call.

Everything here skips rather than fails when the site or the browser is
missing, the way the integration tier skips without PostgreSQL. A skipped run
is not evidence that presentation passed.
"""

from __future__ import annotations

import functools
import http.server
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"

# Tall enough that the page head and the first code blocks are laid out; these
# measurements read the layout box, not the pixels, so nothing has to be
# scrolled into view.
VIEWPORT_HEIGHT = 900


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """The default handler logs every asset to stderr, which buries test output."""

    # The default is HTTP/1.0, which closes the socket after every response.
    # The browser opens several connections per page and reuses them, so on a
    # long run it eventually reuses one the server has already closed and the
    # request stalls until the navigation times out. Answering HTTP/1.1 keeps
    # the connections alive and the reuse honest.
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return


def is_redirect_stub(page: Path) -> bool:
    """A retired address that forwards to the page's new home.

    `scripts/docs_redirects.py` writes these. They carry no theme, so they
    are not documentation pages and the geometry rules do not apply.
    """
    return 'http-equiv="refresh"' in page.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def built_pages() -> list[str]:
    """Every page the build emitted, as site-relative URLs in a stable order."""
    pages = sorted(SITE.rglob("*.html")) if SITE.is_dir() else []
    if not pages:
        pytest.skip(f"no built site at {SITE}; run `make docs` first")
    return [page.relative_to(SITE).as_posix() for page in pages if not is_redirect_stub(page)]


@pytest.fixture(scope="session")
def site_origin(built_pages: list[str]) -> Iterator[str]:
    """Serve the built site, because file:// resolves the stylesheets differently."""
    handler = functools.partial(_QuietHandler, directory=str(SITE))
    # Threading matters: the browser opens several keep-alive connections per
    # page, and a single-threaded server serialises them into a stall.
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            thread.join(timeout=5)


Measure = Callable[[str, Sequence[int], Sequence[str]], dict[int, list[tuple[str, Any]]]]


@pytest.fixture(scope="session")
def measure_pages(site_origin: str) -> Measure:
    """Return a function that measures the given pages at the given widths.

    Each page is loaded once and evaluated at every width, because the layout
    that moves between widths is driven by media queries rather than by
    anything the page fetches. Reloading per width doubles the navigations for
    identical numbers.
    """
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="playwright is not installed; `uv sync --group docs-test`",
    )

    def run(
        script: str, widths: Sequence[int], pages: Sequence[str]
    ) -> dict[int, list[tuple[str, Any]]]:
        collected: dict[int, list[tuple[str, Any]]] = {width: [] for width in widths}
        with playwright.sync_playwright() as driver:
            try:
                browser = driver.chromium.launch()
            except Exception as exc:  # pragma: no cover - environment guard
                pytest.skip(
                    f"no Playwright browser ({type(exc).__name__}); "
                    "run `playwright install chromium`"
                )
            page = browser.new_page(viewport={"width": widths[0], "height": VIEWPORT_HEIGHT})
            for relative in pages:
                page.goto(f"{site_origin}/{relative}", wait_until="domcontentloaded")
                for width in widths:
                    page.set_viewport_size({"width": width, "height": VIEWPORT_HEIGHT})
                    collected[width].append((relative, page.evaluate(script)))
            browser.close()

        return collected

    return run
