"""ModelScope Qwen3 本地嵌入器。

下载与模型加载都是同步阻塞操作; 编码显式移入工作线程, 避免占用事件循环。
可选依赖延迟导入, 使默认安装仍可离线使用其他嵌入器。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, Protocol

from sci_rag.config import Settings
from sci_rag.embed.provider import EmbeddingProvider, EmbeddingTask, l2_normalize

_INSTALL_COMMAND = "uv sync --extra modelscope-embedding"


class SentenceTransformerLike(Protocol):
    """仅依赖嵌入器实际使用的 SentenceTransformer 编码接口。"""

    def encode(self, sentences: list[str], /, **kwargs: Any) -> Any: ...


SnapshotDownloader = Callable[..., str]
SentenceTransformerLoader = Callable[..., SentenceTransformerLike]
ModelCacheKey = tuple[str, int, str, str | None]
LoadedModel = tuple[str, SentenceTransformerLike]
ModelLoader = Callable[[], LoadedModel]

# 进程级缓存按模型配置共享; Future 同时承担加载完成通知和失败传播。
_MODEL_CACHE: dict[ModelCacheKey, Future[LoadedModel]] = {}
_CACHE_LOCK = threading.Lock()


def _download_snapshot(model_id: str, *, cache_dir: str | None) -> str:
    try:
        from modelscope import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "ModelScope embedding needs the 'modelscope-embedding' extra. "
            f"Install it with: {_INSTALL_COMMAND}"
        ) from exc
    return snapshot_download(model_id, cache_dir=cache_dir)


def _load_sentence_transformer(local_path: str, *, device: str | None) -> SentenceTransformerLike:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "ModelScope embedding needs the 'modelscope-embedding' extra. "
            f"Install it with: {_INSTALL_COMMAND}"
        ) from exc
    return SentenceTransformer(local_path, device=device)


def _get_shared_model(key: ModelCacheKey, load_model: ModelLoader) -> LoadedModel:
    with _CACHE_LOCK:
        cached = _MODEL_CACHE.get(key)
        owner = cached is None
        if cached is None:
            cached = Future()
            _MODEL_CACHE[key] = cached

    if not owner:
        return cached.result()

    try:
        loaded = load_model()
    except BaseException as exc:
        with _CACHE_LOCK:
            if _MODEL_CACHE.get(key) is cached:
                _MODEL_CACHE.pop(key, None)
        cached.set_exception(exc)
        raise

    cached.set_result(loaded)
    return loaded


class ModelScopeEmbedder(EmbeddingProvider):
    """加载一次本地 Qwen3 模型, 并按任务提示生成归一化向量。"""

    def __init__(
        self,
        settings: Settings,
        *,
        snapshot_downloader: SnapshotDownloader | None = None,
        sentence_transformer_loader: SentenceTransformerLoader | None = None,
    ) -> None:
        self._settings = settings
        self._download = snapshot_downloader or _download_snapshot
        self._load = sentence_transformer_loader or _load_sentence_transformer
        self.model_id = settings.embedding_model
        self.dim = settings.embedding_dim
        self.version = f"{self.model_id}@{self.dim}"
        self.local_path: str | None = None
        self.model: SentenceTransformerLike | None = None

    def _ensure_model(self) -> LoadedModel:
        if self.model is not None and self.local_path is not None:
            return self.local_path, self.model

        key: ModelCacheKey = (
            self.model_id,
            self.dim,
            self._settings.modelscope_device,
            self._settings.modelscope_cache_dir,
        )

        def load_model() -> LoadedModel:
            local_path = self._download(
                self.model_id,
                cache_dir=self._settings.modelscope_cache_dir,
            )
            device = (
                None
                if self._settings.modelscope_device == "auto"
                else self._settings.modelscope_device
            )
            return local_path, self._load(local_path, device=device)

        return _get_shared_model(key, load_model)

    async def embed(self, texts: list[str], *, task: EmbeddingTask) -> list[list[float]]:
        model = self.model
        if model is None:
            local_path, model = await asyncio.to_thread(self._ensure_model)
            self.local_path = local_path
            self.model = model

        encode_kwargs: dict[str, Any] = {
            "convert_to_numpy": True,
            "normalize_embeddings": False,
        }
        if task == "query":
            encode_kwargs["prompt_name"] = "query"

        assert model is not None
        raw_vectors = await asyncio.to_thread(model.encode, texts, **encode_kwargs)
        results: list[list[float]] = []
        for raw_vector in raw_vectors:
            vector = [float(value) for value in raw_vector]
            results.append(self.assert_dimension(l2_normalize(vector)))
        if len(results) != len(texts):
            raise RuntimeError(
                f"ModelScope returned {len(results)} vectors for {len(texts)} texts."
            )
        return results
