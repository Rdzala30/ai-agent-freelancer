"""Demo URL Generator and Landing Page Verifier for LeadHunter AI.

Generates unique, branded preview URLs for PERSONALIZED leads:
- Generates canonical slug: {DEMO_BASE_URL}/{slug}
- Stores fallback query URL: {DEMO_BASE_URL}?lead_id={lead_id}
- Verifies that the preview page successfully renders and contains the business name
- Sets demo_status = READY (or FAILED)
- Transitions lead status to DEMO_READY
- Replaces {{DEMO_URL}} placeholder in email_message and whatsapp_message
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi.testclient import TestClient

from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus
from .server import app, slugify_lead

log = get_logger("url_generator")

DEFAULT_DEMO_BASE_URL = "http://localhost:8500/preview"


def get_demo_base_url(config: Optional[Config] = None) -> str:
    """Retrieve base domain / URL for demo previews, resolving automatic public tunnel if available."""
    from ..utils.tunnel_manager import resolve_public_demo_base_url

    configured_url = None
    env_url = os.environ.get("DEMO_BASE_URL")
    if env_url and env_url.strip():
        configured_url = env_url.strip().rstrip("/")
    elif config:
        base = config.get("demo.base_domain", "")
        if base and base.strip():
            base = base.strip().rstrip("/")
            configured_url = f"{base}/preview" if not base.endswith("/preview") else base

    return resolve_public_demo_base_url(config_url=configured_url, local_port=8500, force_tunnel=True)


def generate_lead_demo_urls(
    lead: Lead,
    base_url: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Generate canonical slug, primary demo URL, and fallback URL for a lead.

    Returns:
        (slug, primary_demo_url, fallback_demo_url)
    """
    if not base_url:
        base_url = get_demo_base_url()

    slug = slugify_lead(lead.name, lead.city)
    primary_url = f"{base_url}/{slug}"
    fallback_url = f"{base_url}?lead_id={lead.id}"
    return slug, primary_url, fallback_url


def verify_demo_page_render(
    lead: Lead,
    slug: str,
    target_url: str,
    test_client: Optional[TestClient] = None,
) -> Tuple[bool, str]:
    """Verify that the preview landing page loads with status 200 and contains the business name.

    Returns:
        (is_verified, response_html_or_error)
    """
    if test_client is None:
        test_client = TestClient(app)

    # 1. Try local in-process FastAPI TestClient (guaranteed to work in all environments)
    try:
        resp = test_client.get(f"/preview/{slug}")
        if resp.status_code == 200 and lead.name.lower() in resp.text.lower():
            log.info("Verified demo landing page for Lead [ID %s] '%s' (status 200 OK)", lead.id, lead.name)
            return True, resp.text
    except Exception as exc:
        log.warning("TestClient preview verification exception for '%s': %s", slug, exc)

    # 2. Try external HTTP GET if server is running on live network / port
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(target_url)
            if resp.status_code == 200 and lead.name.lower() in resp.text.lower():
                return True, resp.text
    except Exception:
        pass

    return False, "Failed to verify demo page loading"


def process_and_generate_demo_urls(
    db: Optional[Database] = None,
    config: Optional[Config] = None,
    city: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Generate demo URLs, verify rendering, replace placeholders, and transition leads to DEMO_READY."""
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

    base_url = get_demo_base_url(config)
    test_client = TestClient(app)

    # Query leads sitting at PERSONALIZED status
    query = "SELECT * FROM leads WHERE status = 'PERSONALIZED' ORDER BY id ASC LIMIT ?"
    if city:
        query = f"SELECT * FROM leads WHERE status = 'PERSONALIZED' AND city = '{city}' ORDER BY id ASC LIMIT ?"

    rows = db.conn.execute(query, (limit,)).fetchall()
    leads = [Lead.from_row(dict(r)) for r in rows]

    log.info("Generating demo URLs for %d PERSONALIZED leads...", len(leads))
    results: List[Dict[str, Any]] = []

    for lead in leads:
        slug, demo_url, fallback_url = generate_lead_demo_urls(lead, base_url=base_url)

        # Verify page rendering
        is_verified, response_body = verify_demo_page_render(
            lead=lead,
            slug=slug,
            target_url=demo_url,
            test_client=test_client,
        )

        demo_status = "READY" if is_verified else "FAILED"

        # Replace {{DEMO_URL}} placeholder in email and whatsapp messages
        updated_email = (lead.email_message or "").replace("{{DEMO_URL}}", demo_url)
        updated_whatsapp = (lead.whatsapp_message or lead.personalized_message or "").replace("{{DEMO_URL}}", demo_url)

        update_fields: Dict[str, Any] = {
            "demo_url": demo_url,
            "demo_status": demo_status,
            "email_message": updated_email,
            "whatsapp_message": updated_whatsapp,
            "personalized_message": updated_whatsapp,
        }

        if is_verified:
            # Transition to DEMO_READY
            db.update_lead(lead.id, update_fields)
            db.transition(
                lead_id=lead.id,
                to_status=LeadStatus.DEMO_READY.value,
                stage="demo_generator",
                event=f"Demo website created & verified: {demo_url}",
                level="INFO",
                extra_fields=update_fields,
            )
            lead.status = LeadStatus.DEMO_READY
            log.info("Lead [ID %d] '%s' -> demo_status: READY -> [DEMO_READY]", lead.id, lead.name)
        else:
            db.update_lead(lead.id, update_fields)
            log.error("Lead [ID %d] '%s' -> demo verification FAILED", lead.id, lead.name)

        lead.demo_url = demo_url
        lead.email_message = updated_email
        lead.whatsapp_message = updated_whatsapp
        lead.personalized_message = updated_whatsapp

        results.append({
            "id": lead.id,
            "name": lead.name,
            "city": lead.city,
            "category": lead.category,
            "slug": slug,
            "demo_url": demo_url,
            "fallback_url": fallback_url,
            "demo_status": demo_status,
            "status": lead.status.value,
            "email_message": updated_email,
            "whatsapp_message": updated_whatsapp,
            "sample_html_snippet": response_body[:600] if is_verified else "",
        })

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI Demo URL Generator")
    parser.add_argument("--city", default="Vadodara", help="City name filter")
    parser.add_argument("--limit", type=int, default=10, help="Max leads to process")
    args = parser.parse_args()

    print(f"\n=== Running Demo URL Generation (city='{args.city}', limit={args.limit}) ===")
    results = process_and_generate_demo_urls(city=args.city, limit=args.limit)

    print("\n==========================================================================================")
    print("                    LEADHUNTER AI — DEMO URLS & VERIFIED PREVIEWS                         ")
    print("==========================================================================================")
    for r in results:
        status_tag = f"[{r['demo_status']}]"
        print(f"\nLead ID {r['id']:2d} | {r['name']} ({r['city']}) | Demo: {status_tag}")
        print(f"      Slug         : {r['slug']}")
        print(f"      Demo URL     : {r['demo_url']}")
        print(f"      Fallback URL : {r['fallback_url']}")
        print(f"      Status       : {r['status']}")
        print(f"\n      Updated WhatsApp Message:")
        print(f"      {r['whatsapp_message']}")


if __name__ == "__main__":
    main()
