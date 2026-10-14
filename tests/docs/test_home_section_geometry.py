"""Rendered spacing guards for the homepage section dividers."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.docs_render

WIDTHS = (480, 768, 1200, 1440)
MAX_DIVIDER_GAP_PX = 27

MEASURE_JS = """
() => [...document.querySelectorAll('.srag-home-section + .srag-home-section')].map(section => {
  const sectionBox = section.getBoundingClientRect();
  const firstBox = section.firstElementChild.getBoundingClientRect();
  return Math.round(firstBox.top - sectionBox.top);
})
"""

HERO_FIGURE_MEASURE_JS = """
() => {
  const masthead = document.querySelector('.srag-home-masthead');
  const lede = document.querySelector('.srag-home-masthead__lede');
  const figureSection = masthead.nextElementSibling;
  const figure = figureSection.querySelector('.srag-home-figure');
  return {
    border: getComputedStyle(figureSection).borderTopWidth,
    gap: Math.round(figure.getBoundingClientRect().top - lede.getBoundingClientRect().bottom),
    widthDelta: Math.round(
      Math.abs(figure.getBoundingClientRect().width - figureSection.getBoundingClientRect().width)
    ),
  };
}
"""


def test_every_homepage_divider_has_the_same_tight_gap(
    measure_pages: Any,
) -> None:
    """Every divider should sit close to the content that follows it."""
    measurements = measure_pages(MEASURE_JS, WIDTHS, ["index.html"])
    offenders = []

    for width, pages in measurements.items():
        gaps = pages[0][1]
        if not gaps or max(gaps) > MAX_DIVIDER_GAP_PX or max(gaps) - min(gaps) > 1:
            offenders.append(f"{width}px: {gaps}")

    assert offenders == [], f"homepage divider spacing is uneven or too large: {offenders}"


def test_pipeline_figure_follows_the_intro_without_a_divider(measure_pages: Any) -> None:
    """The pipeline figure should sit close to the homepage introduction."""
    measurements = measure_pages(HERO_FIGURE_MEASURE_JS, WIDTHS, ["index.html"])
    offenders = []

    for width, pages in measurements.items():
        result = pages[0][1]
        if result["border"] != "0px" or result["gap"] > 60 or result["widthDelta"] > 1:
            offenders.append(f"{width}px: {result}")

    assert offenders == [], f"homepage figure should have no divider or oversized gap: {offenders}"
