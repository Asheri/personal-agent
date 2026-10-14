"""Build, screen, and report reproducible scientific-document campaigns."""

from sci_rag.campaigns.build import (
    CampaignBuildReport,
    build_campaign,
    load_discovered_candidates,
)
from sci_rag.campaigns.discovery import (
    CandidateWork,
    DiscoveryReport,
    discover_by_dois,
    discover_by_topic,
    normalize_doi,
)
from sci_rag.campaigns.download import DownloadOutcome, download_pdf, pdf_filename
from sci_rag.campaigns.licensing_map import license_class_for
from sci_rag.campaigns.manifest import ManifestItem, write_campaign_manifest
from sci_rag.campaigns.resolve import OaResolution, resolve_unpaywall
from sci_rag.campaigns.screen import (
    ScreeningDecision,
    ScreeningReport,
    apply_human_review,
    screen_campaign,
)
from sci_rag.campaigns.state import CampaignRecord, CampaignState

__all__ = [
    "CampaignBuildReport",
    "CampaignRecord",
    "CampaignState",
    "CandidateWork",
    "DiscoveryReport",
    "DownloadOutcome",
    "ManifestItem",
    "OaResolution",
    "ScreeningDecision",
    "ScreeningReport",
    "apply_human_review",
    "build_campaign",
    "discover_by_dois",
    "discover_by_topic",
    "download_pdf",
    "license_class_for",
    "load_discovered_candidates",
    "normalize_doi",
    "pdf_filename",
    "resolve_unpaywall",
    "screen_campaign",
    "write_campaign_manifest",
]
