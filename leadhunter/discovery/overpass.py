"""Lead discovery via the OpenStreetMap Overpass API.

Real, free, no API key. Politeness: min interval between requests, browser
UA, small timeouts. Used as the default provider.
"""

from __future__ import annotations

from typing import List

import requests

from ..errors import ProviderError, RateLimitError
from ..log import get_logger
from ..retry import RateLimiter, retry_with_backoff
from . import categories as cat_map
from .base import DiscoveryProvider, RawLead

log = get_logger("overpass")
ENDPOINT = "https://overpass-api.de/api/interpreter"
_limiter = RateLimiter(1.5)


class OverpassProvider(DiscoveryProvider):
    name = "overpass"

    def discover(self, city: str, category: str, limit: int) -> List[RawLead]:
        from . import nominatim

        nominatim.configure(self.config)
        lat, lon, _ = nominatim.geocode(city, self.config)
        radius = self.config.get("discovery.search_radius_m", 5000)
        tags = cat_map.resolve(category)

        query = self._build_query(tags, lat, lon, radius, limit)
        elements = self._run_query(query, city, category)

        leads: List[RawLead] = []
        for el in elements:
            tags_d = el.get("tags", {})
            name = tags_d.get("name")
            if not name:
                continue
            if el["type"] == "node":
                el_lat, el_lon = el.get("lat"), el.get("lon")
            else:
                center = el.get("center") or {}
                el_lat, el_lon = center.get("lat"), center.get("lon")
            address = self._address(tags_d)
            leads.append(
                RawLead(
                    source=self.name,
                    external_id=f"osm:{el['type']}/{el['id']}",
                    name=name,
                    category=category,
                    city=city,
                    address=address,
                    lat=float(el_lat) if el_lat is not None else None,
                    lon=float(el_lon) if el_lon is not None else None,
                    phone=tags_d.get("phone") or tags_d.get("contact:phone"),
                    website=tags_d.get("website") or tags_d.get("contact:website"),
                    email=tags_d.get("email") or tags_d.get("contact:email"),
                    tags=tags_d,
                )
            )
            if len(leads) >= limit:
                break
        log.info("overpass: %d leads for %s/%s", len(leads), city, category)
        return leads

    # ---- internals -------------------------------------------------------

    @staticmethod
    def _build_query(tags, lat, lon, radius, limit) -> str:
        clauses = []
        for key, value in tags:
            clauses.append(
                f'node["{key}"="{value}"]["name"](around:{radius},{lat},{lon});'
            )
            clauses.append(
                f'way["{key}"="{value}"]["name"](around:{radius},{lat},{lon});'
            )
        body = "\n".join(clauses)
        return (
            "[out:json][timeout:30];\n(\n" + body + "\n);\nout center tags "
            + str(min(limit, 200))
            + ";\n"
        )

    def _run_query(self, query: str, city: str, category: str) -> List[dict]:
        def _call():
            _limiter.wait()
            resp = requests.post(
                ENDPOINT,
                data={"data": query},
                headers={
                    "User-Agent": self.config.get("http.user_agent", "LeadHunterAI/0.1"),
                    "Accept": "application/json",
                },
                timeout=60,
            )
            if resp.status_code == 429:
                raise RateLimitError("overpass 429 — throttled")
            if resp.status_code == 504:
                raise ProviderError("overpass 504 — query timed out upstream")
            resp.raise_for_status()
            payload = resp.json()
            if "elements" not in payload:
                raise ProviderError(f"overpass: unexpected payload for {city}/{category}")
            return payload["elements"]

        try:
            return retry_with_backoff(
                _call,
                attempts=self.config.get("retry.max_attempts", 3),
                base_delay_s=self.config.get("retry.base_delay_s", 2.0),
                max_delay_s=self.config.get("retry.max_delay_s", 60.0),
                jitter=self.config.get("retry.jitter", True),
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — wrap as provider error
            raise ProviderError(f"overpass request failed: {exc}") from exc

    @staticmethod
    def _address(tags: dict) -> str:
        parts = []
        for key in ("addr:housenumber", "addr:street"):
            if tags.get(key):
                parts.append(tags[key])
        if tags.get("addr:city"):
            parts.append(tags["addr:city"])
        return ", ".join(parts) or None
