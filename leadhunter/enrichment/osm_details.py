"""Enrichment from OpenStreetMap element details (Overpass).

Discovery returns the tag set from the initial query, which is usually
complete, but contacts are sometimes on sibling elements or added later.
This enricher re-fetches the element and pulls any contact tags (phone,
website, email, full address) that the discovery pass missed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from ..errors import ProviderError
from ..log import get_logger
from ..models import Lead
from ..retry import RateLimiter, retry_with_backoff
from .base import Enricher

log = get_logger("osm_details")
ENDPOINT = "https://overpass-api.de/api/interpreter"
_limiter = RateLimiter(1.5)

CONTACT_KEYS = {
    "phone": ("phone", "contact:phone"),
    "website": ("website", "contact:website"),
    "email": ("email", "contact:email"),
}


class OSMDetailsEnricher(Enricher):
    def enrich(self, lead: Lead) -> Dict[str, Any]:
        if not lead.external_id or not lead.external_id.startswith("osm:"):
            return {}
        _, _, element_ref = lead.external_id.partition("osm:")
        if not element_ref:
            return {}
        otype, _, oid = element_ref.partition("/")
        if not oid:
            return {}
        tags = self._fetch_tags(otype, oid)
        if not tags:
            return {}

        fields: Dict[str, Any] = {}
        for field, keys in CONTACT_KEYS.items():
            if getattr(lead, field):
                continue  # already known — don't overwrite
            for key in keys:
                value = tags.get(key)
                if value:
                    fields[field] = value
                    break

        if not lead.address and tags.get("addr:full"):
            fields["address"] = tags["addr:full"]
        return fields

    def _fetch_tags(self, otype: str, oid: str) -> Optional[Dict[str, Any]]:
        query = f"[out:json][timeout:20];\n({otype}({oid}););\nout body;\n"

        def _call():
            _limiter.wait()
            resp = requests.post(
                ENDPOINT,
                data={"data": query},
                headers={"User-Agent": self.config.get("http.user_agent", "LeadHunterAI/0.1")},
                timeout=45,
            )
            resp.raise_for_status()
            payload = resp.json()
            elements = payload.get("elements", [])
            return elements[0].get("tags", {}) if elements else {}

        try:
            return retry_with_backoff(
                _call,
                attempts=self.config.get("retry.max_attempts", 2),
                base_delay_s=self.config.get("retry.base_delay_s", 2.0),
                max_delay_s=self.config.get("retry.max_delay_s", 60.0),
                jitter=self.config.get("retry.jitter", True),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("osm details fetch failed for %s/%s: %s", otype, oid, exc)
            return None
