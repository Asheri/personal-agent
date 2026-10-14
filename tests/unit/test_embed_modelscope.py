"""ModelScope Qwen3 嵌入器的离线单元测试。"""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from sci_rag.config import Settings
from sci_rag.embed import EmbeddingDimensionError, get_embedder


@pytest.fixture(autouse=True)
def _isolate_modelscope_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离仓库测试环境, 确保断言来自字段默认值。"""
    for name in (
        "SCI_RAG_EMBEDDING_PROVIDER",
        "SCI_RAG_EMBEDDING_MODEL",
        "SCI_RAG_EMBEDDING_DIM",
        "SCI_RAG_MODELSCOPE_DEVICE",
        "SCI_RAG_MODELSCOPE_CACHE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _fresh_modelscope_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试使用独立的进程级模型缓存。"""
    from sci_rag.embed import modelscope as modelscope_embed

    monkeypatch.setattr(modelscope_embed, "_MODEL_CACHE", {}, raising=False)
    monkeypatch.setattr(modelscope_embed, "_CACHE_LOCK", threading.Lock(), raising=False)


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "embedding_provider": "modelscope",
        "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
        "embedding_dim": 32,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class RecordingModel:
    """记录 encode 参数并返回可控维度的原始向量。"""

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.encode_calls: list[tuple[list[str], dict[str, Any]]] = []
        self.encode_thread_ids: list[int] = []

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.encode_calls.append((list(texts), kwargs))
        self.encode_thread_ids.append(threading.get_ident())
        return [[float(self.dim)] + [0.0] * (self.dim - 1) for _ in texts]


def _injected_dependencies(
    dim: int,
    *,
    load_gate: Callable[[], None] | None = None,
) -> tuple[
    Callable[..., str],
    Callable[..., RecordingModel],
    list[tuple[str, str | None]],
    list[tuple[str, str | None]],
]:
    download_calls: list[tuple[str, str | None]] = []
    load_calls: list[tuple[str, str | None]] = []

    def download(model_id: str, *, cache_dir: str | None) -> str:
        download_calls.append((model_id, cache_dir))
        return rf"C:\modelscope-cache\{model_id}"

    def load(path: str, *, device: str | None) -> RecordingModel:
        load_calls.append((path, device))
        if load_gate is not None:
            load_gate()
        return RecordingModel(dim)

    return download, load, download_calls, load_calls


def test_constructor_defers_download_and_load() -> None:
    from sci_rag.embed.modelscope import ModelScopeEmbedder

    download, load, download_calls, load_calls = _injected_dependencies(32)
    embedder = ModelScopeEmbedder(
        _settings(),
        snapshot_downloader=download,
        sentence_transformer_loader=load,
    )

    assert embedder.model is None
    assert embedder.local_path is None
    assert download_calls == []
    assert load_calls == []


async def test_concurrent_first_embeds_load_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sci_rag.embed import modelscope as modelscope_embed

    concurrent_phase = threading.Event()
    both_ensure_started = threading.Event()

    def load_gate() -> None:
        if concurrent_phase.is_set() and not both_ensure_started.wait(2.0):
            raise AssertionError("both first-embed calls did not reach model loading")

    download, load, download_calls, load_calls = _injected_dependencies(
        32,
        load_gate=load_gate,
    )
    first = modelscope_embed.ModelScopeEmbedder(
        _settings(),
        snapshot_downloader=download,
        sentence_transformer_loader=load,
    )
    second = modelscope_embed.ModelScopeEmbedder(
        _settings(),
        snapshot_downloader=download,
        sentence_transformer_loader=load,
    )
    ensure_starts = 0
    real_to_thread = asyncio.to_thread

    async def recording_to_thread(
        func: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        nonlocal ensure_starts
        if getattr(func, "__name__", "") == "_ensure_model":
            ensure_starts += 1
            if ensure_starts == 2:
                both_ensure_started.set()
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording_to_thread)
    concurrent_phase.set()

    async def embed_with(embedder: Any) -> list[list[float]]:
        return await embedder.embed(["single-flight"], task="document")

    await asyncio.gather(embed_with(first), embed_with(second))

    assert download_calls == [("Qwen/Qwen3-Embedding-0.6B", None)]
    assert len(load_calls) == 1
    assert first.model is second.model
    assert first.model is not None
    assert first.model.encode_thread_ids


async def test_cache_key_separates_cache_directories() -> None:
    from sci_rag.embed.modelscope import ModelScopeEmbedder

    download, load, download_calls, load_calls = _injected_dependencies(32)
    first = ModelScopeEmbedder(
        _settings(modelscope_cache_dir=r"C:\cache-one"),
        snapshot_downloader=download,
        sentence_transformer_loader=load,
    )
    second = ModelScopeEmbedder(
        _settings(modelscope_cache_dir=r"C:\cache-two"),
        snapshot_downloader=download,
        sentence_transformer_loader=load,
    )

    await first.embed(["one"], task="document")
    await second.embed(["two"], task="document")

    assert download_calls == [
        ("Qwen/Qwen3-Embedding-0.6B", r"C:\cache-one"),
        ("Qwen/Qwen3-Embedding-0.6B", r"C:\cache-two"),
    ]
    assert len(load_calls) == 2


@pytest.mark.parametrize(
    "invalid_device",
    ["", "   ", "gpu", "cuda:", "cuda:-1", "cuda:1.0"],
)
def test_invalid_modelscope_device_is_rejected(invalid_device: str) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, modelscope_device=invalid_device)

    assert caught.value.errors()[0]["loc"] == ("modelscope_device",)


@pytest.mark.parametrize(
    ("raw_device", "normalized_device"),
    [("AUTO", "auto"), (" CPU ", "cpu"), ("CUDA:1", "cuda:1")],
)
def test_modelscope_device_values_are_normalized(raw_device: str, normalized_device: str) -> None:
    settings = Settings(_env_file=None, modelscope_device=raw_device)
    assert settings.modelscope_device == normalized_device


async def test_get_embedder_dispatches_to_modelscope_with_shipped_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, embedding_provider="modelscope")
    assert settings.modelscope_device == "auto"
    assert settings.modelscope_cache_dir is None

    import sci_rag.embed.modelscope as modelscope_embed

    download_calls: list[tuple[str, str | None]] = []
    load_calls: list[tuple[str, str | None]] = []

    def download(model_id: str, *, cache_dir: str | None) -> str:
        download_calls.append((model_id, cache_dir))
        return r"C:\modelscope-cache\qwen3"

    def load(path: str, *, device: str | None) -> RecordingModel:
        load_calls.append((path, device))
        return RecordingModel(settings.embedding_dim)

    monkeypatch.setattr(modelscope_embed, "_download_snapshot", download)
    monkeypatch.setattr(modelscope_embed, "_load_sentence_transformer", load)

    embedder = get_embedder(settings)

    assert isinstance(embedder, modelscope_embed.ModelScopeEmbedder)
    assert embedder.version == "Qwen/Qwen3-Embedding-0.6B@1024"
    assert embedder.dim == 1024
    assert download_calls == []
    assert load_calls == []

    await embedder.embed(["dispatch"], task="document")

    assert download_calls == [("Qwen/Qwen3-Embedding-0.6B", None)]
    assert load_calls == [(r"C:\modelscope-cache\qwen3", None)]


@pytest.mark.parametrize(
    ("configured_device", "expected_loader_device"),
    [
        pytest.param("auto", None, id="auto-selects-none"),
        pytest.param("cpu", "cpu", id="explicit-cpu"),
        pytest.param("cuda:1", "cuda:1", id="explicit-cuda-index"),
    ],
)
async def test_loader_device_mapping(
    configured_device: str,
    expected_loader_device: str | None,
) -> None:
    from sci_rag.embed.modelscope import ModelScopeEmbedder

    download, load, download_calls, load_calls = _injected_dependencies(32)
    embedder = ModelScopeEmbedder(
        _settings(modelscope_device=configured_device),
        snapshot_downloader=download,
        sentence_transformer_loader=load,
    )

    assert download_calls == []
    assert load_calls == []
    await embedder.embed(["device"], task="document")

    expected_path = rf"C:\modelscope-cache\{_settings().embedding_model}"
    assert load_calls == [(expected_path, expected_loader_device)]


async def test_embed_runs_encode_in_worker_and_forwards_cache_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sci_rag.embed import modelscope as modelscope_embed

    cache_dir = r"C:\modelscope-cache\custom"
    download, load, download_calls, load_calls = _injected_dependencies(32)
    embedder = modelscope_embed.ModelScopeEmbedder(
        _settings(modelscope_cache_dir=cache_dir),
        snapshot_downloader=download,
        sentence_transformer_loader=load,
    )
    real_to_thread = asyncio.to_thread
    to_thread_calls: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []

    async def recording_to_thread(
        func: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        to_thread_calls.append((func, args, dict(kwargs)))
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording_to_thread)
    loop_thread_id = threading.get_ident()

    await embedder.embed(["worker-thread"], task="document")

    model = embedder.model
    assert isinstance(model, RecordingModel)
    assert download_calls == [("Qwen/Qwen3-Embedding-0.6B", cache_dir)]
    assert load_calls[0][1] is None
    encode_calls = [call for call in to_thread_calls if call[0] == model.encode]
    assert len(to_thread_calls) == 2
    assert len(encode_calls) == 1
    assert encode_calls[0][1] == (["worker-thread"],)
    assert model.encode_thread_ids and model.encode_thread_ids[0] != loop_thread_id


async def test_query_uses_prompt_and_document_has_no_prompt() -> None:
    from sci_rag.embed.modelscope import ModelScopeEmbedder

    download, load, download_calls, load_calls = _injected_dependencies(32)
    embedder = ModelScopeEmbedder(
        _settings(),
        snapshot_downloader=download,
        sentence_transformer_loader=load,
    )

    [query_vector] = await embedder.embed(["检索问题"], task="query")
    [document_vector] = await embedder.embed(["语料段落"], task="document")

    model = embedder.model
    assert isinstance(model, RecordingModel)
    assert model.encode_calls[0][1]["prompt_name"] == "query"
    assert "prompt_name" not in model.encode_calls[1][1]
    assert len(download_calls) == 1
    assert len(load_calls) == 1
    assert query_vector[0] == 1.0
    assert document_vector[0] == 1.0


async def test_wrong_output_dimension_raises_embedding_dimension_error() -> None:
    from sci_rag.embed.modelscope import ModelScopeEmbedder

    download, load, _, _ = _injected_dependencies(16)
    embedder = ModelScopeEmbedder(
        _settings(embedding_dim=32),
        snapshot_downloader=download,
        sentence_transformer_loader=load,
    )

    with pytest.raises(EmbeddingDimensionError, match=r"vector\(32\)"):
        await embedder.embed(["x"], task="document")


async def test_missing_modelscope_dependency_names_the_install_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sci_rag.embed.modelscope import ModelScopeEmbedder

    monkeypatch.setitem(sys.modules, "modelscope", None)
    embedder = ModelScopeEmbedder(_settings())
    with pytest.raises(RuntimeError, match=r"uv sync --extra modelscope-embedding"):
        await embedder.embed(["x"], task="document")


async def test_missing_sentence_transformers_dependency_names_the_install_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sci_rag.embed.modelscope import ModelScopeEmbedder

    download, _, _, _ = _injected_dependencies(32)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    embedder = ModelScopeEmbedder(_settings(), snapshot_downloader=download)
    with pytest.raises(RuntimeError, match=r"uv sync --extra modelscope-embedding"):
        await embedder.embed(["x"], task="document")
