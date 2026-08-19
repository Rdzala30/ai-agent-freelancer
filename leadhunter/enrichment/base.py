"""Enrichment interface: add verified details to a discovered lead."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from ..models import Lead


class Enricher(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def enrich(self, lead: Lead) -> Dict[str, Any]:
        """Return a dict of NEW fields (keys matching Lead.to_row()) plus
        optional 'notes'. Empty dict = nothing found (fine)."""
