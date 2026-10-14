"""Resolve DOI candidates to legal open-access locations through Unpaywall."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlparse

from sci_rag.campaigns.discovery import JsonClient, normalize_doi
from sci_rag.campaigns.licensing_map import license_class_for

UNPAYWALL_API_URL = "https://api.unpaywall.org/v2"


@dataclass(frozen=True)
class OaResolution:
    doi: str
    is_oa: bool
    oa_status: str | None
    license_string: str | None
    license_class: str
    pdf_url: str | None
    landing_page_url: str | None
    host_type: str | None = None
    version: str | None = None


async def resolve_unpaywall(
    client: JsonClient,
    doi: str,
    *,
    base_url: str = UNPAYWALL_API_URL,
    email: str | None = None,
) -> OaResolution:
    """Fetch and validate the Unpaywall DOI object for one candidate."""
    normalized = normalize_doi(doi)
    if normalized is None:
        raise ValueError(f"invalid DOI: {doi!r}")
    params = {"email": email} if email else None
    payload = await client.get_json(
        f"{base_url.rstrip('/')}/{quote(normalized, safe='/')}",
        params=params,
    )
    returned_doi = normalize_doi(payload.get("doi", ""))
    if returned_doi != normalized:
        raise ValueError("Unpaywall DOI did not match the requested DOI")
    is_oa = payload.get("is_oa")
    if not isinstance(is_oa, bool):
        raise ValueError("Unpaywall is_oa must be a boolean")
    raw_status = payload.get("oa_status")
    if raw_status is not None and not isinstance(raw_status, str):
        raise ValueError("Unpaywall oa_status must be a string or null")

    raw_location = payload.get("best_oa_location")
    if raw_location is None:
        if is_oa:
            raise ValueError("Unpaywall marked the work OA without a best OA location")
        raw_location = {}
    if not isinstance(raw_location, dict):
        raise ValueError("Unpaywall best_oa_location must be an object or null")

    raw_license = raw_location.get("license")
    if raw_license is not None and not isinstance(raw_license, str):
        raise ValueError("Unpaywall location license must be a string or null")
    pdf_url = _optional_http_url(raw_location.get("url_for_pdf"), field_name="url_for_pdf")
    landing_page_url = _optional_http_url(
        raw_location.get("url_for_landing_page") or raw_location.get("url"),
        field_name="url_for_landing_page",
    )
    host_type = raw_location.get("host_type")
    version = raw_location.get("version")
    return OaResolution(
        doi=normalized,
        is_oa=is_oa,
        oa_status=raw_status,
        license_string=raw_license,
        license_class=license_class_for(raw_status, raw_license),
        pdf_url=pdf_url,
        landing_page_url=landing_page_url,
        host_type=host_type if isinstance(host_type, str) else None,
        version=version if isinstance(version, str) else None,
    )


def _optional_http_url(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Unpaywall {field_name} must be a URL or null")
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Unpaywall {field_name} must use HTTP or HTTPS")
    return value
