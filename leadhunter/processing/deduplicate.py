"""Deduplication and quality scoring engine for LeadHunter AI.

Compares newly discovered leads against existing database records to detect
and flag duplicates using:
- Phone number matching (exact normalized 10 digits)
- Normalized name similarity (SequenceMatcher ratio & token overlap)
- Website domain matching (excluding generic portals)
- Branch awareness (same brand with different address/locality = kept as distinct branch)

Marks confirmed duplicate leads with status 'DUPLICATE' in SQLite and logs
the rationale. Computes quality scores (0–100).
"""

from __future__ import annotations

import difflib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus
from .normalize import (
    compute_quality_score,
    extract_domain,
    normalize_address,
    normalize_name,
    normalize_phone,
    normalize_website,
)

log = get_logger("deduplicate")

GENERIC_DOMAINS: Set[str] = {
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "google.com",
    "maps.google.com",
    "goo.gl",
    "linktr.ee",
    "zomato.com",
    "swiggy.com",
    "justdial.com",
    "magicpin.in",
    "tripadvisor.com",
    "tripadvisor.in",
}


def are_addresses_different_branches(addr1: Optional[str], addr2: Optional[str]) -> bool:
    """Check if two addresses represent distinctly different branch locations.

    Returns True if both addresses are present and have distinct non-overlapping
    locality/street identifiers, indicating different branches.
    """
    if not addr1 or not addr2:
        return False

    n1 = normalize_address(addr1)
    n2 = normalize_address(addr2)
    if not n1 or not n2:
        return False

    if n1 == n2:
        return False

    # Extract words/tokens
    words1 = {w for w in n1.split() if len(w) > 3}
    words2 = {w for w in n2.split() if len(w) > 3}

    # Filter out common city/state tokens
    generic_geo = {"vadodara", "baroda", "pune", "mumbai", "gujarat", "maharashtra", "india", "road", "near", "opposite", "behind", "floor"}
    spec1 = words1 - generic_geo
    spec2 = words2 - generic_geo

    if not spec1 or not spec2:
        return False

    overlap = spec1 & spec2
    overlap_ratio = len(overlap) / min(len(spec1), len(spec2))
    # If overlap of specific location keywords is low (< 0.4), they are distinct branches
    return overlap_ratio < 0.4


def check_duplicate(
    lead1: Lead,
    lead2: Lead,
    name_similarity_threshold: float = 0.85,
) -> Tuple[bool, str]:
    """Compare two leads and determine if lead2 is a duplicate of lead1.

    Returns:
        (is_duplicate, reason_string)
    """
    # 1. Exact phone match (strongest signal)
    p1 = normalize_phone(lead1.phone or lead1.phone_normalized)
    p2 = normalize_phone(lead2.phone or lead2.phone_normalized)
    if p1 and p2 and p1 == p2:
        return True, f"phone match ({p1})"

    # 2. Normalized name similarity
    n1 = normalize_name(lead1.name)
    n2 = normalize_name(lead2.name)

    name_matched = False
    similarity = 0.0
    if n1 and n2:
        if n1 == n2:
            name_matched = True
            similarity = 1.0
        else:
            similarity = difflib.SequenceMatcher(None, n1, n2).ratio()
            if similarity >= name_similarity_threshold:
                name_matched = True

    # 3. Website domain match
    d1 = extract_domain(lead1.website)
    d2 = extract_domain(lead2.website)
    domain_matched = False
    if d1 and d2 and d1 not in GENERIC_DOMAINS and d2 not in GENERIC_DOMAINS:
        if d1 == d2:
            domain_matched = True

    # Check for branch distinction:
    # If name or domain matched, but addresses clearly represent different branches, KEEP both!
    if (name_matched or domain_matched) and are_addresses_different_branches(lead1.address, lead2.address):
        log.info(
            "Distinct branches detected for '%s' vs '%s' (addr: '%s' vs '%s') -> KEEPING BOTH",
            lead1.name,
            lead2.name,
            lead1.address,
            lead2.address,
        )
        return False, "distinct branch (different address)"

    # If name matched and not different branch
    if name_matched:
        return True, f"name similarity ({similarity:.2f}) between '{lead1.name}' and '{lead2.name}'"

    # If website domain matched (and not a different branch)
    if domain_matched:
        return True, f"website domain match ({d1})"

    return False, ""


def process_leads(
    db: Optional[Database] = None,
    config: Optional[Config] = None,
    city: Optional[str] = None,
) -> Dict[str, Any]:
    """Run normalization, quality scoring, and deduplication across leads in SQLite.

    Returns:
        Summary dict of processed leads, scores, and detected duplicates.
    """
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

    # Fetch leads
    query = "SELECT * FROM leads WHERE status != 'DUPLICATE' ORDER BY id ASC"
    if city:
        query = f"SELECT * FROM leads WHERE city = '{city}' AND status != 'DUPLICATE' ORDER BY id ASC"

    rows = db.conn.execute(query).fetchall()
    all_leads = [Lead.from_row(dict(r)) for r in rows]

    log.info("Processing %d leads for normalization and quality scoring...", len(all_leads))

    # Step 1: Normalize fields and calculate quality scores
    scored_leads = []
    for lead in all_leads:
        # Normalize fields
        norm_phone = normalize_phone(lead.phone)
        norm_site = normalize_website(lead.website)
        norm_addr = normalize_address(lead.address)

        # Compute Quality Score (0-100)
        q_score, reasons = compute_quality_score(lead)

        update_fields: Dict[str, Any] = {
            "phone_normalized": norm_phone,
            "score": q_score,
            "score_reasons_json": json.dumps(reasons),
        }
        db.update_lead(lead.id, update_fields)
        lead.phone_normalized = norm_phone
        lead.score = q_score
        lead.score_reasons = reasons
        scored_leads.append(lead)

        log.info(
            "Lead [ID %d] '%s': Quality Score = %d/100 (%s)",
            lead.id,
            lead.name,
            q_score,
            ", ".join(reasons),
        )

    # Step 2: Deduplication against existing records
    duplicates: List[Dict[str, Any]] = []
    kept_leads: List[Lead] = []

    for lead in scored_leads:
        is_dup = False
        dup_reason = ""
        matched_lead = None

        for existing in kept_leads:
            is_dup, dup_reason = check_duplicate(existing, lead)
            if is_dup:
                matched_lead = existing
                break

        if is_dup and matched_lead is not None:
            # Mark lead as DUPLICATE in SQLite
            db.update_lead(lead.id, {"status": LeadStatus.DUPLICATE.value})
            db.record_event(
                lead_id=lead.id,
                from_status=lead.status.value,
                to_status=LeadStatus.DUPLICATE.value,
                stage="deduplication",
                event=f"Marked as DUPLICATE of Lead ID {matched_lead.id} ({dup_reason})",
                level="WARN",
            )
            lead.status = LeadStatus.DUPLICATE
            log.warning(
                "DUPLICATE DETECTED: Lead [ID %d] '%s' is a duplicate of Lead [ID %d] '%s' (Reason: %s)",
                lead.id,
                lead.name,
                matched_lead.id,
                matched_lead.name,
                dup_reason,
            )
            duplicates.append({
                "lead_id": lead.id,
                "lead_name": lead.name,
                "duplicate_of_id": matched_lead.id,
                "duplicate_of_name": matched_lead.name,
                "reason": dup_reason,
            })
        else:
            kept_leads.append(lead)

    db.conn.commit()

    return {
        "total_processed": len(all_leads),
        "kept_count": len(kept_leads),
        "duplicate_count": len(duplicates),
        "duplicates": duplicates,
        "leads": scored_leads,
    }


def main():
    results = process_leads(city="Vadodara")
    print("\n============================================================")
    print("      LEADHUNTER AI — NORMALIZATION & DEDUPLICATION         ")
    print("============================================================")
    print(f"Total Leads Processed : {results['total_processed']}")
    print(f"Unique Leads Kept     : {results['kept_count']}")
    print(f"Duplicates Flagged    : {results['duplicate_count']}")

    print("\n--- Lead Quality Scores (0–100) ---")
    for lead in results["leads"]:
        status_tag = f"[{lead.status.value}]"
        print(f"ID {lead.id:2d} | {lead.name:<38} | Score: {lead.score:3.0f}/100 {status_tag}")
        for r in lead.score_reasons:
            print(f"       + {r}")

    if results["duplicates"]:
        print("\n--- Flagged Duplicates ---")
        for d in results["duplicates"]:
            print(f"Lead ID {d['lead_id']} ('{d['lead_name']}') -> DUPLICATE of ID {d['duplicate_of_id']} ('{d['duplicate_of_name']}'): {d['reason']}")
    else:
        print("\n--- Flagged Duplicates ---")
        print("No duplicate leads detected among the current set.")


if __name__ == "__main__":
    main()
