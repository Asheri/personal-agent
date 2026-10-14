"""Ask the provider whether the partner-model examples the docs name still work.

A model id in a guide has no date on it and nothing re-checks it, so when one
is retired the guide keeps recommending it until a reader trips over it. F-030
is what that looks like from the other side: a finding built from a model card
and a release-notes entry, concluding an example was retired, when a call to
the documented endpoint answered in under a second. Reading a lifecycle page
and asking the endpoint are different kinds of evidence, and this script does
the second one.

It needs credentials, so it is a maintainer command rather than a CI job:

    make providers-check

Every entry below is a model a reader can copy out of `docs/extend.md` or
`.env.example`, the location that serves it, and the date it last answered
both an ordinary generation call and a strict JSON one. A test keeps this list
and those pages from drifting apart in either direction.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PartnerModel:
    """A model the documentation tells a reader to try, and where."""

    model: str
    location: str
    verified: str


PARTNER_MODELS: tuple[PartnerModel, ...] = (
    PartnerModel("anthropic:claude-haiku-4-5", "global", "2026-08-30"),
    PartnerModel("openai-compatible:xai/grok-4.1-fast-reasoning", "global", "2026-08-30"),
    PartnerModel("openai-compatible:xai/grok-4.1-fast-non-reasoning", "global", "2026-08-30"),
)

#: The strict-JSON path is checked as well as ordinary generation, because a
#: partner model that answers prose and cannot hold a JSON contract is useless
#: to the graph extractor and the judge, which are what these models are for.
_JSON_PROBE = 'Return only JSON: {"status": "ok"}'


def summarize(results: list[tuple[PartnerModel, bool, str]]) -> tuple[bool, list[str]]:
    """Render the outcome, and say whether every named model still answers."""
    lines = []
    for entry, ok, detail in results:
        mark = "ok  " if ok else "FAIL"
        lines.append(f"{mark} {entry.model} @ {entry.location} (verified {entry.verified})")
        lines.append(f"     {detail}")
    failed = [entry for entry, ok, _ in results if not ok]
    if failed:
        lines.append("")
        lines.append(
            f"{len(failed)} documented model(s) no longer answer. A model that has been "
            "retired, renamed, or moved has to be replaced in docs/extend.md and "
            ".env.example, and its entry here updated with the new id and date. "
            "A model that is merely not enabled in this project's Model Garden is a "
            "local authorization problem, not a lifecycle one: check the diagnostic "
            "text before editing the guide."
        )
    return not failed, lines


async def _probe(entry: PartnerModel) -> tuple[PartnerModel, bool, str]:
    from sci_rag.config import Settings
    from sci_rag.llm import get_llm

    settings = Settings(
        _env_file=None,
        gcp_location=entry.location,
        llm_model=entry.model,
        embedding_provider="local-hash",
    )
    if not settings.gcp_project:
        return entry, False, "no SCI_RAG_GCP_PROJECT configured"
    try:
        llm = get_llm(settings)
        text = await llm.generate("Reply with the single word: ready", max_tokens=64)
        payload = await llm.generate_json(_JSON_PROBE, max_tokens=128)
    except Exception as exc:
        from sci_rag.scaffold.preflight import _failure_result

        result = _failure_result(exc, vertex=True, location=entry.location)
        return entry, False, f"{result.detail} {result.fix}".strip()
    if not text.strip():
        return entry, False, "empty response on the generation path"
    if not isinstance(payload, dict):
        return entry, False, f"strict JSON path returned {type(payload).__name__}"
    return entry, True, f"generation and strict JSON both answered ({payload})"


def main() -> None:
    import os

    if not os.environ.get("SCI_RAG_GCP_PROJECT"):
        print(
            "This check calls the provider, so it needs SCI_RAG_GCP_PROJECT and "
            "application-default credentials. It is deliberately not a CI job: a "
            "check that always skips is a check nobody reads.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    async def probe_all() -> list[tuple[PartnerModel, bool, str]]:
        return list(await asyncio.gather(*(_probe(entry) for entry in PARTNER_MODELS)))

    ok, lines = summarize(asyncio.run(probe_all()))
    print("\n".join(lines))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
