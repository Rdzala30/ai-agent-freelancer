"""Follow-up package for LeadHunter AI."""

from .followup_engine import (
    DEFAULT_SCHEDULE,
    FollowupEngine,
    generate_followup_message,
    generate_followup_template,
    is_lead_eligible_for_followup,
)

__all__ = [
    "FollowupEngine",
    "is_lead_eligible_for_followup",
    "generate_followup_message",
    "generate_followup_template",
    "DEFAULT_SCHEDULE",
]
