"""Retired documentation addresses keep answering.

`scripts/docs_redirects.py` is a MkDocs hook, so its map in `mkdocs.yml` has
to name pages that exist, and the stubs it writes have to point at them from
the right directory. Both are checked here without building the whole site.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "scripts" / "docs_redirects.py"


def _hook():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("docs_redirects", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config() -> dict:  # type: ignore[type-arg]
    class _Loader(yaml.SafeLoader):
        pass

    _Loader.add_multi_constructor("tag:yaml.org,2002:python/name:", lambda *_: None)
    return yaml.load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"), Loader=_Loader)


def test_the_hook_is_wired_and_every_target_is_a_real_page() -> None:
    config = _config()
    assert "scripts/docs_redirects.py" in config["hooks"]
    redirects = config["extra"]["redirects"]
    assert redirects, "the map should name the pages retired so far"
    for old, new in redirects.items():
        assert not (ROOT / "docs" / old).exists(), f"{old} still exists; it needs no redirect"
        target = new.partition("#")[0]
        assert (ROOT / "docs" / target).is_file(), f"{old} redirects to a page that is not there"


def test_stubs_point_at_the_target_from_the_old_directory(tmp_path: Path) -> None:
    hook = _hook()
    (tmp_path / "get-started").mkdir()
    (tmp_path / "get-started" / "index.html").write_text("<h1>Get started</h1>", encoding="utf-8")

    written = hook.write_redirects(tmp_path, {"tour.md": "get-started.md#full-project-structure"})

    assert written == [tmp_path / "tour" / "index.html"]
    stub = written[0].read_text(encoding="utf-8")
    assert 'http-equiv="refresh"' in stub
    assert "url=../get-started/#full-project-structure" in stub
    assert '<link rel="canonical" href="../get-started/#full-project-structure">' in stub


def test_a_redirect_to_a_page_the_build_did_not_produce_fails_the_build(tmp_path: Path) -> None:
    hook = _hook()
    with pytest.raises(ValueError, match="was not built"):
        hook.write_redirects(tmp_path, {"tour.md": "nowhere.md"})
