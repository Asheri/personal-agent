"""REST contract tests: shapes, auth, scopes, rate limits, problem+json."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_query_returns_items_traces_and_request_id(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/v1/query",
        json={"query": "rice straw availability in the Colusa Basin", "top_k": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"], "expected results from the demo corpus"
    assert body["items"][0]["title"]
    assert body["items"][0]["license_class"] == "public"
    assert {t["stage"] for t in body["traces"]} == {
        "vector",
        "keyword",
        "graph",
        "community",
        "hyde",
        "rerank",
    }
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]


async def test_query_can_omit_content(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/v1/query", json={"query": "rice straw", "include_content": False}
    )
    assert response.status_code == 200
    assert all(item["content"] is None for item in response.json()["items"])


async def test_validation_errors_are_problem_json(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post("/v1/query", json={"query": ""})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "invalid_request"


async def test_missing_key_is_401_with_www_authenticate(secured_client) -> None:  # type: ignore[no-untyped-def]
    response = await secured_client.post("/v1/query", json={"query": "rice"})
    assert response.status_code == 401
    assert response.json()["code"] == "missing_key"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_unknown_key_is_401(secured_client) -> None:  # type: ignore[no-untyped-def]
    response = await secured_client.post(
        "/v1/query", json={"query": "rice"}, headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_key"


async def test_scope_enforcement(secured_client) -> None:  # type: ignore[no-untyped-def]
    ok = await secured_client.post(
        "/v1/query", json={"query": "rice"}, headers={"Authorization": "Bearer query-key"}
    )
    assert ok.status_code == 200
    forbidden = await secured_client.get(
        "/v1/documents", headers={"Authorization": "Bearer query-key"}
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "insufficient_scope"


async def test_rate_limit_returns_429_with_retry_after(secured_client, frozen_minute) -> None:  # type: ignore[no-untyped-def]
    headers = {"Authorization": "Bearer limited-key"}
    for _ in range(2):
        assert (
            await secured_client.post("/v1/query", json={"query": "rice"}, headers=headers)
        ).status_code == 200
    third = await secured_client.post("/v1/query", json={"query": "rice"}, headers=headers)
    assert third.status_code == 429
    assert third.json()["code"] == "rate_limited"
    assert int(third.headers["Retry-After"]) >= 1


async def test_a_budget_refills_when_the_wall_clock_minute_turns(  # type: ignore[no-untyped-def]
    secured_client, frozen_minute
) -> None:
    """The window is wall-clock, not per-caller, and that is worth asserting.

    It is also what made these tests flaky: three requests that straddled a
    minute boundary reset the counter, so the third returned 200 and the run
    failed for reasons that had nothing to do with the change under test.
    Pinning the clock moves that behavior from an accident into a test.
    """
    headers = {"Authorization": "Bearer limited-key"}
    for _ in range(2):
        assert (
            await secured_client.post("/v1/query", json={"query": "rice"}, headers=headers)
        ).status_code == 200
    assert (
        await secured_client.post("/v1/query", json={"query": "rice"}, headers=headers)
    ).status_code == 429

    frozen_minute.advance(60)

    assert (
        await secured_client.post("/v1/query", json={"query": "rice"}, headers=headers)
    ).status_code == 200


async def test_same_prefix_keys_do_not_share_a_rate_limit_bucket(
    secured_client, frozen_minute
) -> None:  # type: ignore[no-untyped-def]
    """F-017: two callers whose keys begin alike are still two callers.

    Both keys allow one request a minute. The first spends its own budget.
    The second must still get its own, because a rate limit that keyed off
    the first six characters let either caller throttle the other.
    """
    first = {"Authorization": "Bearer shared-prefix-first"}
    second = {"Authorization": "Bearer shared-prefix-second"}

    assert (
        await secured_client.post("/v1/query", json={"query": "rice"}, headers=first)
    ).status_code == 200
    assert (
        await secured_client.post("/v1/query", json={"query": "rice"}, headers=first)
    ).status_code == 429

    independent = await secured_client.post("/v1/query", json={"query": "rice"}, headers=second)
    assert independent.status_code == 200, "a same-prefix key spent another key's budget"


async def test_one_key_still_accumulates_against_its_own_limit(secured_client) -> None:  # type: ignore[no-untyped-def]
    """Isolating buckets must not accidentally give every request a fresh one."""
    headers = {"Authorization": "Bearer shared-prefix-second"}
    assert (
        await secured_client.post("/v1/query", json={"query": "rice"}, headers=headers)
    ).status_code == 200
    repeated = await secured_client.post("/v1/query", json={"query": "rice"}, headers=headers)
    assert repeated.status_code == 429
    assert repeated.json()["code"] == "rate_limited"
    assert int(repeated.headers["Retry-After"]) >= 1


async def test_corpus_manifest_is_public_even_when_auth_is_on(secured_client) -> None:  # type: ignore[no-untyped-def]
    response = await secured_client.get("/v1/corpus-manifest")
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["kit"] == "sci-rag-kit"
    assert manifest["stats"]["documents"] == 5
    assert manifest["retrieval"]["fusion"] == "weighted_rrf"
    assert manifest["endpoints"]["mcp"].endswith("/mcp")


async def test_mcp_mount_requires_auth_when_keys_configured(secured_client) -> None:  # type: ignore[no-untyped-def]
    # Note the trailing slash: the parent router 307-redirects bare /mcp
    # before the mount (and its auth wrapper) ever runs.
    response = await secured_client.post("/mcp/", json={})
    assert response.status_code == 401
    assert response.json()["code"] == "missing_key"


async def test_health_and_status(client) -> None:  # type: ignore[no-untyped-def]
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["database"] is True

    status = await client.get("/v1/status")
    assert status.status_code == 200
    body = status.json()
    assert body["documents"] == 5
    assert body["entities"] == 2
    assert body["license_classes"] == {"public": 5}


async def test_documents_catalog_and_detail(client) -> None:  # type: ignore[no-untyped-def]
    listing = await client.get("/v1/documents", params={"search": "rice"})
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    document = body["documents"][0]
    assert document["title"].startswith("Colusa Basin Rice Straw")

    detail = await client.get(f"/v1/documents/{document['id']}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["chunks"], "expected chunk previews"
    assert detail_body["formatted_citation"]

    missing = await client.get("/v1/documents/doesnotexist")
    assert missing.status_code == 404
    assert missing.json()["code"] == "document_not_found"


async def test_query_metadata_filters(client) -> None:  # type: ignore[no-untyped-def]
    """The v0.3 filters ride through the schema, the service, and every layer.

    The demo corpus is two 2023 documents and three 2024 ones, so a year
    bound is a real cut, not a no-op.
    """
    recent = await client.post(
        "/v1/query", json={"query": "residue", "top_k": 10, "year_min": 2024}
    )
    assert recent.status_code == 200
    older = await client.post("/v1/query", json={"query": "residue", "top_k": 10, "year_max": 2023})
    assert older.status_code == 200
    recent_docs = {item["document_id"] for item in recent.json()["items"]}
    older_docs = {item["document_id"] for item in older.json()["items"]}
    assert recent_docs and older_docs
    assert not (recent_docs & older_docs), "year bounds returned overlapping documents"

    by_author = await client.post(
        "/v1/query",
        json={"query": "residue", "top_k": 10, "authors": ["Demo Region Policy Desk"]},
    )
    assert by_author.status_code == 200
    assert by_author.json()["items"], "author filter matched nothing it should have matched"

    unknown_journal = await client.post(
        "/v1/query", json={"query": "residue", "journals": ["Journal of Nothing"]}
    )
    assert unknown_journal.status_code == 200
    assert unknown_journal.json()["items"] == []


async def test_year_filter_skips_the_community_stage(client) -> None:  # type: ignore[no-untyped-def]
    """Community summaries aggregate across documents before any scope is
    known, so a metadata filter has to disable that layer like every other
    restriction does."""
    response = await client.post(
        "/v1/query", json={"query": "residue", "profile": "deep", "year_min": 2024}
    )
    assert response.status_code == 200
    community = next(t for t in response.json()["traces"] if t["stage"] == "community")
    assert community["status"] == "skipped"


async def test_answer_accepts_metadata_filters(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/v1/answer",
        json={"query": "residue availability", "stream": False, "year_min": 2024},
    )
    assert response.status_code == 200
    assert response.json()["answer"]


async def test_year_bounds_are_validated(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.post("/v1/query", json={"query": "residue", "year_min": 99})
    assert response.status_code == 422


async def test_an_api_key_is_accepted_from_a_header_cloud_run_does_not_eat(secured_client) -> None:  # type: ignore[no-untyped-def]
    """`Authorization` is unusable on the platform this repo documents deploying to.

    Google's Cloud Run frontend inspects `Authorization: Bearer` and rejects
    anything that is not a Google identity token, before the request reaches
    the container. On a real deploy that meant the kit's own API keys could
    not be used at all: a request carrying one got an HTML 401 from Google,
    while a request carrying nothing reached the app and got a correct
    `missing_key`.

    `docs/api.md` and `docs/deploy-gcp.md` were each right and jointly
    impossible. So the key is also accepted from a header no platform claims.
    """
    response = await secured_client.post(
        "/v1/query", json={"query": "rice straw"}, headers={"X-API-Key": "full-key"}
    )

    assert response.status_code == 200
    assert response.json()["items"]


async def test_the_explicit_key_header_wins_when_both_are_sent(secured_client) -> None:  # type: ignore[no-untyped-def]
    """Precedence is explicit, and it now favours the caller's own header.

    This test previously asserted the opposite, on the reasoning that
    `Authorization` was the documented header and local behavior should not
    change. That premise does not survive a deployment. A private Cloud Run
    service requires a Google identity token in `Authorization`, so preferring
    it meant the identity token shadowed the kit key and every authenticated
    request returned 401 `invalid_key`. The issue #189 live qualification
    reproduced that against a real service and found no header combination
    that worked.

    `X-API-Key` is the caller naming the credential it means. `Authorization`
    may have been set by infrastructure the caller does not control, so it is
    the weaker claim when both arrive.
    """
    response = await secured_client.post(
        "/v1/query",
        json={"query": "rice straw"},
        headers={"Authorization": "Bearer not-a-real-key", "X-API-Key": "query-key"},
    )

    assert response.status_code == 200


async def test_the_fallback_header_enforces_scopes_the_same_way(secured_client) -> None:  # type: ignore[no-untyped-def]
    """A second door must not be a weaker door.

    `query-key` holds `retrieval:query` and not `retrieval:answer`, so the
    answer route must refuse it through either header identically.
    """
    response = await secured_client.post(
        "/v1/answer", json={"query": "rice straw"}, headers={"X-API-Key": "query-key"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "insufficient_scope"


async def test_the_mcp_mount_accepts_the_fallback_header_too(secured_client) -> None:  # type: ignore[no-untyped-def]
    """The MCP mount reads the header itself, so it can drift from REST.

    It did: the two extract the token in different files. This pins that a
    key working on one front door works on the other.
    """
    response = await secured_client.post("/mcp", headers={"X-API-Key": "full-key"})

    assert response.status_code != 401
