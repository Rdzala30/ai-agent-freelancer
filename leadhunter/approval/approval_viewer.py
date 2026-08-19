"""Terminal-based Human Approval Viewer and Safety Gate for LeadHunter AI.

Allows human review of PENDING_APPROVAL leads:
- Displays lead metadata, demo URL, email preview (first 3 lines), and WhatsApp preview
- Interactive prompt: [A]pprove / [R]eject / [S]kip
- Updates approval status in SQLite and Google Sheets / local CSV mirror
- Enforces strict safety rules before any outreach can proceed
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus, utcnow_iso
from ..sheets_logger import SheetsLogger

log = get_logger("approval_viewer")


def check_outreach_safety_rules(
    lead: Lead,
    config: Optional[Config] = None,
    approval_record: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, List[str]]:
    """Enforce strict 4-point safety gate:
    1. approval_status == APPROVED
    2. DRY_RUN in config / env is False
    3. Lead has not already been contacted (email_status or whatsapp_status != SENT)
    4. Lead is not marked DO_NOT_CONTACT
    """
    violations: List[str] = []

    # Rule 1: Approval check
    app_status = (
        (approval_record.get("approval_status") if approval_record else None)
        or (lead.tags.get("approval_status") if lead.tags else None)
        or (lead.status.value if lead.status == LeadStatus.APPROVED else None)
    )
    if app_status != "APPROVED" and lead.status != LeadStatus.APPROVED:
        violations.append(f"Lead is not APPROVED (current approval status: {app_status or lead.status.value})")

    # Rule 2: DRY_RUN check
    dry_run = True
    if config:
        dry_run = bool(config.get("outreach.dry_run", True))
    env_dry_run = os.environ.get("DRY_RUN") or os.environ.get("LEADHUNTER_OUTREACH_DRY_RUN")
    if env_dry_run is not None:
        dry_run = env_dry_run.lower() in ("true", "1", "yes")

    if dry_run:
        violations.append("DRY_RUN is active (outreach sending blocked by safety policy)")

    # Rule 3: Already contacted check
    tags = lead.tags or {}
    email_status = tags.get("email_status", "")
    whatsapp_status = tags.get("whatsapp_status", "")
    if email_status == "SENT" or whatsapp_status == "SENT" or lead.status == LeadStatus.SENT:
        violations.append("Lead has already been contacted (SENT status detected)")

    # Rule 4: DO_NOT_CONTACT check
    if lead.status == LeadStatus.DO_NOT_CONTACT or lead.status == LeadStatus.REJECTED or app_status == "REJECTED":
        violations.append("Lead is marked DO_NOT_CONTACT / REJECTED")

    can_send = len(violations) == 0
    return can_send, violations


class ApprovalViewer:
    """CLI viewer and controller for approving or rejecting leads."""

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
        self.sheets_logger = SheetsLogger(config=self.config, db=self.db)

    def get_pending_approvals(self, city: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all leads sitting in PENDING_APPROVAL status."""
        query = (
            "SELECT a.*, l.city, l.category, l.rating, l.reviews_count, l.phone "
            "FROM approvals a "
            "JOIN leads l ON a.lead_id = l.id "
            "WHERE a.approval_status = 'PENDING_APPROVAL' "
            "ORDER BY a.approval_id ASC"
        )
        if city:
            query = (
                "SELECT a.*, l.city, l.category, l.rating, l.reviews_count, l.phone "
                "FROM approvals a "
                "JOIN leads l ON a.lead_id = l.id "
                "WHERE a.approval_status = 'PENDING_APPROVAL' AND l.city = :city "
                "ORDER BY a.approval_id ASC"
            )
            rows = self.db.conn.execute(query, {"city": city}).fetchall()
        else:
            rows = self.db.conn.execute(query).fetchall()

        return [dict(r) for r in rows]

    def update_decision(
        self,
        lead_id: int,
        decision: str,  # 'A', 'R', 'S'
        notes: str = "",
    ) -> str:
        """Process reviewer decision:
        'A' -> APPROVED
        'R' -> REJECTED
        'S' -> PENDING_APPROVAL (skipped)
        """
        now = utcnow_iso()
        decision_upper = decision.strip().upper()

        if decision_upper.startswith("A"):
            new_approval_status = "APPROVED"
            new_lead_status = LeadStatus.APPROVED.value
            event_msg = "Lead APPROVED by reviewer for outreach"
        elif decision_upper.startswith("R"):
            new_approval_status = "REJECTED"
            new_lead_status = LeadStatus.REJECTED.value
            event_msg = "Lead REJECTED by reviewer (do not contact)"
        else:
            log.info("Lead [ID %d] skipped by reviewer", lead_id)
            return "SKIPPED"

        # 1. Update approvals table
        self.db.conn.execute(
            """UPDATE approvals SET
                approval_status = ?,
                reviewed_at = ?,
                notes = ?,
                updated_at = ?
            WHERE lead_id = ?""",
            (new_approval_status, now, notes, now, lead_id),
        )
        self.db.conn.commit()

        # 2. Update lead tags and status
        lead = self.db.get_lead(lead_id)
        tags = lead.tags or {}
        tags["approval_status"] = new_approval_status
        tags["reviewed_at"] = now
        lead.tags = tags

        update_fields = {
            "tags_json": json.dumps(tags),
            "status": new_lead_status,
            "updated_at": now,
        }
        self.db.update_lead(lead_id, update_fields)

        self.db.transition(
            lead_id=lead_id,
            to_status=new_lead_status,
            stage="approval_gate",
            event=event_msg,
            level="INFO",
        )

        lead.status = LeadStatus(new_lead_status)
        log.info("Lead [ID %d] -> %s (approval: %s)", lead_id, new_lead_status, new_approval_status)

        # 3. Synchronize with Google Sheets & local CSV
        self.sheets_logger.sync_lead(lead)

        return new_approval_status

    def review_interactive(
        self,
        city: Optional[str] = None,
        default_decision: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """CLI interactive review session."""
        pending = self.get_pending_approvals(city=city)
        if not pending:
            print("\n✅ No leads pending human approval!")
            return []

        print("\n" + "=" * 90)
        print(f"         LEADHUNTER AI — HUMAN APPROVAL QUEUE ({len(pending)} Leads Pending Review)")
        print("=" * 90)

        reviewed_results = []

        for idx, item in enumerate(pending, start=1):
            lead_id = item["lead_id"]
            name = item["business_name"]
            score = item["lead_score"]
            tier = item["lead_tier"]
            site_status = item["website_status"]
            demo_url = item["demo_url"]
            email_msg = item["email_message"] or ""
            wa_msg = item["whatsapp_message"] or ""

            # Extract first 3 lines of email
            email_lines = [l for l in email_msg.strip().splitlines() if l.strip()]
            email_preview = "\n      ".join(email_lines[:3])

            print(f"\n[{idx}/{len(pending)}] Lead ID: {lead_id} | {name}")
            print("-" * 90)
            print(f"  • Tier / Score   : {tier} | {score}/100")
            print(f"  • Website Status : {site_status}")
            print(f"  • Demo URL       : {demo_url}")
            print(f"\n  📧 Cold Email Preview (First 3 lines):")
            print(f"      {email_preview}")
            print(f"\n  📱 WhatsApp Message Preview:")
            print(f"      {wa_msg}")
            print("-" * 90)

            if default_decision:
                choice = default_decision
                print(f"  Action (auto): {choice}")
            else:
                try:
                    choice = input("  Action: [A]pprove / [R]eject / [S]kip (default: A): ").strip() or "A"
                except EOFError:
                    choice = "A"

            status = self.update_decision(lead_id, choice)
            print(f"  Result -> [{status}]")

            reviewed_results.append({
                "lead_id": lead_id,
                "name": name,
                "tier": tier,
                "score": score,
                "demo_url": demo_url,
                "decision": status,
            })

        return reviewed_results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI Approval Viewer")
    parser.add_argument("--city", default="Vadodara", help="City filter")
    parser.add_argument("--auto", choices=["A", "R", "S"], default="A", help="Auto-decision for non-interactive test")
    args = parser.parse_args()

    viewer = ApprovalViewer()
    results = viewer.review_interactive(city=args.city, default_decision=args.auto)

    print("\n==========================================================================================")
    print("                      LEADHUNTER AI — APPROVAL SUMMARY                                    ")
    print("==========================================================================================")
    for r in results:
        badge = "✅ APPROVED" if r["decision"] == "APPROVED" else ("❌ REJECTED" if r["decision"] == "REJECTED" else "⏳ SKIPPED")
        print(f"Lead ID {r['lead_id']:2d} | {r['name']:<38} | {badge}")


if __name__ == "__main__":
    main()
