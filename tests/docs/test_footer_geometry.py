"""Rendered layout guards for the compact documentation footer."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.docs_render

MEASURE_JS = """
() => {
  const footer = document.querySelector('.md-footer-meta');
  const inner = footer.querySelector('.md-footer-meta__inner');
  const items = [...document.querySelectorAll('.srag-footer__item')];
  const itemBoxes = items.map(item => item.getBoundingClientRect());
  const social = footer.querySelector('.md-social__link').getBoundingClientRect();
  const innerBox = inner.getBoundingClientRect();
  return {
    height: Math.round(footer.getBoundingClientRect().height),
    tops: itemBoxes.map(box => Math.round(box.top)),
    gaps: itemBoxes.slice(1).map((box, index) => Math.round(box.left - itemBoxes[index].right)),
    leftInset: Math.round(itemBoxes[0].left - innerBox.left),
    socialRightInset: Math.round(innerBox.right - social.right),
    overflows: footer.scrollWidth > footer.clientWidth + 1,
  };
}
"""


def test_footer_text_uses_one_compact_row_on_desktop(measure_pages: Any) -> None:
    """Copyright, version, and install link should align without a second text row."""
    measurements = measure_pages(MEASURE_JS, (768, 1200, 1440), ["index.html"])
    offenders = []

    for width, pages in measurements.items():
        result = pages[0][1]
        if (
            len(set(result["tops"])) != 1
            or result["height"] > 50
            or max(result["gaps"]) > 24
            or not 15 <= result["leftInset"] <= 25
            or not 15 <= result["socialRightInset"] <= 25
            or result["overflows"]
        ):
            offenders.append(f"{width}px: {result}")

    assert offenders == [], f"footer text should fit one compact desktop row: {offenders}"


def test_footer_stays_inside_a_phone_viewport(measure_pages: Any) -> None:
    """The narrow-screen fallback may wrap, but it must never overflow horizontally."""
    result = measure_pages(MEASURE_JS, (480,), ["index.html"])[480][0][1]

    assert result["overflows"] is False
