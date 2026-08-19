"""Business enrichment (pluggable)."""

from .base import Enricher  # noqa: F401
from .email_finder import EmailFinder  # noqa: F401
from .osm_details import OSMDetailsEnricher  # noqa: F401


def get_enrichers(config) -> list:
    """The ordered enrichment pipeline. Each returns fields; later enrichers
    may fill gaps left by earlier ones."""
    return [OSMDetailsEnricher(config), EmailFinder(config)]
