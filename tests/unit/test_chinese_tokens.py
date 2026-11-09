"""Shared segmentation keeps punctuation out of SQL query operators."""

import pytest

from sci_rag.keyword_tokens import chinese_search_tokens, contains_han, index_chinese


@pytest.mark.parametrize("value", ["陈林", "中文 English", "𠀀"])
def test_han_detection(value):
    assert contains_han(value)


def test_segmentation_preserves_names_and_mixed_identifiers():
    tokens = chinese_search_tokens("陈林的 PC-2026-047 项目报告")
    assert "陈林" in tokens and "的" not in tokens
    assert {"pc", "2026", "047"} <= set(tokens)
    assert index_chinese("English baseline unchanged") == ""


def test_query_operators_are_removed_without_inventing_tokens():
    tokens = chinese_search_tokens("陈林 ' | ! :* OR \\")
    assert "陈林" in tokens
    assert all(token.replace("_", "").isalnum() for token in tokens)
    assert len(tokens) == len(set(tokens))
