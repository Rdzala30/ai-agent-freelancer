"""Core data model: the Lead and its lifecycle statuses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LeadStatus(str, Enum):
    """Lifecycle of a lead. Persisted as the string value."""

    DISCOVERED = "DISCOVERED"          # found by a discovery provider
    ENRICHED = "ENRICHED"              # contact/detail enrichment applied
    VERIFIED = "VERIFIED"              # web presence checked (has_site/weak_site/no_site/...)
    QUALIFIED = "QUALIFIED"            # passed qualification rules (qualified=0/1)
    SCORED = "SCORED"                  # scored 0-100 against config weights
    PERSONALIZED = "PERSONALIZED"      # outreach message + subject rendered
    DEMO_READY = "DEMO_READY"          # personalized demo landing page published
    PENDING_APPROVAL = "PENDING_APPROVAL"  # waiting for human approval to send
    APPROVED = "APPROVED"              # approved by human reviewer, ready for sending
    REJECTED = "REJECTED"              # rejected by human reviewer, will not be contacted
    DRY_RUN_SENT = "DRY_RUN_SENT"      # simulated dry-run delivery
    SENT = "SENT"                      # outreach actually delivered
    COLD = "COLD"                      # max follow-ups exhausted without reply
    FAILED = "FAILED"                  # exhausted retries; see stage_status for recovery
    REPLIED = "REPLIED"                # prospect responded
    CONVERTED = "CONVERTED"            # prospect became a client
    DO_NOT_CONTACT = "DO_NOT_CONTACT"  # explicit opt-out / rejected at approval
    DISCARDED = "DISCARDED"            # failed qualification or below score floor
    DUPLICATE = "DUPLICATE"            # identified as duplicate during processing

    def __str__(self) -> str:  # type: ignore[override]
        return self.value


# Classifications produced by website verification.
SITE_HAS = "has_site"          # real, working website
SITE_WEAK = "weak_site"        # site exists but mobile-unfriendly / heavy / placeholder
SITE_NONE = "no_site"          # no site found (domain guesses failed, no claimed site)
SITE_UNVERIFIABLE = "unverifiable"  # could not determine (DNS/network/timed out)

SITE_CLASSIFICATIONS: tuple = (SITE_HAS, SITE_WEAK, SITE_NONE, SITE_UNVERIFIABLE)


@dataclass
class Lead:
    """A business lead at any stage of the pipeline."""

    name: str
    category: str
    city: str
    source: str
    external_id: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    phone: Optional[str] = None
    phone_normalized: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None          # claimed/discovered website
    website_verified: Optional[str] = None  # final verified URL (after verification)
    website_status: Optional[str] = None    # VALID_WEBSITE, NO_WEBSITE, BROKEN_WEBSITE, etc.
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    tags: Dict[str, Any] = field(default_factory=dict)
    status: LeadStatus = LeadStatus.DISCOVERED
    score: Optional[float] = None
    score_reasons: List[str] = field(default_factory=list)
    lead_tier: Optional[str] = None          # HOT, WARM, LOW
    qualified: bool = False
    qualification_notes: str = ""
    site_profile: Dict[str, Any] = field(default_factory=dict)
    personalized_message: Optional[str] = None
    email_subject: Optional[str] = None
    email_message: Optional[str] = None
    whatsapp_message: Optional[str] = None
    demo_url: Optional[str] = None
    demo_path: Optional[str] = None
    outreach_channel: Optional[str] = None
    outreach_status: Optional[str] = None
    followup_count: int = 0
    last_contacted_at: Optional[str] = None
    next_followup_due: Optional[str] = None
    id: Optional[int] = None
    run_id: Optional[int] = None
    fingerprint: Optional[str] = None
    stage_status: Optional[str] = None       # status to recover to after FAILED
    retry_count: int = 0
    last_error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_row(self) -> Dict[str, Any]:
        return {
            "external_id": self.external_id,
            "source": self.source,
            "run_id": self.run_id,
            "name": self.name,
            "category": self.category,
            "city": self.city,
            "address": self.address,
            "lat": self.lat,
            "lon": self.lon,
            "phone": self.phone,
            "phone_normalized": self.phone_normalized,
            "email": self.email,
            "website": self.website,
            "website_verified": self.website_verified,
            "website_status": self.website_status,
            "rating": self.rating,
            "reviews_count": self.reviews_count,
            "tags_json": _json_dumps(self.tags),
            "status": self.status.value,
            "score": self.score,
            "score_reasons_json": _json_dumps(self.score_reasons),
            "lead_tier": self.lead_tier,
            "qualified": 1 if self.qualified else 0,
            "qualification_notes": self.qualification_notes,
            "site_profile_json": _json_dumps(self.site_profile),
            "personalized_message": self.personalized_message,
            "email_subject": self.email_subject,
            "email_message": self.email_message,
            "whatsapp_message": self.whatsapp_message,
            "demo_url": self.demo_url,
            "demo_path": self.demo_path,
            "outreach_channel": self.outreach_channel,
            "outreach_status": self.outreach_status,
            "followup_count": self.followup_count,
            "last_contacted_at": self.last_contacted_at,
            "next_followup_due": self.next_followup_due,
            "fingerprint": self.fingerprint,
            "stage_status": self.stage_status,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "created_at": self.created_at or utcnow_iso(),
            "updated_at": self.updated_at or utcnow_iso(),
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Lead":
        return cls(
            id=row["id"],
            external_id=row["external_id"],
            source=row["source"],
            run_id=row["run_id"],
            name=row["name"],
            category=row["category"],
            city=row["city"],
            address=row["address"],
            lat=row["lat"],
            lon=row["lon"],
            phone=row["phone"],
            phone_normalized=row["phone_normalized"],
            email=row["email"],
            website=row["website"],
            website_verified=row["website_verified"],
            website_status=row.get("website_status") if "website_status" in row.keys() else None,
            rating=row["rating"],
            reviews_count=row["reviews_count"],
            tags=_json_loads(row["tags_json"]),
            status=LeadStatus(row["status"]),
            score=row["score"],
            score_reasons=_json_loads(row["score_reasons_json"]),
            lead_tier=row.get("lead_tier") if "lead_tier" in row.keys() else None,
            qualified=bool(row["qualified"]),
            qualification_notes=row["qualification_notes"] or "",
            site_profile=_json_loads(row["site_profile_json"]),
            personalized_message=row["personalized_message"],
            email_subject=row["email_subject"],
            email_message=row.get("email_message") if "email_message" in row.keys() else None,
            whatsapp_message=row.get("whatsapp_message") if "whatsapp_message" in row.keys() else None,
            demo_url=row["demo_url"],
            demo_path=row["demo_path"],
            outreach_channel=row["outreach_channel"],
            outreach_status=row["outreach_status"],
            followup_count=row.get("followup_count") or 0 if "followup_count" in row.keys() else 0,
            last_contacted_at=row.get("last_contacted_at") if "last_contacted_at" in row.keys() else None,
            next_followup_due=row.get("next_followup_due") if "next_followup_due" in row.keys() else None,
            fingerprint=row["fingerprint"],
            stage_status=row["stage_status"],
            retry_count=row["retry_count"] or 0,
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str]) -> Any:
    import json

    if not value:
        return {} if value is None else []
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}
