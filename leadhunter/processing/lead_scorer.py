"""Lead scoring and qualification module for LeadHunter AI.

Evaluates leads sitting at status 'VERIFIED' against website and business signals:
- Website signals:
    NO_WEBSITE = 40 points
    BROKEN_WEBSITE = 35 points
    SOCIAL_ONLY = 30 points
    DIRECTORY_ONLY = 28 points
    DOMAIN_ONLY = 20 points
    VALID_WEBSITE = 0 points (skip as lead)
- Business signals:
    Has phone number = +15
    Has email = +10
    Rating 4.0+ with 20+ reviews = +15 (strong local presence, needs web)
    Rating 3.0–3.9 with reviews = +8
    Has Instagram = +5
    Target Category (restaurant/hotel/clinic/salon/gym/shop/etc.) = +10

Assigns lead_tier:
    Score 70+ = HOT   -> status = QUALIFIED (qualified = 1)
    Score 45–69 = WARM -> status = QUALIFIED (qualified = 1)
    Score < 45 = LOW  -> saved with qualified = 0 (not processed further)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus
from .website_checker import (
    STATUS_BROKEN_WEBSITE,
    STATUS_DIRECTORY_ONLY,
    STATUS_DOMAIN_ONLY,
    STATUS_NO_WEBSITE,
    STATUS_SOCIAL_ONLY,
    STATUS_UNKNOWN,
    STATUS_VALID_WEBSITE,
)

log = get_logger("lead_scorer")

# Target commercial SMB categories that benefit heavily from web presence
TARGET_CATEGORIES: Set[str] = {
    "restaurant",
    "cafe",
    "hotel",
    "resort",
    "clinic",
    "hospital",
    "doctor",
    "dentist",
    "salon",
    "spa",
    "beauty",
    "gym",
    "fitness",
    "shop",
    "store",
    "bakery",
    "dhaba",
    "bar",
    "boutique",
    "jeweller",
    "coaching",
    "academy",
}

# Tier constants
TIER_HOT = "HOT"
TIER_WARM = "WARM"
TIER_LOW = "LOW"


def evaluate_lead(lead: Lead) -> Tuple[int, str, List[str], str]:
    """Calculate lead score, tier, and qualification reason for a verified lead.

    Returns:
        (lead_score, lead_tier, breakdown_reasons, qualification_reason)
    """
    score = 0
    reasons: List[str] = []

    # 1. Website Signals
    site_status = lead.website_status or STATUS_UNKNOWN

    if site_status == STATUS_NO_WEBSITE:
        score += 40
        reasons.append("NO_WEBSITE (+40)")
    elif site_status == STATUS_BROKEN_WEBSITE:
        score += 35
        reasons.append("BROKEN_WEBSITE (+35)")
    elif site_status == STATUS_SOCIAL_ONLY:
        score += 30
        reasons.append("SOCIAL_ONLY (+30)")
    elif site_status == STATUS_DIRECTORY_ONLY:
        score += 28
        reasons.append("DIRECTORY_ONLY (+28)")
    elif site_status == STATUS_DOMAIN_ONLY:
        score += 20
        reasons.append("DOMAIN_ONLY (+20)")
    elif site_status == STATUS_VALID_WEBSITE:
        score += 0
        reasons.append("VALID_WEBSITE (+0, skip target)")
    else:
        score += 0
        reasons.append(f"{site_status} (+0)")

    # 2. Business Signals
    # Phone
    phone = lead.phone or lead.phone_normalized
    if phone and str(phone).strip():
        score += 15
        reasons.append(f"has_phone (+15): {phone}")

    # Email
    if lead.email and str(lead.email).strip():
        score += 10
        reasons.append(f"has_email (+10): {lead.email}")

    # Rating & Reviews
    rating = lead.rating
    reviews = lead.reviews_count or 0

    if rating is not None and rating >= 4.0 and reviews >= 20:
        score += 15
        reasons.append(f"high_reputation (+15): {rating}★ with {reviews} reviews")
    elif rating is not None and 3.0 <= rating < 4.0 and reviews > 0:
        score += 8
        reasons.append(f"moderate_reputation (+8): {rating}★ with {reviews} reviews")

    # Instagram
    has_instagram = False
    if lead.tags and isinstance(lead.tags, dict):
        if lead.tags.get("instagram") or "instagram.com" in str(lead.tags):
            has_instagram = True
    if lead.website and "instagram.com" in lead.website.lower():
        has_instagram = True

    if has_instagram:
        score += 5
        reasons.append("has_instagram (+5)")

    # Target Category Match
    cat_lower = (lead.category or "").lower()
    is_target_cat = any(t in cat_lower for t in TARGET_CATEGORIES)
    if is_target_cat:
        score += 10
        reasons.append(f"target_category (+10): {lead.category}")

    # 3. Determine Tier
    if score >= 70:
        tier = TIER_HOT
    elif score >= 45:
        tier = TIER_WARM
    else:
        tier = TIER_LOW

    # 4. Qualification summary reason
    if tier == TIER_HOT:
        qual_reason = f"HOT Lead ({score} pts): {site_status} with strong business profile"
    elif tier == TIER_WARM:
        qual_reason = f"WARM Lead ({score} pts): Qualified prospect ({site_status})"
    else:
        qual_reason = f"LOW Lead ({score} pts): Below qualification threshold ({site_status})"

    return score, tier, reasons, qual_reason


def score_and_qualify_leads(
    db: Optional[Database] = None,
    config: Optional[Config] = None,
    city: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Score all leads at status VERIFIED, assign tier, and qualify HOT/WARM leads."""
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

    query = "SELECT * FROM leads WHERE status = 'VERIFIED' ORDER BY id ASC LIMIT ?"
    if city:
        query = f"SELECT * FROM leads WHERE status = 'VERIFIED' AND city = '{city}' ORDER BY id ASC LIMIT ?"

    rows = db.conn.execute(query, (limit,)).fetchall()
    leads = [Lead.from_row(dict(r)) for r in rows]

    log.info("Starting scoring and qualification for %d verified leads...", len(leads))
    results: List[Dict[str, Any]] = []

    for lead in leads:
        score, tier, reasons, qual_reason = evaluate_lead(lead)
        is_qualified = tier in (TIER_HOT, TIER_WARM)

        update_fields: Dict[str, Any] = {
            "score": score,
            "score_reasons_json": json.dumps(reasons),
            "lead_tier": tier,
            "qualified": 1 if is_qualified else 0,
            "qualification_notes": qual_reason,
        }

        if is_qualified:
            # Transition to QUALIFIED
            db.update_lead(lead.id, update_fields)
            db.transition(
                lead_id=lead.id,
                to_status=LeadStatus.QUALIFIED.value,
                stage="lead_scorer",
                event=f"Qualified as {tier} lead (Score: {score}) — {qual_reason}",
                level="INFO",
                extra_fields=update_fields,
            )
            lead.status = LeadStatus.QUALIFIED
            log.info(
                "Lead [ID %d] '%s' -> %s (Score: %d) [QUALIFIED]",
                lead.id,
                lead.name,
                tier,
                score,
            )
        else:
            # LOW leads are saved with qualified=0 and not processed further
            db.update_lead(lead.id, update_fields)
            lead.score = score
            lead.lead_tier = tier
            lead.qualified = False
            lead.qualification_notes = qual_reason
            log.info(
                "Lead [ID %d] '%s' -> %s (Score: %d) [Unqualified / Skipped]",
                lead.id,
                lead.name,
                tier,
                score,
            )

        results.append({
            "id": lead.id,
            "name": lead.name,
            "category": lead.category,
            "city": lead.city,
            "website_status": lead.website_status,
            "lead_score": score,
            "lead_tier": tier,
            "qualified": is_qualified,
            "status": lead.status.value,
            "reasons": reasons,
            "qualification_reason": qual_reason,
        })

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI Scoring and Qualification")
    parser.add_argument("--city", default="Vadodara", help="City name filter")
    parser.add_argument("--limit", type=int, default=100, help="Max leads to score")
    args = parser.parse_args()

    print(f"\n=== Running Lead Scoring & Qualification (city='{args.city}', limit={args.limit}) ===")
    results = score_and_qualify_leads(city=args.city, limit=args.limit)

    print("\n==========================================================================================")
    print("                      LEADHUNTER AI — SCORING & QUALIFICATION RESULTS                     ")
    print("==========================================================================================")
    for r in results:
        tier_symbol = "🔥" if r["lead_tier"] == TIER_HOT else ("⚡" if r["lead_tier"] == TIER_WARM else "❄️")
        qual_tag = "[QUALIFIED]" if r["qualified"] else "[LOW / SKIPPED]"
        print(f"\nID {r['id']:2d} | {r['name']:<38} | Score: {r['lead_score']:2d}/100 | Tier: {tier_symbol} {r['lead_tier']:<4} {qual_tag}")
        print(f"      Website Status : {r['website_status']}")
        print(f"      Reason         : {r['qualification_reason']}")
        print(f"      Signal Details :")
        for sig in r["reasons"]:
            print(f"        + {sig}")


if __name__ == "__main__":
    main()
