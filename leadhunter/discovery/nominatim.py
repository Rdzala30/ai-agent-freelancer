"""City geocoding via the Nominatim API (free, no key required).

Usage policy (https://operations.osmfoundation.org/policies/nominatim/):
max 1 request/second, identify yourself with a real User-Agent. The rate
limiter + UA below comply.
"""

from __future__ import annotations

from typing import Optional, Tuple

import requests

from ..config import Config
from ..errors import ProviderError
from ..retry import RateLimiter, retry_with_backoff
from ..log import get_logger

log = get_logger("nominatim")
_limiter = RateLimiter(1.2)  # default; pipeline can set tighter


def configure(config: Config) -> None:
    global _limiter
    _limiter = RateLimiter(config.get("rate_limits.nominatim_min_interval_s", 1.2))


def geocode(city: str, config: Config) -> Tuple[float, float, str]:
    """Return (lat, lon, display_name) for a city, or raise ProviderError."""
    params = {"q": city, "format": "jsonv2", "limit": 1, "addressdetails": 0}
    headers = {"User-Agent": config.get("http.user_agent", "LeadHunterAI/0.1")}

    def _call():
        _limiter.wait()
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=headers,
            timeout=config.get("http.timeout_s", 15),
        )
        if resp.status_code == 429:
            from ..errors import RateLimitError

            raise RateLimitError("nominatim 429 — throttled")
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise ProviderError(f"nominatim: no result for city '{city}'")
        hit = data[0]
        return float(hit["lat"]), float(hit["lon"]), hit.get("display_name", city)

    return retry_with_backoff(
        _call,
        attempts=config.get("retry.max_attempts", 3),
        base_delay_s=config.get("retry.base_delay_s", 2.0),
        max_delay_s=config.get("retry.max_delay_s", 60.0),
        jitter=config.get("retry.jitter", True),
    )
