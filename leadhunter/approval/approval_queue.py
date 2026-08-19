"""Approval queue module for LeadHunter AI.

Enqueues leads with ready demos into the 'approvals' table with status PENDING_APPROVAL.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus, utcnow_iso

log = get_logger("approval_queue")


def enqueue_lead_for_approval(
    db: Database,
    lead: Lead,
) -> int:
    """Insert or update a lead record into the 'approvals' SQLite table."""
    now = utcnow_iso()
    cur = db.conn.execute(
        """INSERT INTO approvals (
            lead_id, business_name, lead_score, lead_tier,
            email_message, whatsapp_message, demo_url, website_status,
            approval_status, reviewed_at, notes, created_at, updated_at
        ) VALUES (
            :lead_id, :business_name, :lead_score, :lead_tier,
            :email_message, :whatsapp_message, :demo_url, :website_status,
            :approval_status, :reviewed_at, :notes, :created_at, :updated_at
        ) ON CONFLICT(lead_id) DO UPDATE SET
            business_name=excluded.business_name,
            lead_score=excluded.lead_score,
            lead_tier=excluded.lead_tier,
            email_message=excluded.email_message,
            whatsapp_message=excluded.whatsapp_message,
            demo_url=excluded.demo_url,
            website_status=excluded.website_status,
            approval_status='PENDING_APPROVAL',
            reviewed_at=NULL,
            updated_at=excluded.updated_at
        """,
        {
            "lead_id": lead.id,
            "business_name": lead.name,
            "lead_score": lead.score,
            "lead_tier": lead.lead_tier,
            "email_message": lead.email_message or "",
            "whatsapp_message": lead.whatsapp_message or lead.personalized_message or "",
            "demo_url": lead.demo_url or "",
            "website_status": lead.website_status or "",
            "approval_status": "PENDING_APPROVAL",
            "reviewed_at": None,
            "notes": lead.qualification_notes or "",
            "created_at": now,
            "updated_at": now,
        },
    )
    db.conn.commit()
    approval_id = int(cur.lastrowid)

    # Transition lead status to PENDING_APPROVAL if not already there
    if lead.status != LeadStatus.PENDING_APPROVAL:
        db.transition(
            lead_id=lead.id,
            to_status=LeadStatus.PENDING_APPROVAL.value,
            stage="approval_queue",
            event="Lead enqueued for human approval",
            level="INFO",
        )
        lead.status = LeadStatus.PENDING_APPROVAL

    log.info("Enqueued Lead [ID %d] '%s' into approval queue (status: PENDING_APPROVAL)", lead.id, lead.name)
    return approval_id


def process_approval_queue(
    db: Optional[Database] = None,
    config: Optional[Config] = None,
    city: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Scan leads with DEMO_READY or (PERSONALIZED with READY demo) and queue them for approval."""
    load_env_file(DEFAULT_ENV_PATH)
    if config is None:
        try:
            config = Config.load()
        except Exception:
            config = None

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

    # Query leads that are DEMO_READY or (PERSONALIZED with demo_status READY)
    query = (
        "SELECT * FROM leads WHERE "
        "(status = 'DEMO_READY' OR (status = 'PERSONALIZED' AND demo_status = 'READY') "
        " OR status = 'PENDING_APPROVAL') "
        "ORDER BY id ASC LIMIT ?"
    )
    if city:
        query = (
            f"SELECT * FROM leads WHERE "
            f"(status = 'DEMO_READY' OR (status = 'PERSONALIZED' AND demo_status = 'READY') "
            f" OR status = 'PENDING_APPROVAL') AND city = '{city}' "
            f"ORDER BY id ASC LIMIT ?"
        )

    rows = db.conn.execute(query, (limit,)).fetchall()
    leads = [Lead.from_row(dict(r)) for r in rows]

    log.info("Processing %d eligible leads for human approval queue...", len(leads))
    results: List[Dict[str, Any]] = []

    for lead in leads:
        approval_id = enqueue_lead_for_approval(db, lead)
        results.append({
            "approval_id": approval_id,
            "lead_id": lead.id,
            "name": lead.name,
            "city": lead.city,
            "lead_tier": lead.lead_tier,
            "lead_score": lead.score,
            "website_status": lead.website_status,
            "demo_url": lead.demo_url,
            "status": lead.status.value,
        })

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI Approval Queue")
    parser.add_argument("--city", default="Vadodara", help="City name filter")
    parser.add_argument("--limit", type=int, default=50, help="Max leads to queue")
    args = parser.parse_args()

    print(f"\n=== Enqueuing Leads for Human Approval (city='{args.city}', limit={args.limit}) ===")
    results = process_approval_queue(city=args.city, limit=args.limit)

    print("\n==========================================================================================")
    print("                      LEADHUNTER AI — APPROVAL QUEUE STATUS                               ")
    print("==========================================================================================")
    for r in results:
        print(f"Lead ID {r['lead_id']:2d} | {r['name']:<38} | Tier: {str(r['lead_tier']):<4} | Score: {r['lead_score']} | Demo: {r['demo_url']}")


if __name__ == "__main__":
    main()
