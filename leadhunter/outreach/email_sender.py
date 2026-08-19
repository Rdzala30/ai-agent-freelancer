"""Email outreach sender for LeadHunter AI using Gmail SMTP.

Delivers personalized cold emails to human-APPROVED leads:
- Enforces DRY_RUN safety policy
- Connects to Gmail SMTP using SENDER_EMAIL and GMAIL_APP_PASSWORD
- Pre-flight validation (approved, valid email, not sent, active demo URL, not DNC)
- 3-second inter-message delay
- Rate limited to max 10 emails/hour
"""

from __future__ import annotations

import email.utils
import json
import os
import re
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus, utcnow_iso
from ..sheets_logger import SheetsLogger
from .rate_limiter import RateLimiter

log = get_logger("email_sender")

EMAIL_REGEX = re.compile(r"^[\w\.\+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-\.]+$")


def is_valid_email(email_str: Optional[str]) -> bool:
    if not email_str or not isinstance(email_str, str):
        return False
    return bool(EMAIL_REGEX.match(email_str.strip()))


def is_dry_run(config: Optional[Config] = None) -> bool:
    """Determine if system is running in DRY_RUN mode (defaults to True)."""
    env_dry = os.environ.get("DRY_RUN") or os.environ.get("LEADHUNTER_OUTREACH_DRY_RUN")
    if env_dry is not None:
        return env_dry.lower() in ("true", "1", "yes")
    if config:
        return bool(config.get("outreach.dry_run", True))
    return True


class EmailSender:
    """Handles cold email outreach via Gmail SMTP."""

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

        # Credentials
        self.sender_email = (
            (self.config.get_secret("SENDER_EMAIL") if self.config else None)
            or os.environ.get("SENDER_EMAIL")
            or "consultant@example.com"
        )
        self.sender_name = (
            (self.config.get_secret("SENDER_NAME") if self.config else None)
            or os.environ.get("SENDER_NAME")
            or "Web Design Consultant"
        )
        raw_pwd = (
            (self.config.get_secret("GMAIL_APP_PASSWORD") if self.config else None)
            or (self.config.get_secret("SMTP_PASS") if self.config else None)
            or os.environ.get("GMAIL_APP_PASSWORD")
            or os.environ.get("SMTP_PASS")
        )
        self.app_password = raw_pwd.replace(" ", "").strip() if raw_pwd else None

    def can_send(self, lead: Lead) -> Tuple[bool, str]:
        """Verify pre-flight requirements for email delivery."""
        # 1. Approval status
        tags = lead.tags or {}
        app_status = tags.get("approval_status", lead.status.value)
        if lead.status != LeadStatus.APPROVED and app_status != "APPROVED":
            return False, f"Lead is not APPROVED (status: {lead.status.value})"

        # 2. Valid email
        if not is_valid_email(lead.email):
            return False, f"Missing or invalid email address ('{lead.email}')"

        # 3. Already sent check
        email_status = tags.get("email_status", "")
        if email_status == "SENT" or lead.status == LeadStatus.SENT:
            return False, "Email already sent to this lead"

        # 4. Working Demo URL
        if not lead.demo_url:
            return False, "Missing demo URL"

        # 5. DNC check
        if lead.status == LeadStatus.DO_NOT_CONTACT or lead.status == LeadStatus.REJECTED:
            return False, "Lead is marked DO_NOT_CONTACT / REJECTED"

        # 6. Rate limit check
        can_rate, rate_reason = self.rate_limiter.can_send_email()
        if not can_rate:
            return False, rate_reason

        return True, "Ready"

    def send_email_to_lead(self, lead: Lead) -> Dict[str, Any]:
        """Send email to an individual lead, respecting DRY_RUN mode."""
        dry_run = is_dry_run(self.config)
        now = utcnow_iso()
        tags = lead.tags or {}

        from ..utils.tunnel_manager import resolve_public_demo_base_url
        public_base = resolve_public_demo_base_url(local_port=8500)

        subject = lead.email_subject or f"Website concept for {lead.name}"
        body = lead.email_message or f"Hi {lead.name},\n\nCheck your website preview: {lead.demo_url}"

        # Replace any localhost/127.0.0.1 demo links with the live public HTTPS link
        for lh in ("http://localhost:8000/preview", "http://localhost:8500/preview", "http://127.0.0.1:8000/preview", "http://127.0.0.1:8500/preview"):
            if lh in body:
                body = body.replace(lh, public_base)

        # If lead has no email, note it clearly
        if not lead.email:
            preview_snippet = body.replace("\n", " ")[:100]
            if dry_run:
                print(f"DRY RUN — would send to {lead.name} [No Email on File — Skipped]: {preview_snippet}...")
            return {
                "lead_id": lead.id,
                "name": lead.name,
                "email": None,
                "status": "SKIPPED_NO_EMAIL",
                "mode": "DRY_RUN" if dry_run else "LIVE",
            }

        can, reason = self.can_send(lead)
        if not can:
            log.warning("Cannot send email to Lead [ID %d] '%s': %s", lead.id, lead.name, reason)
            return {
                "lead_id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "status": "BLOCKED",
                "reason": reason,
            }

        if dry_run:
            preview_snippet = body.replace("\n", " ")[:120]
            print(f"DRY RUN — would send to {lead.name}: {preview_snippet}...")

            tags["email_status"] = "DRY_RUN_SENT"
            tags["email_sent_at"] = now
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
                stage="email_sender",
                event=f"[DRY_RUN] Email simulated for {lead.email}",
                level="INFO",
            )
            self.sheets_logger.sync_lead(lead)

            return {
                "lead_id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "status": "DRY_RUN_SENT",
                "subject": subject,
                "preview": preview_snippet,
            }

        # Real Live Send via Gmail SMTP
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = email.utils.formataddr((self.sender_name, self.sender_email))
            msg["To"] = lead.email
            msg.attach(MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15.0) as server:
                server.starttls()
                server.login(self.sender_email, self.app_password)
                server.sendmail(self.sender_email, [lead.email], msg.as_string())

            self.rate_limiter.record_email()
            tags["email_status"] = "SENT"
            tags["email_sent_at"] = now
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
                stage="email_sender",
                event=f"Email successfully delivered to {lead.email}",
                level="INFO",
            )
            self.sheets_logger.sync_lead(lead)
            log.info("Email sent successfully to Lead [ID %d] '%s' (%s)", lead.id, lead.name, lead.email)

            return {
                "lead_id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "status": "SENT",
                "sent_at": now,
            }

        except Exception as exc:
            from ..utils.error_handler import log_error
            log_error(exc, lead_id=lead.id, context="Email Outreach Delivery")
            tags["email_status"] = "FAILED"
            tags["email_error"] = str(exc)
            lead.tags = tags
            self.db.update_lead(lead.id, {"tags_json": json.dumps(tags), "last_error": str(exc), "updated_at": now})
            log.error("Failed to deliver email to Lead [ID %d] '%s': %s", lead.id, lead.name, exc)
            return {
                "lead_id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "status": "FAILED",
                "error": str(exc),
            }

    def process_approved_emails(
        self,
        city: Optional[str] = None,
        limit: int = 10,
        delay_s: float = 3.0,
    ) -> List[Dict[str, Any]]:
        """Process email delivery for all APPROVED leads."""
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

        log.info("Processing email outreach for %d leads (DRY_RUN=%s)...", len(leads), is_dry_run(self.config))
        results: List[Dict[str, Any]] = []

        for idx, lead in enumerate(leads):
            if idx > 0 and delay_s > 0 and not is_dry_run(self.config):
                time.sleep(delay_s)

            res = self.send_email_to_lead(lead)
            results.append(res)

        return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI Email Sender")
    parser.add_argument("--city", default="Vadodara", help="City filter")
    parser.add_argument("--limit", type=int, default=10, help="Max emails to process")
    args = parser.parse_args()

    sender = EmailSender()
    print(f"\n=== Running Email Outreach Dispatcher (city='{args.city}', DRY_RUN={is_dry_run(sender.config)}) ===")
    results = sender.process_approved_emails(city=args.city, limit=args.limit)

    print("\n==========================================================================================")
    print("                      LEADHUNTER AI — EMAIL OUTREACH RESULTS                              ")
    print("==========================================================================================")
    for r in results:
        print(f"Lead ID {r['lead_id']:2d} | {r['name']:<38} | Status: [{r['status']}]")


if __name__ == "__main__":
    main()
