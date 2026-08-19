"""Processing package for LeadHunter AI (normalization, deduplication, scoring)."""

from .deduplicate import check_duplicate, process_leads
from .lead_scorer import (
    TIER_HOT,
    TIER_LOW,
    TIER_WARM,
    evaluate_lead,
    score_and_qualify_leads,
)
from .normalize import (
    compute_quality_score,
    extract_domain,
    normalize_address,
    normalize_name,
    normalize_phone,
    normalize_website,
)
from .website_checker import (
    STATUS_BROKEN_WEBSITE,
    STATUS_DIRECTORY_ONLY,
    STATUS_DOMAIN_ONLY,
    STATUS_NO_WEBSITE,
    STATUS_SOCIAL_ONLY,
    STATUS_UNKNOWN,
    STATUS_VALID_WEBSITE,
    check_url_with_httpx,
    verify_lead_website,
    verify_leads_batch,
)

__all__ = [
    "normalize_name",
    "normalize_phone",
    "normalize_website",
    "normalize_address",
    "extract_domain",
    "compute_quality_score",
    "check_duplicate",
    "process_leads",
    "verify_lead_website",
    "verify_leads_batch",
    "check_url_with_httpx",
    "evaluate_lead",
    "score_and_qualify_leads",
    "TIER_HOT",
    "TIER_WARM",
    "TIER_LOW",
    "STATUS_VALID_WEBSITE",
    "STATUS_BROKEN_WEBSITE",
    "STATUS_NO_WEBSITE",
    "STATUS_SOCIAL_ONLY",
    "STATUS_DIRECTORY_ONLY",
    "STATUS_DOMAIN_ONLY",
    "STATUS_UNKNOWN",
]
