"""Lead lifecycle state machine — the single source of truth for transitions.

Every status change goes through db.transition(), which consults this module.
No lead may jump stages illegally; recovery from FAILED is the only
"backwards" motion, and it is explicit.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Set

from .errors import StateTransitionError
from .models import LeadStatus as S

# allowed transitions: from -> set(to)
ALLOWED: Dict[str, FrozenSet[str]] = {
    S.DISCOVERED.value: frozenset({S.ENRICHED.value, S.VERIFIED.value, S.FAILED.value, S.DISCARDED.value, S.DO_NOT_CONTACT.value, S.DUPLICATE.value}),
    S.ENRICHED.value: frozenset({S.VERIFIED.value, S.FAILED.value, S.DISCARDED.value, S.DO_NOT_CONTACT.value, S.DUPLICATE.value}),
    S.VERIFIED.value: frozenset({S.QUALIFIED.value, S.FAILED.value, S.DISCARDED.value, S.DO_NOT_CONTACT.value, S.DUPLICATE.value}),
    S.QUALIFIED.value: frozenset({S.SCORED.value, S.PERSONALIZED.value, S.FAILED.value, S.DISCARDED.value, S.DO_NOT_CONTACT.value, S.DUPLICATE.value}),
    S.SCORED.value: frozenset({S.PERSONALIZED.value, S.FAILED.value, S.DISCARDED.value, S.DO_NOT_CONTACT.value, S.DUPLICATE.value}),
    S.PERSONALIZED.value: frozenset({S.DEMO_READY.value, S.FAILED.value, S.DO_NOT_CONTACT.value, S.DUPLICATE.value}),
    S.DEMO_READY.value: frozenset({S.PENDING_APPROVAL.value, S.FAILED.value, S.DO_NOT_CONTACT.value, S.DUPLICATE.value}),
    S.PENDING_APPROVAL.value: frozenset({S.APPROVED.value, S.REJECTED.value, S.SENT.value, S.FAILED.value, S.DO_NOT_CONTACT.value, S.DUPLICATE.value}),
    S.APPROVED.value: frozenset({S.SENT.value, S.DRY_RUN_SENT.value, S.FAILED.value, S.DO_NOT_CONTACT.value}),
    S.DRY_RUN_SENT.value: frozenset({S.SENT.value, S.REPLIED.value, S.CONVERTED.value, S.COLD.value, S.PENDING_APPROVAL.value, S.FAILED.value, S.DO_NOT_CONTACT.value}),
    S.REJECTED.value: frozenset({S.DO_NOT_CONTACT.value}),
    S.SENT.value: frozenset({S.REPLIED.value, S.CONVERTED.value, S.COLD.value, S.PENDING_APPROVAL.value, S.DO_NOT_CONTACT.value}),
    S.COLD.value: frozenset({S.REPLIED.value, S.CONVERTED.value, S.DO_NOT_CONTACT.value}),
    S.REPLIED.value: frozenset({S.CONVERTED.value, S.DO_NOT_CONTACT.value}),
    # FAILED may recover into any stage-input status (set by the pipeline).
    S.FAILED.value: frozenset(
        {
            S.DISCOVERED.value,
            S.ENRICHED.value,
            S.VERIFIED.value,
            S.QUALIFIED.value,
            S.SCORED.value,
            S.PERSONALIZED.value,
            S.DEMO_READY.value,
            S.PENDING_APPROVAL.value,
            S.APPROVED.value,
            S.COLD.value,
            S.DO_NOT_CONTACT.value,
            S.DISCARDED.value,
            S.DUPLICATE.value,
        }
    ),
}

TERMINAL: Set[str] = {S.DISCARDED.value, S.DO_NOT_CONTACT.value, S.CONVERTED.value, S.DUPLICATE.value, S.REJECTED.value, S.COLD.value}


def can_transition(from_status: str, to_status: str) -> bool:
    allowed = ALLOWED.get(from_status, frozenset())
    return to_status in allowed


def assert_transition(from_status: str, to_status: str) -> None:
    if not can_transition(from_status, to_status):
        raise StateTransitionError(
            f"illegal transition {from_status} -> {to_status}"
        )


def is_terminal(status: str) -> bool:
    return status in TERMINAL


def stage_statuses() -> Set[str]:
    """All non-terminal lifecycle statuses a lead can sit at."""
    return {
        s.value
        for s in (
            S.DISCOVERED,
            S.ENRICHED,
            S.VERIFIED,
            S.QUALIFIED,
            S.SCORED,
            S.PERSONALIZED,
            S.DEMO_READY,
            S.PENDING_APPROVAL,
            S.SENT,
            S.FAILED,
        )
    }
