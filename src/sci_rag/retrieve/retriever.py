"""The retrieval orchestrator: five layers, run in parallel, fused once.

Callers use one method and one result type:

    retriever = Retriever()
    result = await retriever.retrieve("how much rice straw does Colusa produce?")

What happens inside:

* The enabled layers run concurrently, each against its own database
  session, each under its own timeout. A slow or failing layer degrades
  (and says so in the trace); it never takes the request down with it.
* The query is embedded once and shared by the layers that need it.
* Candidates fuse by weighted reciprocal rank, then the winners are
  resolved into full items with title, citation, and license class.

Two profiles set the defaults: "interactive" (vector + keyword only,
short timeouts, query-embedding cache on) keeps a human waiting as briefly
as possible; "deep" (all five layers, long timeouts) is for agents, batch
jobs, and evaluation. Explicit ``include_*`` flags override either.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sci_rag.config import Settings, get_settings
from sci_rag.db.engine import get_session_factory
from sci_rag.db.models import Chunk, Document, KgCommunity
from sci_rag.domain import DomainProfile, RerankerTuning, load_domain
from sci_rag.embed import EmbeddingProvider, QueryEmbeddingCache, get_embedder
from sci_rag.llm import LLMClient, get_llm
from sci_rag.retrieve.fusion import rrf_fuse
from sci_rag.retrieve.rerank import Reranker, build_reranker
from sci_rag.retrieve.router import route
from sci_rag.retrieve.stages import (
    community_stage,
    graph_stage,
    hyde_stage,
    keyword_stage,
    vector_stage,
)
from sci_rag.retrieve.types import (
    Key,
    RetrievalResult,
    RetrievalScope,
    RetrievedItem,
    StageTrace,
    scope_conditions,
)

log = structlog.get_logger(__name__)

Profile = str  # "interactive" | "deep"

#: Stages that make a provider round trip before they reach SQL. Vector and
#: community await the shared query embedding, graph extracts query entities
#: with a model, and HyDE generates a passage and then embeds it. Keyword is
#: the only purely local stage.
PROVIDER_BACKED_STAGES = frozenset({"vector", "community", "graph", "hyde"})


def stage_budget_s(stage: str, profile_timeout_s: float, settings: Settings) -> float:
    """How long ``stage`` is allowed, for this profile.

    The profile budget bounds a stage's own database work, and that is the
    right shape for it: a slow SQL layer should not hold a request open. A
    remote call has a different latency profile entirely, so a stage that has
    to make one gets that budget in addition rather than out of the same
    allowance. Charging the two to one number is what made a supported live
    Vertex project return nothing at all: a 33-second query embedding cannot
    fit in 30 seconds, and every stage sharing that embedding failed with it.
    """
    if stage in PROVIDER_BACKED_STAGES:
        return profile_timeout_s + settings.provider_call_timeout_s
    return profile_timeout_s


class Retriever:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        domain: DomainProfile | None = None,
        embedder: EmbeddingProvider | None = None,
        llm: LLMClient | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.domain = domain or load_domain(self.settings.domain_dir)
        self.embedder = embedder or get_embedder(self.settings)
        self._llm = llm
        self.session_factory = session_factory or get_session_factory()
        self.query_cache = QueryEmbeddingCache(self.embedder)

    @property
    def llm(self) -> LLMClient:
        """Built on first use so no-credential runs work until a layer needs it."""
        if self._llm is None:
            self._llm = get_llm(self.settings, role="extraction")
        return self._llm

    def can_generate(self) -> bool:
        """Whether a model is reachable for the layers that call one.

        The question is about the client, not about the settings. A caller
        that supplied one has generation whatever the environment says, which
        is how the evaluation harness and the test suite drive graph and HyDE
        with a stub under exactly the configuration the wizard writes for
        ``credentials: offline``.
        """
        return self._llm is not None or not self.settings.is_offline()

    async def retrieve(
        self,
        query: str,
        *,
        profile: Profile = "deep",
        limit: int = 8,
        scope: RetrievalScope | None = None,
        include_vector: bool | None = None,
        include_keyword: bool | None = None,
        include_graph: bool | None = None,
        include_community: bool | None = None,
        include_hyde: bool | None = None,
        include_rerank: bool | None = None,
        graph_confidence_weighted: bool | None = None,
        graph_include_citations: bool | None = None,
        use_query_cache: bool | None = None,
    ) -> RetrievalResult:
        scope = scope or RetrievalScope()
        query = query.strip()
        if not query:
            return RetrievalResult(items=[], traces=[], profile=profile)
        if scope.denies_all():
            # Fail closed before any embedding or database work.
            return RetrievalResult(
                items=[],
                traces=[StageTrace(stage="scope", status="denied")],
                profile=profile,
            )

        router_trace: StageTrace | None = None
        if profile == "auto":
            # Resolve the plan up front; explicit include_* flags still win
            # below because the router only fills the ones left as None.
            start = time.monotonic()
            decision = await route(query, self.domain)
            router_trace = StageTrace(
                stage="router",
                status="success",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
            profile = decision.profile
            include_graph = include_graph if include_graph is not None else decision.include_graph
            include_community = (
                include_community if include_community is not None else decision.include_community
            )
            include_hyde = include_hyde if include_hyde is not None else decision.include_hyde
            log.info(
                "router_decision",
                profile=profile,
                graph=include_graph,
                community=include_community,
                hyde=include_hyde,
                ambiguous=decision.ambiguous,
            )

        deep = profile == "deep"
        # Vector and keyword are on in both profiles; explicit flags (used by
        # the evaluation harness's ablations) override anything.
        vector_on = include_vector if include_vector is not None else True
        keyword_on = include_keyword if include_keyword is not None else True
        # Graph and HyDE call a model for every query, so a project with none
        # cannot run them. Leaving them on spent one stage timeout each on the
        # credential failure and reported `error`, which reads as a broken
        # deployment rather than the mode the reader chose. An explicit
        # include_* still wins: an ablation that names a stage means it.
        model_layers = self.can_generate()
        graph_on = include_graph if include_graph is not None else (deep and model_layers)
        community_on = include_community if include_community is not None else deep
        hyde_on = include_hyde if include_hyde is not None else (deep and model_layers)
        cache_on = use_query_cache if use_query_cache is not None else not deep
        timeout = (
            self.settings.deep_stage_timeout_s
            if deep
            else self.settings.interactive_stage_timeout_s
        )
        limits = self.domain.config.retrieval.candidate_limits
        graph_tuning = self.domain.config.retrieval.graph

        # Communities aggregate evidence across documents before any scope is
        # known, so a scoped request must not use them (see stage docstring).
        community_scope_blocked = community_on and not scope.is_unrestricted()
        if community_scope_blocked:
            community_on = False

        # Embed the query once; the vector and community layers share this task.
        embedding_task: asyncio.Task[list[float]] | None = None
        if vector_on or community_on:
            embedding_task = asyncio.create_task(
                self.query_cache.embed_query(query, use_cache=cache_on)
            )

        async def _shared_embedding() -> list[float]:
            assert embedding_task is not None
            return await asyncio.shield(embedding_task)

        async def vector_factory() -> list[Key]:
            vector = await _shared_embedding()
            return await vector_stage(self.session_factory, vector, scope, limits.get("vector", 20))

        async def keyword_factory() -> list[Key]:
            return await keyword_stage(
                self.session_factory, query, scope, limits.get("keyword", 20)
            )

        async def graph_factory() -> list[Key]:
            return await graph_stage(
                self.session_factory,
                self.llm,
                self.domain,
                query,
                scope,
                limits.get("graph", 20),
                min_confidence=graph_tuning.min_confidence,
                confidence_weighted=(
                    graph_tuning.confidence_weighted
                    if graph_confidence_weighted is None
                    else graph_confidence_weighted
                ),
                include_citations=(
                    graph_tuning.include_citations
                    if graph_include_citations is None
                    else graph_include_citations
                ),
            )

        async def community_factory() -> list[Key]:
            vector = await _shared_embedding()
            return await community_stage(
                self.session_factory, vector, scope, limits.get("community", 5)
            )

        async def hyde_factory() -> list[Key]:
            return await hyde_stage(
                self.session_factory,
                self.llm,
                self.embedder,
                self.domain,
                query,
                scope,
                limits.get("hyde", 20),
            )

        plan: list[tuple[str, Callable[[], Awaitable[list[Key]]] | None]] = [
            ("vector", vector_factory if vector_on else None),
            ("keyword", keyword_factory if keyword_on else None),
            ("graph", graph_factory if graph_on else None),
            ("community", community_factory if community_on else None),
            ("hyde", hyde_factory if hyde_on else None),
        ]

        stage_runs = [
            self._timed_stage(name, factory, stage_budget_s(name, timeout, self.settings))
            for name, factory in plan
            if factory is not None
        ]
        finished = await asyncio.gather(*stage_runs)

        # Make sure the shared embedding task never outlives the request.
        if embedding_task is not None and not embedding_task.done():
            embedding_task.cancel()

        traces: list[StageTrace] = []
        if router_trace is not None:
            traces.append(router_trace)
        layer_results: dict[str, list[Key]] = {}
        finished_by_name = {name: (keys, trace) for name, keys, trace in finished}
        for name, factory in plan:
            if factory is None:
                status = (
                    "skipped" if name == "community" and community_scope_blocked else "disabled"
                )
                traces.append(StageTrace(stage=name, status=status))
                continue
            keys, trace = finished_by_name[name]
            traces.append(trace)
            layer_results[name] = keys

        rerank_cfg = self.domain.config.retrieval.reranker
        rerank_on = include_rerank if include_rerank is not None else rerank_cfg.enabled

        fused = rrf_fuse(
            layer_results,
            weights=self.domain.config.retrieval.weights,
            k=self.domain.config.retrieval.rrf_k,
            # With rerank on, fuse a wider pool so the reranker has real
            # candidates to promote; the final cut back to `limit` happens
            # after (or instead of) reranking.
            limit=max(limit, rerank_cfg.pool) if rerank_on else limit,
        )
        items = await self._resolve(fused, scope)

        if not rerank_on:
            traces.append(StageTrace(stage="rerank", status="disabled"))
            return RetrievalResult(items=items[:limit], traces=traces, profile=profile)

        items, rerank_trace = await self._rerank(query, items, limit, rerank_cfg)
        traces.append(rerank_trace)
        return RetrievalResult(items=items, traces=traces, profile=profile)

    async def _rerank(
        self,
        query: str,
        items: list[RetrievedItem],
        limit: int,
        cfg: RerankerTuning,
    ) -> tuple[list[RetrievedItem], StageTrace]:
        """Rerank the resolved pool; any failure falls back to fused order."""
        pool = items[: cfg.pool]
        start = time.monotonic()
        status = "success"
        ranked = pool
        try:
            reranker: Reranker = build_reranker(
                cfg.adapter, llm=self.llm, domain=self.domain, model=cfg.model
            )
            ranked = await asyncio.wait_for(
                reranker.rerank(query, pool, top_k=limit), cfg.timeout_s
            )
        except TimeoutError:
            status = "timeout"
            ranked = pool
            log.warning("rerank_timeout", timeout_s=cfg.timeout_s)
        except Exception as exc:
            status = "error"
            ranked = pool
            log.warning("rerank_error", error=type(exc).__name__, detail=str(exc)[:200])
        duration_ms = int((time.monotonic() - start) * 1000)
        trace = StageTrace(
            stage="rerank",
            status=status if ranked else "empty",
            duration_ms=duration_ms,
            candidate_count=len(pool),
        )
        return ranked[:limit], trace

    async def _timed_stage(
        self,
        name: str,
        factory: Callable[[], Awaitable[list[Key]]],
        timeout_s: float,
    ) -> tuple[str, list[Key], StageTrace]:
        start = time.monotonic()
        keys: list[Key] = []
        try:
            keys = await asyncio.wait_for(factory(), timeout_s)
            status = "success" if keys else "empty"
        except TimeoutError:
            status = "timeout"
            log.warning("retrieval_stage_timeout", stage=name, timeout_s=timeout_s)
        except Exception as exc:
            status = "error"
            log.warning(
                "retrieval_stage_error", stage=name, error=type(exc).__name__, detail=str(exc)[:200]
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        return (
            name,
            keys,
            StageTrace(
                stage=name, status=status, duration_ms=duration_ms, candidate_count=len(keys)
            ),
        )

    async def _resolve(self, fused: list, scope: RetrievalScope) -> list[RetrievedItem]:
        chunk_ids = [c.key[1] for c in fused if c.key[0] == "chunk"]
        community_ids = [c.key[1] for c in fused if c.key[0] == "community"]
        chunk_map: dict[str, RetrievedItem] = {}
        community_map: dict[str, RetrievedItem] = {}

        async with self.session_factory() as session:
            if chunk_ids:
                rows = await session.execute(
                    select(
                        Chunk.id,
                        Chunk.document_id,
                        Chunk.content,
                        Chunk.section_path,
                        Chunk.is_table,
                        Document.title,
                        Document.formatted_citation,
                        Document.license_class,
                        Document.source,
                    )
                    .join(Document, Chunk.document_id == Document.id)
                    # Scope was applied inside every stage; re-applying here is
                    # cheap defense in depth.
                    .where(Chunk.id.in_(chunk_ids), *scope_conditions(scope))
                )
                for row in rows:
                    chunk_map[row.id] = RetrievedItem(
                        kind="chunk",
                        id=row.id,
                        score=0.0,
                        layers=[],
                        title=row.title,
                        content=row.content,
                        document_id=row.document_id,
                        section_path=row.section_path,
                        citation=row.formatted_citation,
                        license_class=row.license_class,
                        source=row.source,
                        is_table=row.is_table,
                    )
            if community_ids:
                rows = await session.execute(
                    select(KgCommunity.id, KgCommunity.title, KgCommunity.summary).where(
                        KgCommunity.id.in_(community_ids)
                    )
                )
                for row in rows:
                    community_map[row.id] = RetrievedItem(
                        kind="community",
                        id=row.id,
                        score=0.0,
                        layers=[],
                        title=f"Knowledge graph overview: {row.title}",
                        content=row.summary or "",
                        license_class="aggregate",
                        source="knowledge_graph",
                    )

        items: list[RetrievedItem] = []
        for candidate in fused:
            kind, ref_id = candidate.key
            item = chunk_map.get(ref_id) if kind == "chunk" else community_map.get(ref_id)
            if item is None:
                continue
            item.score = candidate.score
            item.layers = candidate.layers
            items.append(item)
        return items
