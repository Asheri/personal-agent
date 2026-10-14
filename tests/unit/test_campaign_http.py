import httpx
import pytest

from sci_rag.campaigns.http import PoliteHttpClient


@pytest.mark.asyncio
async def test_polite_client_identifies_itself_and_retries_429() -> None:
    requests: list[httpx.Request] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0.25"})
        return httpx.Response(200, json={"status": "ok"})

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="researcher@example.org",
            client=transport,
            sleep=sleep,
            max_retries=1,
            requests_per_second=None,
        )
        payload = await client.get_json("https://api.crossref.org/works/10.1000%2Fcurrent")

    assert payload == {"status": "ok"}
    assert len(requests) == 2
    assert requests[0].url.params["mailto"] == "researcher@example.org"
    assert "mailto:researcher@example.org" in requests[0].headers["User-Agent"]
    assert delays == [0.25]


@pytest.mark.asyncio
async def test_polite_client_spaces_requests_at_the_configured_rate() -> None:
    now = 0.0
    delays: list[float] = []

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        delays.append(delay)
        now += delay

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="researcher@example.org",
            client=transport,
            sleep=sleep,
            clock=clock,
            requests_per_second=2,
        )
        await client.get_json("https://api.crossref.org/works/one")
        await client.get_json("https://api.crossref.org/works/two")

    assert delays == [0.5]


@pytest.mark.asyncio
async def test_polite_client_retries_server_errors_then_raises() -> None:
    requests = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500, json={"message": "temporary failure"})

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="researcher@example.org",
            client=transport,
            sleep=sleep,
            max_retries=2,
            requests_per_second=None,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_json("https://api.openalex.org/works")

    assert requests == 3
    assert delays == [0.5, 1.0]


@pytest.mark.asyncio
async def test_polite_client_uses_unpaywall_email_without_mailto() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
        client = PoliteHttpClient(
            mailto="researcher@example.org",
            client=transport,
            requests_per_second=None,
        )
        await client.get_json(
            "https://api.unpaywall.org/v2/10.7717/peerj.4375",
            params={"email": "researcher@example.org"},
        )

    assert requests[0].url.params["email"] == "researcher@example.org"
    assert "mailto" not in requests[0].url.params
