"""Evaluation-only local runtime adapters; application defaults are unchanged."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from sci_rag.embed.provider import EmbeddingProvider, EmbeddingTask, l2_normalize
from sci_rag.llm import LLMClient


class LocalSemanticEmbedder(EmbeddingProvider):
    dim = 1024
    version = "Qwen3-Embedding-0.6B-GGUF@370f27d-Q8_0-last-1024"

    def __init__(self, base_url: str) -> None:
        if not base_url.startswith("http://127.0.0.1:"):
            raise ValueError("Evaluation endpoint must be task-owned loopback")
        self.base_url = base_url

    async def embed(self, texts: list[str], *, task: EmbeddingTask) -> list[list[float]]:
        vectors = []
        async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
            for value in texts:
                if "TEST-CANARY-913" in value or "TEST-CANARY-927" in value:
                    raise AssertionError("Protected source reached semantic embedding")
                if task == "query":
                    value = (
                        "Instruct: Given a file search query, retrieve relevant passages that answer the query\nQuery: "
                        + value
                    )
                response = await client.post(
                    self.base_url + "/embeddings", json={"input": value, "model": "local"}
                )
                response.raise_for_status()
                raw = response.json()["data"][0]["embedding"]
                vectors.append(l2_normalize(self.assert_dimension(raw)))
        return vectors


class RecordedLLM(LLMClient):
    def __init__(
        self, client: LLMClient, records: list[dict[str, Any]], output: Path | None = None
    ) -> None:
        self.client, self.records = client, records
        self.model, self.spec = client.model, client.spec
        self.output = output
        self.blocked_attempts = 0

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> str:
        if "TEST-CANARY-913" in prompt or "TEST-CANARY-927" in prompt:
            self.blocked_attempts += 1
            raise AssertionError("Unknown/private source reached a model prompt")
        started = time.perf_counter()
        raw = await self.client.generate(
            prompt, system=system, temperature=0, max_tokens=max_tokens, json_mode=json_mode
        )
        self.records.append(
            dict(
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                response=raw,
                elapsed_seconds=time.perf_counter() - started,
            )
        )
        if self.output is not None:
            with self.output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(self.records[-1], ensure_ascii=False) + "\n")
        print("Completed generation call", len(self.records), flush=True)
        return raw

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ):  # type: ignore[no-untyped-def]
        if "TEST-CANARY-913" in prompt or "TEST-CANARY-927" in prompt:
            self.blocked_attempts += 1
            raise AssertionError("Protected source reached answer generation")
        return self.client.stream(prompt, system=system, temperature=0, max_tokens=max_tokens)
