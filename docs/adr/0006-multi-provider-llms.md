---
title: "ADR 0006: Hand-written provider adapters"
description: Why each generation provider gets its own adapter, and why embeddings stay Google-only.
---

# ADR 0006: Hand-written provider adapters

Each generation provider gets a hand-written adapter, selected per role. Embeddings stay Google-only, because changing them is a data migration.

**Status:** accepted

## Context

Every generation path in the kit ran on Gemini. `SCI_RAG_LLM_MODEL` named a
model with no way to say whose model it was, so pointing answers at Claude or
Grok meant forking the kit.

Three things pushed against that. Adopters standardizing on Google Cloud can
reach Claude, Grok, Llama, Mistral, and DeepSeek as Vertex partner models
without a new vendor relationship. The evaluation harness grades answers with
the same model family that wrote them, which flatters the score. And the kit
is a template: an adopter who cannot change the backend has to change the
code.

The interface for this already existed. `LLMClient` has three methods, every
consumer takes it by injection, and it had exactly one factory with a handful
of call sites. The open question was not where the interface belongs, but what fills
it.

The obvious alternative was a translation layer such as LiteLLM: one
dependency, roughly a hundred providers, far less code to write.

## Decision

**Hand-written adapters, one module per provider, behind the existing
`LLMClient` ABC.** Three ship: `google`, `anthropic`, and
`openai-compatible`. You select one with a `provider:model` spec, so a bare
model id keeps resolving to `SCI_RAG_LLM_PROVIDER` and configurations written
before this change keep working unedited.

We rejected a translation layer because the provider differences that matter
here are precisely the ones it would smooth over. JSON-mode calls set
`thinking_budget=0` on Gemini for a documented reason: without it, extraction
and judging spend their whole output budget on thought and return empty. The
Claude equivalent is `output_config={"effort": "low"}`. That is a different
knob with different semantics, *not* a translation of the same one. Disabling
thinking on current Claude models can leak reasoning tags into the JSON these
call sites parse. Those models also removed the sampling parameters outright,
so the adapter drops `temperature` entirely. Reaching all of
that through a normalizing layer is harder than writing the hundred lines
directly, and writing them keeps the supported set visible in one file, which
is the same trade-off `get_embedder()` already makes.

`openai-compatible` is the third adapter, and not a dedicated OpenAI one
because Vertex serves its non-Google partner models behind an
OpenAI-compatible endpoint instead of native APIs. One adapter therefore
covers Grok, Llama, Mistral, DeepSeek, every future partner model on that
endpoint, OpenAI itself, and a self-hosted vLLM or Ollama server.

**Embeddings stay Google-only.** Anthropic ships no embedding API. On Vertex
the only managed text embeddings are Google's; everything else requires
deploying and paying for a GPU endpoint in Model Garden. More decisively, an
embedder is not a runtime-swappable choice in this system. A migration bakes
`SCI_RAG_EMBEDDING_DIM` into the pgvector column (ADR 0002), and every chunk
stores the version that produced it. Switching therefore means a migration, a
full re-embed, and an index rebuild. A provider flag would advertise a
configuration change for what is really a data migration.

## Consequences

* Roles resolve independently, so a run can extract with cheap Gemini Flash,
  answer with Claude, and judge with a third provider. Cross-provider judging
  is now a config change, and reports name the answering and grading models so
  the choice is auditable and not merely available.
* Adding a fourth provider means writing an adapter, not registering a plugin.
  The capability table in [extend.md](../extend.md) is the checklist; the
  `temperature` and effort rows are where a new adapter is most likely to get
  it wrong.
* The SDKs are optional extras (`--extra anthropic`, `--extra openai`) that
  the kit imports lazily, so an offline or Google-only install carries neither.
* `retry_async()` holds the one retry policy, and the kit builds the provider
  SDKs with `max_retries=0`, so there is one backoff to reason about and not
  three that compound.
* Bring-your-own-key stays meaningful per provider. It has no meaning against
  Vertex, which authenticates with the operator's Google credentials, so that
  combination raises, and never silently ignores the caller's key.

## Reversal conditions

* The provider SDKs converge far enough that the differences this
  decision exists to preserve, JSON-mode thinking budgets and sampling
  parameters among them, stop being real.
* A translation layer starts shipping those knobs faithfully and stops
  smoothing them into a lowest common denominator.
* A managed non-Google text-embedding API arrives on Vertex, which is
  what makes the embedding half of this decision worth revisiting.
