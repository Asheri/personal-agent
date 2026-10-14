"""Rendered-geometry guards for the metadata strips on task pages."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.docs_render

WIDTHS = (480, 768, 1200, 1440)

MEASURE_JS = """
() => [...document.querySelectorAll('.srag-meta-strip')].map(strip => ({
  cells: [...strip.children].map(cell => {
    const box = cell.getBoundingClientRect();
    return {
      top: Math.round(box.top),
      width: Math.round(box.width),
    };
  }),
}))
"""


@pytest.fixture(scope="module")
def measurements(
    measure_pages: Any, built_pages: list[str]
) -> dict[int, list[tuple[str, list[dict[str, Any]]]]]:
    """Measure every metadata strip on every built page."""
    return measure_pages(MEASURE_JS, WIDTHS, built_pages)


def test_metadata_cells_use_one_column_grid_across_the_entire_strip(
    measurements: dict[int, list[tuple[str, list[dict[str, Any]]]]],
) -> None:
    """Every cell must use the same column width, even when it wraps to another row."""
    measured = 0
    offenders = []
    for width, pages in measurements.items():
        for name, strips in pages:
            for strip in strips:
                measured += 1
                widths = [cell["width"] for cell in strip["cells"]]
                if widths and max(widths) - min(widths) > 1:
                    offenders.append(f"{name} at {width}px: cell widths {widths}")

    assert measured == 9 * len(WIDTHS), f"expected nine metadata strips, measured {measured}"
    assert offenders == [], f"metadata cells do not align to equal columns: {offenders}"


def test_metadata_cells_stack_on_narrow_screens(
    measurements: dict[int, list[tuple[str, list[dict[str, Any]]]]],
) -> None:
    """A phone-sized strip should present one readable metadata item per row."""
    offenders = []
    for name, strips in measurements[480]:
        for strip in strips:
            tops = [cell["top"] for cell in strip["cells"]]
            if len(tops) != len(set(tops)):
                offenders.append(name)

    assert offenders == [], f"metadata cells share a row on a narrow screen: {offenders}"
