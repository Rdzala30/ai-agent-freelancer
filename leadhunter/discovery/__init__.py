"""Lead discovery providers (pluggable)."""

from .base import DiscoveryProvider, RawLead  # noqa: F401
from .google_places import GooglePlacesProvider  # noqa: F401
from .overpass import OverpassProvider  # noqa: F401
from .serpapi_search import SerpApiSearchProvider  # noqa: F401

PROVIDERS = {
    "overpass": OverpassProvider,
    "google_places": GooglePlacesProvider,
    "serpapi": SerpApiSearchProvider,
}


def get_provider(name: str, config):
    try:
        cls = PROVIDERS[name]
    except KeyError:
        from ...errors import ConfigError

        raise ConfigError(
            f"unknown discovery provider '{name}' — choose from {sorted(PROVIDERS)}"
        )
    return cls(config)
