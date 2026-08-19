"""Data normalization for LeadHunter AI.

Normalizes business names, phone numbers, website URLs, and addresses to standard
canonical representations used across the pipeline and deduplication.
Also provides lead quality scoring (0–100).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

_DIGITS = re.compile(r"\d+")
_PHONE_10 = re.compile(r"^[6-9]\d{9}$")
_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")

# Company entity noise patterns (case-insensitive)
_COMPANY_NOISE = re.compile(
    r"\b(pvt\.?\s*ltd\.?|private\s+limited|pvt\.?|ltd\.?|llp|inc\.?|corp\.?|co\.?)\b",
    re.IGNORECASE,
)
_AMPERSAND = re.compile(r"\s*&\s*|\s+and\s+", re.IGNORECASE)


def normalize_name(raw: Optional[str]) -> str:
    """Normalize business names:
    - Lowercase
    - Remove Ltd, Pvt, Pvt.Ltd, Private Limited, Co, etc.
    - Remove & / and
    - Strip punctuation and excess whitespace
    """
    if not raw:
        return ""
    s = str(raw).strip().lower()
    # Remove & / and
    s = _AMPERSAND.sub(" ", s)
    # Remove company entity suffixes
    s = _COMPANY_NOISE.sub(" ", s)
    # Remove non-alphanumeric characters (keep letters, numbers, spaces)
    s = _NON_ALNUM.sub(" ", s)
    # Collapse multiple whitespaces and strip
    return _WS.sub(" ", s).strip()


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """Normalize phone numbers:
    - Strip spaces, dashes, parentheses, dots
    - Remove +91 or 91 country code (or leading 0)
    - Keep standard 10 digits
    """
    if not raw:
        return None
    s = str(raw).strip()
    digits = "".join(_DIGITS.findall(s))
    if not digits:
        return None

    # Handle Indian phone formats (+91XXXXXXXXXX, 91XXXXXXXXXX, 0XXXXXXXXXX)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    elif len(digits) > 10 and digits.startswith("91"):
        digits = digits[-10:]

    if len(digits) == 10:
        return digits
    elif len(digits) > 10:
        # Take the last 10 digits if formatted with country code
        return digits[-10:]
    return digits if digits else None


def normalize_website(raw: Optional[str]) -> Optional[str]:
    """Normalize website URLs:
    - Lowercase
    - Remove www.
    - Remove trailing slash
    - Remove http:// or https:// prefix for standard clean string
    """
    if not raw:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None

    # Ensure urlparse can parse hostname
    if not s.startswith(("http://", "https://")):
        s = "https://" + s

    parsed = urlparse(s)
    host = parsed.netloc or parsed.path.split("/")[0]
    # Remove port if present
    host = host.split(":")[0]
    # Remove leading www.
    if host.startswith("www."):
        host = host[4:]

    path = parsed.path.rstrip("/")
    if parsed.query:
        path += f"?{parsed.query}"

    if not host or "." not in host:
        return None

    return f"{host}{path}" if path and path != "/" else host


def extract_domain(raw: Optional[str]) -> Optional[str]:
    """Extract root/registered domain from a website URL (e.g. expresshotelsindia.com)."""
    norm = normalize_website(raw)
    if not norm:
        return None
    host = norm.split("/")[0].split("?")[0]
    return host


def normalize_address(raw: Optional[str]) -> Optional[str]:
    """Normalize addresses:
    - Lowercase
    - Strip extra spaces and punctuation
    """
    if not raw:
        return None
    s = str(raw).strip().lower()
    # Normalize separators
    s = s.replace(",", " , ")
    s = _WS.sub(" ", s).strip()
    # Clean leading/trailing commas
    s = re.sub(r"^\s*,\s*|\s*,\s*$", "", s)
    return _WS.sub(" ", s).strip()


def compute_quality_score(lead: Any) -> Tuple[int, List[str]]:
    """Compute lead quality score (0–100) based on:
    - Has phone number: +20
    - Has website URL: +20
    - Has address: +20
    - Has rating: +10
    - Has email: +15
    - Has 10+ reviews: +15
    """
    score = 0
    reasons: List[str] = []

    # Get attributes whether lead is a Lead model or a dict
    def _get(attr: str) -> Any:
        if isinstance(lead, dict):
            return lead.get(attr)
        return getattr(lead, attr, None)

    phone = _get("phone") or _get("phone_normalized")
    website = _get("website") or _get("website_verified")
    address = _get("address")
    rating = _get("rating")
    email = _get("email")
    reviews_count = _get("reviews_count") or _get("review_count")

    if phone and str(phone).strip():
        score += 20
        reasons.append("has_phone (+20)")

    if website and str(website).strip():
        score += 20
        reasons.append("has_website (+20)")

    if address and str(address).strip():
        score += 20
        reasons.append("has_address (+20)")

    if rating is not None:
        try:
            if float(rating) > 0:
                score += 10
                reasons.append(f"has_rating: {rating} (+10)")
        except (ValueError, TypeError):
            pass

    if email and str(email).strip():
        score += 15
        reasons.append("has_email (+15)")

    if reviews_count is not None:
        try:
            if int(reviews_count) >= 10:
                score += 15
                reasons.append(f"has_10+_reviews: {reviews_count} (+15)")
        except (ValueError, TypeError):
            pass

    return min(score, 100), reasons
