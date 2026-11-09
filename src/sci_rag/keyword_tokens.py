"""Search-mode Chinese segmentation shared by indexing and queries."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]")
_WORD = re.compile(r"[\w]+", re.UNICODE)
_STOP_WORDS = frozenset(
    [
        "的",
        "了",
        "是",
        "在",
        "与",
        "和",
        "或",
        "及",
        "把",
        "被",
        "地",
        "得",
        "吗",
        "呢",
        "吧",
        "啊",
        "请",
    ]
)


def contains_han(value: str) -> bool:
    return bool(_HAN.search(value))


@lru_cache(maxsize=1)
def _tokenizer() -> Any:
    import jieba

    tokenizer = jieba.Tokenizer()
    tokenizer.initialize()
    return tokenizer


def chinese_search_tokens(value: str) -> list[str]:
    """Keep word tokens only; punctuation can never become tsquery syntax."""
    if not contains_han(value):
        return []
    tokens = _tokenizer().cut_for_search(value.casefold())
    return list(
        dict.fromkeys(
            part for token in tokens for part in _WORD.findall(token) if part not in _STOP_WORDS
        )
    )


def index_chinese(value: str) -> str:
    return " ".join(chinese_search_tokens(value))


def index_search(value: str) -> str:
    """Index Latin identifiers even when their document contains no Han text."""
    if contains_han(value):
        return index_chinese(value)
    return " ".join(dict.fromkeys(_WORD.findall(value.casefold())))
