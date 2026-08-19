"""Error taxonomy for LeadHunter AI.

Every error knows whether it is *retryable*. Retryable errors (provider
throttling, network blips) get the backoff treatment and, if they exhaust
retries, land the lead in FAILED with a note. Fatal errors (misconfig,
missing secret, invalid state) surface immediately — the system never
pretends a keyless integration works.
"""

from __future__ import annotations


class LeadHunterError(Exception):
    """Base class for all LeadHunter AI errors."""

    retryable = False


class ConfigError(LeadHunterError):
    """Missing/invalid configuration or a secret that a module actually needs."""


class ProviderError(LeadHunterError):
    """An external data source (OSM, Google, directory) failed."""

    retryable = True


class RateLimitError(ProviderError):
    """Source throttled us — back off and retry later."""


class HttpFetchError(ProviderError):
    """HTTP-level failure fetching a resource."""


class VerificationError(LeadHunterError):
    """Website verification could not be completed."""

    retryable = True


class OutboundError(LeadHunterError):
    """Outreach send failed (bridge down, SMTP rejected, etc.)."""


class StateTransitionError(LeadHunterError):
    """An illegal lead state transition was attempted."""


class NotFoundError(LeadHunterError):
    """A requested lead/run/record does not exist."""
