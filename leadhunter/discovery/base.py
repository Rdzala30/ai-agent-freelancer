"""Discovery provider interface and the raw lead payload."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RawLead:
    """A business as returned by a discovery provider (pre-normalization)."""

    source: str
    external_id: str
    name: str
    category: str
    city: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    tags: Dict[str, Any] = field(default_factory=dict)


class DiscoveryProvider(ABC):
    """Finds businesses of a category in a city."""

    name: str = "base"

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def discover(self, city: str, category: str, limit: int) -> List[RawLead]:
        """Return up to `limit` raw leads for (city, category).

        Raises ConfigError when a required secret is missing, ProviderError
        on source failures. Never returns fabricated leads.
        """
