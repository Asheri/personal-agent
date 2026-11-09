"""Chinese routing must recognize classes and spend graph calls on synthesis."""

from pathlib import Path

import pytest

from sci_rag.domain import load_domain
from sci_rag.retrieve.router import route

DOMAIN = Path(__file__).parents[2] / "domain-personal"


@pytest.mark.parametrize(
    "query,expected",
    [
        ("查找最新版本的文件", "locating"),
        ("这份材料属于哪个项目", "project"),
        ("谁是作者", "person"),
        ("按时间查看历史进展", "timeline"),
    ],
)
def test_chinese_classification(query, expected):
    profile = load_domain(DOMAIN)
    assert profile.classify_query(query).name == expected


@pytest.mark.parametrize(
    "query,profile,graph,community",
    [
        ("陈林是谁", "interactive", False, False),
        ("比较星河和海岚项目的方法", "deep", True, False),
        ("概述所有材料的主要主题", "deep", False, True),
        ("谁比较过两个项目的区别", "deep", True, False),
    ],
)
async def test_chinese_routing(query, profile, graph, community):
    decision = await route(query, load_domain(DOMAIN))
    assert (decision.profile, decision.include_graph, decision.include_community) == (
        profile,
        graph,
        community,
    )
    assert decision.reasons
