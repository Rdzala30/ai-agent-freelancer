"""Data normalization: phone, name, website, city, category, address.

Normalization is lossy-on-purpose: it produces canonical forms used for
dedup fingerprints, E.164 phone storage, and safe URL storage.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

_DIGITS = re.compile(r"\d+")
_PHONE_10 = re.compile(r"^[6-9]\d{9}$")  # Indian mobile numbers start 6-9
_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_phone(raw: Optional[str], country: str = "IN") -> Optional[str]:
    """Return an E.164-ish phone ('+91XXXXXXXXXX') or None when unparseable."""
    if not raw:
        return None
    s = str(raw).strip()
    digits = "".join(_DIGITS.findall(s))
    if not digits:
        return None
    if s.startswith("+"):
        digits = "+" + digits
    if country == "IN":
        if digits.startswith("+91") and len(digits) == 13:
            return digits
        if digits.startswith("91") and len(digits) == 12:
            return "+" + digits
        if digits.startswith("0") and len(digits) == 11:
            return "+91" + digits[1:]
        if len(digits) == 10 and _PHONE_10.match(digits):
            return "+91" + digits
        if len(digits) == 11 and digits.startswith("1"):  # US-style, not IN
            return None
    return None


def normalize_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _WS.sub(" ", str(raw)).strip()


def normalize_website(raw: Optional[str]) -> Optional[str]:
    """Canonicalize a website string to 'https://host[/path]' or None."""
    if not raw:
        return None
    s = str(raw).strip().rstrip("/")
    if not s:
        return None
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    parsed = urlparse(s)
    if not parsed.hostname or "." not in parsed.hostname:
        return None
    return s


def normalize_city(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _WS.sub(" ", str(raw).strip()).title()


def normalize_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return str(raw).strip().lower()


def normalize_address(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _WS.sub(" ", str(raw)).strip().strip(",")


def slugify(value: str, max_len: int = 32) -> str:
    """URL/domain-safe slug: 'The Green Cafe' -> 'thegreencafe'."""
    slug = _NON_ALNUM.sub("", value.lower())
    return slug[:max_len]
