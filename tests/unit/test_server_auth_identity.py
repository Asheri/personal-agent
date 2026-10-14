"""Who the rate limiter thinks it is counting.

`AuthContext.key_id` is a human facing label: a truncated key that is safe to
read in a log. F-017 in the 2026-08-29 documentation route audit found that
the limiter counted against that label, so two keys beginning with the same
six characters shared one bucket and either caller could throttle the other.

Accounting now runs on `rate_limit_id`, an opaque identity derived from the
whole token. These tests cover the identity itself and the limiter's use of
it. `tests/server/test_api_contracts.py` covers the same behaviour over the
live REST route, which is where the audit reproduced it.
"""

from __future__ import annotations

import json

import pytest

from sci_rag.server.auth import (
    ALL_SCOPES,
    AuthContext,
    OpenBackend,
    StaticKeyBackend,
    limiter_identity,
)
from sci_rag.server.errors import ApiError

SAME_PREFIX_KEYS = {
    "audit-alpha-0001": {"scopes": ["retrieval:query"], "rate_limit_per_minute": 1},
    "audit-bravo-0002": {"scopes": ["retrieval:query"], "rate_limit_per_minute": 1},
}


def _backend() -> StaticKeyBackend:
    return StaticKeyBackend.from_json(json.dumps(SAME_PREFIX_KEYS))


# --- the identity itself ----------------------------------------------------


def test_two_keys_sharing_a_prefix_get_different_identities() -> None:
    assert limiter_identity("audit-alpha-0001") != limiter_identity("audit-bravo-0002")


def test_the_same_key_always_gets_the_same_identity() -> None:
    """Accounting is worthless if a caller gets a fresh bucket every request."""
    assert limiter_identity("audit-alpha-0001") == limiter_identity("audit-alpha-0001")


def test_the_identity_does_not_contain_the_key() -> None:
    token = "audit-alpha-0001"
    identity = limiter_identity(token)
    assert token not in identity
    for length in range(4, len(token) + 1):
        assert token[:length] not in identity.removeprefix("key:")


def test_a_one_character_difference_still_separates() -> None:
    """Keys can be issued in a batch and differ only in a suffix."""
    assert limiter_identity("prefix-key-a") != limiter_identity("prefix-key-b")


# --- what the backend puts in the context -----------------------------------


def test_the_label_stays_readable_and_truncated() -> None:
    context = _backend().authenticate("audit-alpha-0001")
    assert context.key_id == "key:audit-..."
    assert "alpha" not in context.key_id


def test_the_limiter_key_is_the_identity_not_the_label() -> None:
    context = _backend().authenticate("audit-alpha-0001")
    assert context.limiter_key == context.rate_limit_id
    assert context.limiter_key != context.key_id


def test_a_backend_with_nothing_to_tell_apart_keeps_one_bucket() -> None:
    """Open mode has no keys, so a shared bucket is the correct answer."""
    context = OpenBackend().authenticate(None)
    assert context.rate_limit_id is None
    assert context.limiter_key == "anonymous"


def test_a_context_built_without_an_identity_falls_back_to_its_label() -> None:
    context = AuthContext(key_id="key:legacy...", scopes=ALL_SCOPES)
    assert context.limiter_key == "key:legacy..."


# --- accounting -------------------------------------------------------------


def test_same_prefix_keys_do_not_spend_each_others_budget() -> None:
    backend = _backend()
    first = backend.authenticate("audit-alpha-0001")
    second = backend.authenticate("audit-bravo-0002")

    backend.check_rate(first)
    with pytest.raises(ApiError) as exhausted:
        backend.check_rate(first)
    assert exhausted.value.code == "rate_limited"

    backend.check_rate(second)  # its own budget, untouched


def test_one_key_still_accumulates() -> None:
    backend = _backend()
    context = backend.authenticate("audit-alpha-0001")
    backend.check_rate(context)
    with pytest.raises(ApiError) as exhausted:
        backend.check_rate(context)
    assert exhausted.value.status == 429
    assert exhausted.value.code == "rate_limited"
    assert int(exhausted.value.headers["Retry-After"]) >= 1


def test_no_raw_key_reaches_limiter_state() -> None:
    """The limiter is the one place that keeps something per credential."""
    backend = _backend()
    for token in SAME_PREFIX_KEYS:
        backend.check_rate(backend.authenticate(token))

    state = repr(backend._limiter._windows)
    for token in SAME_PREFIX_KEYS:
        assert token not in state


def test_no_raw_key_reaches_the_error_a_caller_sees() -> None:
    """A 429 body or header must not echo the credential back."""
    backend = _backend()
    context = backend.authenticate("audit-alpha-0001")
    backend.check_rate(context)
    with pytest.raises(ApiError) as exhausted:
        backend.check_rate(context)

    error = exhausted.value
    rendered = " ".join([error.title, error.detail, error.code, repr(error.headers)])
    assert "audit-alpha-0001" not in rendered
    assert "audit-" not in rendered
