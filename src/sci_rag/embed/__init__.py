from sci_rag.config import Settings
from sci_rag.embed.cache import QueryEmbeddingCache
from sci_rag.embed.local_hash import LocalHashEmbedder
from sci_rag.embed.provider import (
    EmbeddingDimensionError,
    EmbeddingProvider,
    EmbeddingTask,
    l2_normalize,
)


def get_embedder(settings: Settings) -> EmbeddingProvider:
    """The embedder selected by ``SCI_RAG_EMBEDDING_PROVIDER``."""
    if settings.embedding_provider == "local-hash":
        return LocalHashEmbedder(settings.embedding_dim)
    if settings.embedding_provider == "modelscope":
        # 延迟导入, 确保默认离线安装不需要 torch 与 ModelScope。
        from sci_rag.embed.modelscope import ModelScopeEmbedder

        return ModelScopeEmbedder(settings)
    # Imported lazily so offline use never touches the Google SDK.
    from sci_rag.embed.google import GoogleEmbedder

    return GoogleEmbedder(settings)


__all__ = [
    "EmbeddingDimensionError",
    "EmbeddingProvider",
    "EmbeddingTask",
    "LocalHashEmbedder",
    "ModelScopeEmbedder",
    "QueryEmbeddingCache",
    "get_embedder",
    "l2_normalize",
]
