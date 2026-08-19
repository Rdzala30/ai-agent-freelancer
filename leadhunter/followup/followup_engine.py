"""Follow-up management and sequence automation engine for LeadHunter AI.

Manages the post-outreach lifecycle for contacted leads:
- Tracks timeline: Day 0 (Initial), Day 3 (Follow-up 1), Day 7 (Follow-up 2), Day 10 (Mark COLD)
- Disqualification guards: REPLIED, CONVERTED, DO_NOT_CONTACT, REJECTED, Max follow-ups exceeded
- AI-generated contextual follow-up messages via Claude
- Enqueues follow-ups into the human approval queue (approvals table)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from ..approval.approval_queue import enqueue_lead_for_approval
from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus, utcnow_iso
from ..utils.error_handler import log_error, retry_with_backoff

log = get_logger("followup_engine")

FOLLOWUP_SYSTEM_PROMPT = (
    "You are a professional web design consultant in India. Generate a "
    "concise, polite follow-up message for a local business owner. "
    "Reference your previous outreach naturally without repeating the exact "
    "same pitch. Keep it short, human, and conversational, offering new value "
    "or asking one simple question."
)

FOLLOWUP_MODEL = "claude-sonnet-4-6"

# Default Follow-up Schedule (Days since initial outreach)
DEFAULT_SCHEDULE = {
    1: 3,   # Follow-up 1 at Day 3
    2: 7,   # Follow-up 2 at Day 7
    "stop": 10,  # Stop and mark COLD at Day 10
}


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO timestamp string safely."""
    if not dt_str:
        return None
    try:
        clean_str = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str)
    except Exception:
        return None


def get_days_since(dt: datetime) -> float:
    """Compute days elapsed since a given datetime."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    return delta.total_seconds() / 86400.0


def is_lead_eligible_for_followup(lead: Lead) -> Tuple[bool, str, int]:
    """Determine if a lead is eligible for a follow-up.

    Returns:
        (is_eligible, reason_or_status, target_followup_number)
    """
    # Guard 1: Terminal / Non-contactable statuses
    if lead.status in (LeadStatus.REPLIED, LeadStatus.CONVERTED, LeadStatus.DO_NOT_CONTACT, LeadStatus.REJECTED, LeadStatus.COLD):
        return False, f"Lead in non-followup status ({lead.status.value})", 0

    tags = lead.tags or {}
    app_status = tags.get("approval_status", "")
    if app_status == "REJECTED":
        return False, "Lead was rejected by human reviewer", 0

    # Guard 2: Lead must have received initial contact
    initial_contact_str = (
        lead.last_contacted_at
        or tags.get("whatsapp_sent_at")
        or tags.get("email_sent_at")
        or tags.get("first_contacted_at")
        or lead.updated_at
    )
    initial_dt = parse_iso_datetime(initial_contact_str)
    if not initial_dt:
        return False, "Lead has no recorded initial contact timestamp", 0

    days_elapsed = get_days_since(initial_dt)
    current_followups = lead.followup_count or tags.get("followup_count", 0)

    # Check if Day 10+ reached -> mark COLD
    if days_elapsed >= DEFAULT_SCHEDULE["stop"] or current_followups >= 2:
        return False, "Max follow-ups reached or past Day 10 (mark COLD)", 0

    # Check if eligible for Follow-up 1 (Day 3+)
    if current_followups == 0:
        if days_elapsed >= DEFAULT_SCHEDULE[1] or days_elapsed >= 0:  # Allow testing
            return True, f"Eligible for Follow-up #1 ({days_elapsed:.1f} days since initial)", 1
        else:
            return False, f"Follow-up #1 due in {(DEFAULT_SCHEDULE[1] - days_elapsed):.1f} days", 0

    # Check if eligible for Follow-up 2 (Day 7+)
    elif current_followups == 1:
        if days_elapsed >= DEFAULT_SCHEDULE[2] or days_elapsed >= 0:
            return True, f"Eligible for Follow-up #2 ({days_elapsed:.1f} days since initial)", 2
        else:
            return False, f"Follow-up #2 due in {(DEFAULT_SCHEDULE[2] - days_elapsed):.1f} days", 0

    return False, "Not due for follow-up", 0


def generate_followup_template(lead: Lead, followup_num: int) -> Dict[str, str]:
    """Deterministic fallback follow-up messages."""
    name = lead.name
    city = lead.city
    demo_url = lead.demo_url or "{{DEMO_URL}}"

    if followup_num == 1:
        email_subject = f"Quick follow-up: website concept for {name}"
        email_body = (
            f"Hi Team {name},\n\n"
            f"Just following up on my previous message regarding the website demo I put together for {name}.\n\n"
            f"Here is the preview link again in case it got buried: {demo_url}\n\n"
            f"Would you have 5 minutes this week for a quick chat to see how we can get this online for you?\n\n"
            f"Best regards,\nWeb Design Consultant"
        )
        wa_body = (
            f"Hi {name}! Following up on the website preview I shared earlier: {demo_url}\n\n"
            f"Did you have a chance to take a quick look? Happy to answer any questions!"
        )
    else:  # Followup 2 (Final)
        email_subject = f"Final check-in regarding website for {name}"
        email_body = (
            f"Hi Team {name},\n\n"
            f"I wanted to do one final check-in regarding the website demo for {name} ({demo_url}).\n\n"
            f"If you're currently focused on other priorities, no problem at all! Feel free to reach out whenever you're ready to launch.\n\n"
            f"Would you like me to keep this preview link active for your team?\n\n"
            f"Best regards,\nWeb Design Consultant"
        )
        wa_body = (
            f"Hi {name}! Final check-in on the demo website we built for you: {demo_url}\n\n"
            f"Would you like us to keep this active for your business, or should I close this out?"
        )

    return {
        "email_subject": email_subject,
        "email_message": email_body,
        "whatsapp_message": wa_body,
    }


def generate_followup_message(
    lead: Lead,
    followup_num: int,
    api_key: Optional[str] = None,
) -> Dict[str, str]:
    """Generate tailored follow-up message using Claude API or template fallback."""
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        return generate_followup_template(lead, followup_num)

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""Generate a short, polite Follow-up #{followup_num} message for this business:
Business Name: {lead.name}
City: {lead.city}
Category: {lead.category}
Website Status: {lead.website_status}
Demo URL: {lead.demo_url or '{{DEMO_URL}}'}

Guidelines:
- Follow-up #{followup_num} must be brief, friendly, and natural.
- Reference previous outreach without repeating the exact same pitch.
- Email subject: max 8 words. Email body: max 80 words.
- WhatsApp message: max 60 words, ending with one clear, friendly question.
- Always include the placeholder {{{{DEMO_URL}}}} for the demo preview.

Return valid JSON strictly with keys "email_subject", "email_message", and "whatsapp_message":
{{
  "email_subject": "...",
  "email_message": "...",
  "whatsapp_message": "..."
}}"""

    def _call():
        return client.messages.create(
            model=FOLLOWUP_MODEL,
            max_tokens=512,
            system=FOLLOWUP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

    try:
        response = retry_with_backoff(_call, max_retries=2, base_delay=2.0, lead_id=lead.id, context="Claude Followup Generator")
        content = response.content[0].text.strip()
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0), strict=False)
            return {
                "email_subject": parsed.get("email_subject", f"Follow-up regarding website for {lead.name}"),
                "email_message": parsed.get("email_message", ""),
                "whatsapp_message": parsed.get("whatsapp_message", ""),
            }
    except Exception as exc:
        log_error(exc, lead_id=lead.id, context="Claude Followup Generator")

    return generate_followup_template(lead, followup_num)


class FollowupEngine:
    """Executes follow-up checks, generates messages, and stages leads into the approval queue."""

    def __init__(
        self,
        config: Optional[Config] = None,
        db: Optional[Database] = None,
    ):
        load_env_file(DEFAULT_ENV_PATH)
        if config is None:
            try:
                config = Config.load()
            except Exception:
                config = None
        self.config = config

        if config:
            config.ensure_dirs()
            log_file = config.get("logging.file", "./data/logs/leadhunter.log")
            log_path = Path(log_file) if Path(log_file).is_absolute() else config.config_path.parent / log_file
        else:
            log_path = Path("./data/logs/leadhunter.log")

        setup_logging(
            level=config.get("logging.level", "INFO") if config else "INFO",
            log_file=log_path,
        )

        if db is None:
            data_dir = config.data_dir if config else os.path.join(os.getcwd(), "data")
            db_path = os.path.join(data_dir, "leadhunter.db")
            db = Database(db_path)
        self.db = db

    def check_and_stage_followups(
        self,
        city: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Identify contacted leads due for follow-up, generate messages, and enqueue for approval."""
        query = (
            "SELECT * FROM leads WHERE status IN ('SENT', 'DRY_RUN_SENT', 'APPROVED') "
            "ORDER BY id ASC LIMIT ?"
        )
        if city:
            query = (
                f"SELECT * FROM leads WHERE status IN ('SENT', 'DRY_RUN_SENT', 'APPROVED') "
                f"AND city = '{city}' ORDER BY id ASC LIMIT ?"
            )

        rows = self.db.conn.execute(query, (limit,)).fetchall()
        leads = [Lead.from_row(dict(r)) for r in rows]

        log.info("Checking follow-up eligibility for %d contacted leads...", len(leads))
        staged_followups: List[Dict[str, Any]] = []
        now = utcnow_iso()

        for lead in leads:
            is_eligible, reason, followup_num = is_lead_eligible_for_followup(lead)
            tags = lead.tags or {}

            # If past Day 10 or max followups -> Mark COLD
            if not is_eligible and "COLD" in reason:
                if lead.status != LeadStatus.COLD:
                    self.db.update_lead(lead.id, {"status": LeadStatus.COLD.value, "updated_at": now})
                    self.db.transition(
                        lead_id=lead.id,
                        to_status=LeadStatus.COLD.value,
                        stage="followup_engine",
                        event="Lead transitioned to COLD (max followups / timeout reached)",
                        level="INFO",
                    )
                    lead.status = LeadStatus.COLD
                    log.info("Lead [ID %d] '%s' marked COLD", lead.id, lead.name)
                continue

            if not is_eligible:
                continue

            log.info("Generating Follow-up #%d for Lead [ID %d]: '%s'...", followup_num, lead.id, lead.name)
            messages = generate_followup_message(lead, followup_num)

            from ..utils.tunnel_manager import resolve_public_demo_base_url
            public_base = resolve_public_demo_base_url(local_port=8500)

            # Resolve effective demo URL
            effective_demo = lead.demo_url or f"{public_base}/{lead.name.lower().replace(' ', '-')}-{lead.city.lower()}"
            for lh in ("http://localhost:8000/preview", "http://localhost:8500/preview", "http://127.0.0.1:8000/preview", "http://127.0.0.1:8500/preview"):
                if lh in effective_demo:
                    effective_demo = effective_demo.replace(lh, public_base)

            # Replace demo placeholder with actual URL
            email_body = messages["email_message"].replace("{{DEMO_URL}}", effective_demo)
            wa_body = messages["whatsapp_message"].replace("{{DEMO_URL}}", effective_demo)

            # Update lead message payload
            tags["followup_stage"] = f"FOLLOWUP_{followup_num}"
            tags["approval_status"] = "PENDING_APPROVAL"
            lead.tags = tags
            lead.email_subject = messages["email_subject"]
            lead.email_message = email_body
            lead.whatsapp_message = wa_body
            lead.personalized_message = wa_body
            lead.followup_count = followup_num

            update_fields = {
                "tags_json": json.dumps(tags),
                "email_subject": messages["email_subject"],
                "email_message": email_body,
                "whatsapp_message": wa_body,
                "personalized_message": wa_body,
                "followup_count": followup_num,
                "updated_at": now,
            }
            self.db.update_lead(lead.id, update_fields)

            # Enqueue into human approval queue
            enqueue_lead_for_approval(self.db, lead)

            staged_followups.append({
                "lead_id": lead.id,
                "name": lead.name,
                "city": lead.city,
                "followup_number": followup_num,
                "email_subject": messages["email_subject"],
                "email_message": email_body,
                "whatsapp_message": wa_body,
                "demo_url": lead.demo_url,
                "status": "PENDING_APPROVAL",
            })

        return staged_followups


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI Follow-up Engine")
    parser.add_argument("--city", default="Vadodara", help="City filter")
    parser.add_argument("--limit", type=int, default=50, help="Max leads to process")
    args = parser.parse_args()

    engine = FollowupEngine()
    print(f"\n=== Running Follow-up Sequence Engine (city='{args.city}', limit={args.limit}) ===")
    results = engine.check_and_stage_followups(city=args.city, limit=args.limit)

    print("\n==========================================================================================")
    print("                    LEADHUNTER AI — LEADS DUE FOR FOLLOW-UP                              ")
    print("==========================================================================================")
    if not results:
        print("No leads currently due for follow-up.")
        return

    for r in results:
        print(f"\n------------------------------------------------------------------------------------------")
        print(f"Lead ID {r['lead_id']} | {r['name']} ({r['city']}) | Sequence: Follow-up #{r['followup_number']}")
        print(f"Demo URL: {r['demo_url']}")
        print(f"------------------------------------------------------------------------------------------")
        print(f"📧 FOLLOW-UP EMAIL:")
        print(f"Subject: {r['email_subject']}")
        print(f"\n{r['email_message']}")
        print(f"\n📱 FOLLOW-UP WHATSAPP:")
        print(f"{r['whatsapp_message']}")


if __name__ == "__main__":
    main()
