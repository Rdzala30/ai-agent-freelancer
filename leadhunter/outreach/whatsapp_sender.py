"""WhatsApp outreach sender for LeadHunter AI using Meta WhatsApp Cloud API.

Delivers tailored WhatsApp outreach messages to human-APPROVED leads:
- Enforces DRY_RUN safety policy
- Sends to normalized numbers with India (+91) prefix
- Meta Cloud API integration with automatic 429 backoff retry (60s)
- Rate limited to max 20 WhatsApp messages/hour
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus, utcnow_iso
from ..sheets_logger import SheetsLogger
from .email_sender import is_dry_run
from .rate_limiter import RateLimiter

log = get_logger("whatsapp_sender")


def format_india_whatsapp_phone(phone_str: Optional[str]) -> Optional[str]:
    """Format phone number with country code for WhatsApp (e.g., '+919876543210')."""
    if not phone_str:
        return None
    # Strip non-digits
    digits = re.sub(r"\D", "", phone_str)
    if not digits:
        return None

    # Handle 10-digit standard Indian mobile
    if len(digits) == 10:
        return f"+91{digits}"
    elif len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    elif digits.startswith("0") and len(digits) == 11:
        return f"+91{digits[1:]}"
    elif len(digits) >= 10:
        return f"+{digits}"
    return None


class WhatsAppSender:
    """Handles automated WhatsApp outreach via Meta WhatsApp Cloud API."""

    def __init__(
        self,
        config: Optional[Config] = None,
        db: Optional[Database] = None,
        rate_limiter: Optional[RateLimiter] = None,
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

        self.rate_limiter = rate_limiter or RateLimiter(config=self.config)
        self.sheets_logger = SheetsLogger(config=self.config, db=self.db)

        # Meta Cloud API Credentials
        self.token = (
            (self.config.get_secret("WHATSAPP_TOKEN") if self.config else None)
            or os.environ.get("WHATSAPP_TOKEN")
        )
        self.phone_number_id = (
            (self.config.get_secret("WHATSAPP_PHONE_NUMBER_ID") if self.config else None)
            or os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
        )

    def can_send(self, lead: Lead) -> Tuple[bool, str]:
        """Verify safety and deliverability conditions before dispatch."""
        tags = lead.tags or {}
        app_status = tags.get("approval_status", lead.status.value)
        if lead.status != LeadStatus.APPROVED and app_status != "APPROVED":
            return False, f"Lead is not APPROVED (status: {lead.status.value})"

        formatted_phone = format_india_whatsapp_phone(lead.phone or lead.phone_normalized)
        if not formatted_phone:
            return False, f"Missing or invalid phone number ('{lead.phone}')"

        whatsapp_status = tags.get("whatsapp_status", "")
        if whatsapp_status == "SENT" or lead.status == LeadStatus.SENT:
            return False, "WhatsApp message already sent to this lead"

        if not lead.demo_url:
            return False, "Missing demo URL"

        if lead.status == LeadStatus.DO_NOT_CONTACT or lead.status == LeadStatus.REJECTED:
            return False, "Lead is marked DO_NOT_CONTACT / REJECTED"

        can_rate, rate_reason = self.rate_limiter.can_send_whatsapp()
        if not can_rate:
            return False, rate_reason

        return True, "Ready"

    def send_whatsapp_to_lead(self, lead: Lead) -> Dict[str, Any]:
        """Send WhatsApp outreach to an individual lead, respecting DRY_RUN mode."""
        dry_run = is_dry_run(self.config)
        now = utcnow_iso()
        tags = lead.tags or {}

        from ..utils.tunnel_manager import resolve_public_demo_base_url
        public_base = resolve_public_demo_base_url(local_port=8500)

        formatted_phone = format_india_whatsapp_phone(lead.phone or lead.phone_normalized)
        message_body = lead.whatsapp_message or lead.personalized_message or f"Hi {lead.name}! View your demo: {lead.demo_url}"

        # Replace any localhost/127.0.0.1 demo links with the live public HTTPS link
        for lh in ("http://localhost:8000/preview", "http://localhost:8500/preview", "http://127.0.0.1:8000/preview", "http://127.0.0.1:8500/preview"):
            if lh in message_body:
                message_body = message_body.replace(lh, public_base)

        can, reason = self.can_send(lead)
        if not can:
            log.warning("Cannot send WhatsApp to Lead [ID %d] '%s': %s", lead.id, lead.name, reason)
            return {
                "lead_id": lead.id,
                "name": lead.name,
                "phone": formatted_phone,
                "status": "BLOCKED",
                "reason": reason,
            }

        if dry_run:
            preview_snippet = message_body.replace("\n", " ")[:120]
            print(f"DRY RUN — would send to {lead.name} ({formatted_phone}): {preview_snippet}...")

            tags["whatsapp_status"] = "DRY_RUN_SENT"
            tags["whatsapp_sent_at"] = now
            lead.tags = tags

            update_fields = {
                "tags_json": json.dumps(tags),
                "status": LeadStatus.DRY_RUN_SENT.value,
                "updated_at": now,
            }
            self.db.update_lead(lead.id, update_fields)
            self.db.transition(
                lead_id=lead.id,
                to_status=LeadStatus.DRY_RUN_SENT.value,
                stage="whatsapp_sender",
                event=f"[DRY_RUN] WhatsApp message simulated for {formatted_phone}",
                level="INFO",
            )
            self.sheets_logger.sync_lead(lead)

            return {
                "lead_id": lead.id,
                "name": lead.name,
                "phone": formatted_phone,
                "status": "DRY_RUN_SENT",
                "preview": preview_snippet,
            }

        # Real Live Send via Meta WhatsApp Cloud API
        if not self.token or not self.phone_number_id:
            error_msg = "Missing WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID"
            log.error(error_msg)
            return {"lead_id": lead.id, "name": lead.name, "status": "FAILED", "error": error_msg}

        api_url = f"https://graph.facebook.com/v18.0/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        clean_recipient = formatted_phone.replace("+", "")
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_recipient,
            "type": "text",
            "text": {"body": message_body},
        }

        # Attempt call with 429 retry
        for attempt in range(2):
            try:
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(api_url, headers=headers, json=payload)
                    if resp.status_code == 429 and attempt == 0:
                        log.warning("Meta WhatsApp Cloud API rate limited (429). Waiting 60s for retry...")
                        time.sleep(60)
                        continue

                    resp.raise_for_status()

                self.rate_limiter.record_whatsapp()
                tags["whatsapp_status"] = "SENT"
                tags["whatsapp_sent_at"] = now
                lead.tags = tags

                update_fields = {
                    "tags_json": json.dumps(tags),
                    "status": LeadStatus.SENT.value,
                    "updated_at": now,
                }
                self.db.update_lead(lead.id, update_fields)
                self.db.transition(
                    lead_id=lead.id,
                    to_status=LeadStatus.SENT.value,
                    stage="whatsapp_sender",
                    event=f"WhatsApp message delivered to {formatted_phone}",
                    level="INFO",
                )
                self.sheets_logger.sync_lead(lead)
                log.info("WhatsApp message sent successfully to Lead [ID %d] '%s' (%s)", lead.id, lead.name, formatted_phone)

                return {
                    "lead_id": lead.id,
                    "name": lead.name,
                    "phone": formatted_phone,
                    "status": "SENT",
                    "sent_at": now,
                }

            except Exception as exc:
                from ..utils.error_handler import log_error
                log_error(exc, lead_id=lead.id, context="Meta WhatsApp Cloud API")
                if attempt == 1 or "429" not in str(exc):
                    tags["whatsapp_status"] = "FAILED"
                    tags["whatsapp_error"] = str(exc)
                    lead.tags = tags
                    self.db.update_lead(lead.id, {"tags_json": json.dumps(tags), "last_error": str(exc), "updated_at": now})
                    log.error("Failed to send WhatsApp message to Lead [ID %d] '%s': %s", lead.id, lead.name, exc)
                    return {
                        "lead_id": lead.id,
                        "name": lead.name,
                        "phone": formatted_phone,
                        "status": "FAILED",
                        "error": str(exc),
                    }

        return {"lead_id": lead.id, "name": lead.name, "status": "FAILED", "error": "Unknown dispatch error"}

    def process_approved_whatsapp(
        self,
        city: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Process WhatsApp delivery for all APPROVED leads."""
        query = (
            "SELECT * FROM leads WHERE (status = 'APPROVED' OR status = 'PENDING_APPROVAL') "
            "ORDER BY id ASC LIMIT ?"
        )
        if city:
            query = (
                f"SELECT * FROM leads WHERE (status = 'APPROVED' OR status = 'PENDING_APPROVAL') "
                f"AND city = '{city}' ORDER BY id ASC LIMIT ?"
            )

        rows = self.db.conn.execute(query, (limit,)).fetchall()
        leads = [Lead.from_row(dict(r)) for r in rows]

        log.info("Processing WhatsApp outreach for %d leads (DRY_RUN=%s)...", len(leads), is_dry_run(self.config))
        results: List[Dict[str, Any]] = []

        for lead in leads:
            res = self.send_whatsapp_to_lead(lead)
            results.append(res)

        return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI WhatsApp Sender")
    parser.add_argument("--city", default="Vadodara", help="City filter")
    parser.add_argument("--limit", type=int, default=10, help="Max WhatsApp messages to process")
    args = parser.parse_args()

    sender = WhatsAppSender()
    print(f"\n=== Running WhatsApp Outreach Dispatcher (city='{args.city}', DRY_RUN={is_dry_run(sender.config)}) ===")
    results = sender.process_approved_whatsapp(city=args.city, limit=args.limit)

    print("\n==========================================================================================")
    print("                    LEADHUNTER AI — WHATSAPP OUTREACH RESULTS                             ")
    print("==========================================================================================")
    for r in results:
        phone = r.get("phone") or "No Phone"
        print(f"Lead ID {r['lead_id']:2d} | {r['name']:<38} | {phone:<15} | Status: [{r['status']}]")


if __name__ == "__main__":
    main()
