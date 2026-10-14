"""DeepSeek 生成, 使用其专用凭据通过 OpenAI 兼容协议访问。"""

from __future__ import annotations

from sci_rag.config import Settings
from sci_rag.llm import resolve_llm_api_key_override, settings_with_llm_api_key
from sci_rag.llm.openai_compat import OpenAICompatLLM
from sci_rag.llm.spec import ModelSpec


class DeepSeekLLM(OpenAICompatLLM):
    """把 DeepSeek 凭据映射到共享的 OpenAI 兼容实现。"""

    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        api_key_override: str | None = None,
    ) -> None:
        if api_key_override:
            resolved_override = resolve_llm_api_key_override(
                settings,
                "deepseek",
                api_key_override,
            )
            if resolved_override:
                settings = settings_with_llm_api_key(
                    settings,
                    "deepseek",
                    resolved_override,
                )
        key = settings.deepseek_api_key
        if not key:
            raise RuntimeError("DeepSeek cannot generate without SCI_RAG_DEEPSEEK_API_KEY.")
        endpoint = settings.model_copy(
            update={
                "openai_api_key": key,
                "openai_base_url": settings.deepseek_base_url,
                "gcp_project": None,
            }
        )
        super().__init__(endpoint, model=model)
        self.spec = ModelSpec("deepseek", self.model)
