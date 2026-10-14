"""Which header the server believes when a caller sends two.

Found by the issue #189 live qualification, on a real private Cloud Run
service rather than in a fixture. `allow_unauthenticated` is false by default,
so Cloud Run's frontend requires a Google identity token in `Authorization`.
`docs/deploy-gcp.md` therefore tells readers to send the kit's key in
`X-API-Key`, precisely because `Authorization` is already spoken for.

`api_key_from_headers` preferred `Authorization`, so it read the identity
token as if it were the kit key and answered every request the same way:

    {"title": "Unknown API key", "status": 401, "code": "invalid_key"}

Three live probes separated the cause from the symptom:

    X-API-Key only                      -> 403 (Cloud Run rejects, no token)
    Authorization identity + X-API-Key  -> 401 (the token shadowed the key)
    Authorization: Bearer <kit key>     -> 401 (Cloud Run rejects the key)

No combination authenticated, so a private deployment following the guide
could not reach an authenticated route at all. `X-API-Key` now wins when both
are present: it is the caller naming the credential it means, while
`Authorization` may have been set by the infrastructure in front of the app.
"""

from __future__ import annotations

from sci_rag.server.auth import api_key_from_headers

IDENTITY_TOKEN = "eyJhbGciOiJSUzI1NiIsImtpZCI6ImZha2UifQ.fake-google-identity.sig"
KIT_KEY = "kit-key-0123456789abcdef"


def test_the_explicit_key_header_wins_over_an_infrastructure_bearer_token() -> None:
    """The exact shape that returned 401 against the deployed service."""
    assert api_key_from_headers(f"Bearer {IDENTITY_TOKEN}", KIT_KEY) == KIT_KEY


def test_a_bearer_token_is_still_read_when_it_is_the_only_header() -> None:
    """Local and single-header clients are unaffected by the precedence flip."""
    assert api_key_from_headers(f"Bearer {KIT_KEY}", None) == KIT_KEY


def test_the_key_header_is_read_when_no_authorization_arrives() -> None:
    assert api_key_from_headers("", KIT_KEY) == KIT_KEY


def test_no_credential_at_all_stays_none() -> None:
    assert api_key_from_headers("", None) is None


def test_an_empty_key_header_falls_back_rather_than_blanking_the_caller() -> None:
    """An empty header is absence, not a claim to be an empty credential."""
    assert api_key_from_headers(f"Bearer {KIT_KEY}", "") == KIT_KEY


def test_a_non_bearer_authorization_scheme_is_not_mistaken_for_a_key() -> None:
    assert api_key_from_headers("Basic dXNlcjpwYXNz", None) is None
