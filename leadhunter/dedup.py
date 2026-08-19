"""Deduplication: canonical fingerprints for leads.

Two fingerprints are computed per lead:
- name fingerprint: sha1(normalized_name|city|category) — catches the same
  business discovered twice (identical or near-identical names).
- phone fingerprint: sha1(phone|source) — catches the same phone number
  re-listed under a slightly different name.

The DB enforces a UNIQUE constraint on `fingerprint`, so dedup happens
atomically at insert time; the dedup module only computes the keys and can
probe for existing records before a run decides whether to re-discover.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from .normalization import slugify


def name_fingerprint(name: str, city: str, category: str) -> str:
    key = "|".join([slugify(name), slugify(city), slugify(category)])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def phone_fingerprint(phone: str, source: str) -> str:
    key = "|".join(["phone", phone, source])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def primary_fingerprint(
    name: str, city: str, category: str, phone: Optional[str] = None
) -> str:
    """Name-based fingerprint, or phone-based when the name is too generic
    (e.g. 'Hotel', 'Cafe' with no distinctive token)."""
    if phone:
        return phone_fingerprint(phone, "any")
    return name_fingerprint(name, city, category)


def is_generic_name(name: str) -> bool:
    """'Cafe', 'Restaurant', 'Hotel', 'Salon' alone are not unique enough."""
    tokens = [t for t in name.lower().split() if t]
    return len(tokens) == 1 and tokens[0] in {
        "cafe",
        "coffee",
        "restaurant",
        "hotel",
        "salon",
        "gym",
        "shop",
        "store",
        "bakery",
        "pharmacy",
        "clinic",
        "hospital",
        "dhaba",
        "bar",
    }
