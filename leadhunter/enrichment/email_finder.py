"""Email finding via Hunter.io (real API) — env-gated.

No key configured => returns {} and a note; the lead continues fine without
an email (email is a bonus signal, not a requirement). Hunter is a real,
documented integration (domain-search endpoint), so when HUNTER_API_KEY is
set this actually finds emails.

Apollo support: APOLLO_API_KEY enables the organizations/search endpoint,
which confirms company info from a domain (not emails). Kept intentionally
minimal and honest — no fake contact fabrication, ever.
"""

from __future__ import annotations

from typing import Any, Dict

import requests

from ..log import get_logger
from ..models import Lead
from .base import Enricher

log = get_logger("email_finder")

HUNTER_ENDPOINT = "https://api.hunter.io/v2/domain-search"
APOLLO_ENDPOINT = "https://api.apollo.io/v1/organizations/search"


class EmailFinder(Enricher):
    def enrich(self, lead: Lead) -> Dict[str, Any]:
        domain = self._domain_of(lead)
        if not domain:
            return {"notes": "no domain to search emails for"}

        hunter_key = self.config.get_secret("HUNTER_API_KEY")
        if hunter_key:
            emails = self._hunter_domain_emails(domain, hunter_key)
            if emails:
                return {"email": emails[0], "notes": f"hunter.io found {len(emails)} email(s)"}

        apollo_key = self.config.get_secret("APOLLO_API_KEY")
        if apollo_key:
            self._apollo_organization(domain, apollo_key)  # informational

        return {"notes": "email finder: no key configured or nothing found"}

    # ---- internals -------------------------------------------------------

    @staticmethod
    def _domain_of(lead: Lead) -> str:
        url = lead.website_verified or lead.website
        if not url:
            return ""
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
        return host.lstrip("www.") if host else ""

    def _hunter_domain_emails(self, domain: str, key: str) -> list:
        try:
            resp = requests.get(
                HUNTER_ENDPOINT,
                params={"domain": domain, "api_key": key},
                timeout=self.config.get("http.timeout_s", 15),
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            emails = [e.get("value") for e in data.get("emails", []) if e.get("value")]
            return emails
        except Exception as exc:  # noqa: BLE001
            log.warning("hunter.io lookup failed for %s: %s", domain, exc)
            return []

    def _apollo_organization(self, domain: str, key: str) -> None:
        try:
            resp = requests.get(
                APOLLO_ENDPOINT,
                params={"q_keywords": domain, "per_page": 1},
                headers={"x-api-key": key},
                timeout=self.config.get("http.timeout_s", 15),
            )
            if resp.status_code == 200:
                orgs = resp.json().get("organizations", [])
                if orgs:
                    log.info("apollo: matched org %s", orgs[0].get("name"))
        except Exception as exc:  # noqa: BLE001
            log.warning("apollo lookup failed for %s: %s", domain, exc)
