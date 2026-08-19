"""Lead discovery via the Google Places API (Text Search).

Env-gated: requires GOOGLE_PLACES_API_KEY. The adapter is fully real —
it raises ConfigError up-front when the key is missing, so selecting this
provider without the key can never masquerade as a working integration.
"""

from __future__ import annotations

from typing import List

import requests

from ..errors import ConfigError, ProviderError
from ..log import get_logger
from ..retry import retry_with_backoff
from .base import DiscoveryProvider, RawLead

log = get_logger("google_places")
ENDPOINT = "https://maps.googleapis.com/maps/api/place/textsearch/json"


class GooglePlacesProvider(DiscoveryProvider):
    name = "google_places"

    def discover(self, city: str, category: str, limit: int) -> List[RawLead]:
        api_key = self.config.require_secret("GOOGLE_PLACES_API_KEY")
        params = {
            "query": f"{category} in {city}",
            "key": api_key,
        }

        def _call():
            resp = requests.get(
                ENDPOINT,
                params=params,
                timeout=self.config.get("http.timeout_s", 15),
            )
            resp.raise_for_status()
            return resp.json()

        try:
            payload = retry_with_backoff(
                _call,
                attempts=self.config.get("retry.max_attempts", 3),
                base_delay_s=self.config.get("retry.base_delay_s", 2.0),
                max_delay_s=self.config.get("retry.max_delay_s", 60.0),
                jitter=self.config.get("retry.jitter", True),
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"google places request failed: {exc}") from exc

        if payload.get("status") not in ("OK", "ZERO_RESULTS"):
            raise ProviderError(
                f"google places error: {payload.get('status')} — {payload.get('error_message', '')}"
            )

        leads: List[RawLead] = []
        for result in payload.get("results", [])[:limit]:
            geometry = result.get("geometry", {}).get("location", {})
            leads.append(
                RawLead(
                    source=self.name,
                    external_id=f"gplaces/{result.get('place_id')}",
                    name=result.get("name", ""),
                    category=category,
                    city=city,
                    address=result.get("formatted_address"),
                    lat=geometry.get("lat"),
                    lon=geometry.get("lng"),
                    rating=result.get("rating"),
                    reviews_count=result.get("user_ratings_total"),
                    tags={"business_status": result.get("business_status")},
                )
            )
        log.info("google_places: %d leads for %s/%s", len(leads), city, category)
        return leads
