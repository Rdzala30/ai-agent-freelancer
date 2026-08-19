"""AI Message Personalization module for LeadHunter AI.

Generates tailored cold email and WhatsApp outreach messages for QUALIFIED leads
using the Anthropic Python SDK (model claude-sonnet-4-6).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus

log = get_logger("personalizer")

SYSTEM_PROMPT = (
    "You are a professional web design consultant in India. Generate "
    "concise, natural outreach messages. Use only the provided business "
    "data. Never invent services, prices, awards, menu items, or facts "
    "not present in the input. Keep messages short and human."
)

MODEL_NAME = "claude-sonnet-4-6"


def get_anthropic_key(config: Optional[Config] = None) -> Optional[str]:
    """Retrieve ANTHROPIC_API_KEY from config or environment."""
    if config:
        key = config.get_secret("ANTHROPIC_API_KEY")
        if key:
            return key
    return os.environ.get("ANTHROPIC_API_KEY")


def build_user_prompt(lead: Lead) -> str:
    """Construct structured prompt with lead attributes for Claude."""
    tags = lead.tags or {}
    instagram = tags.get("instagram") or ("instagram.com" in (lead.website or "") and lead.website) or "None"
    facebook = tags.get("facebook") or ("facebook.com" in (lead.website or "") and lead.website) or "None"

    lead_data = {
        "business_name": lead.name,
        "city": lead.city,
        "category": lead.category,
        "phone": lead.phone or lead.phone_normalized or "None",
        "website_status": lead.website_status or "NO_WEBSITE",
        "rating": lead.rating if lead.rating is not None else "None",
        "review_count": lead.reviews_count if lead.reviews_count is not None else 0,
        "instagram": str(instagram),
        "facebook": str(facebook),
    }

    prompt = f"""Generate a personalized cold email and a WhatsApp message for this local business lead:

Lead Data:
{json.dumps(lead_data, indent=2)}

Guidelines:
1. Email requirements:
   - Subject line: Maximum 8 words.
   - Body: Maximum 120 words. Professional tone (natural English or subtle Hinglish touch is fine).
2. WhatsApp requirements:
   - Body: Maximum 80 words. Casual yet professional tone.
   - Must end with one clear, easy question.
3. Content Context:
   - If website_status is NO_WEBSITE: focus on opportunity and customer discovery, not failure.
   - If website_status is BROKEN_WEBSITE: mention "I noticed your site seems to be down".
   - If website_status is SOCIAL_ONLY: mention "I see you're active on Instagram — a website could help customers find you faster".
4. Include the placeholder {{{{DEMO_URL}}}} in both messages where the prospective demo site should be linked.
5. Strictly adhere to: never invent services, prices, menu items, or awards not in the lead data.

Output strictly in valid JSON format with keys "email_subject", "email_message", and "whatsapp_message":
{{
  "email_subject": "...",
  "email_message": "...",
  "whatsapp_message": "..."
}}"""
    return prompt


def generate_template_fallback(lead: Lead) -> Dict[str, str]:
    """High-quality deterministic fallback when ANTHROPIC_API_KEY is not configured."""
    name = lead.name
    city = lead.city
    category = lead.category or "business"
    rating = f"{lead.rating}★" if lead.rating else "top-rated"
    reviews = f"{lead.reviews_count} Google reviews" if lead.reviews_count else "great customer reviews"
    site_status = lead.website_status or "NO_WEBSITE"

    # Website status specific hooks
    if site_status == "BROKEN_WEBSITE":
        email_hook = f"I noticed your website seems to be down when searching for {name} in {city}."
        wa_hook = f"I noticed your site seems to be down while looking up {name}."
    elif site_status == "SOCIAL_ONLY":
        email_hook = f"I see you're active on social media — a dedicated website could help customers find and book with you faster."
        wa_hook = f"I see you're active on Instagram — a website could help customers find you faster."
    else:  # NO_WEBSITE or other
        email_hook = f"With {reviews} ({rating}), you have strong local reputation in {city}. Having a modern website would help direct customers find your menu and location directly."
        wa_hook = f"With {reviews} ({rating}), {name} has great local popularity in {city}."

    email_subject = f"Website concept for {name}, {city}"
    email_body = (
        f"Hi Team {name},\n\n"
        f"{email_hook}\n\n"
        f"I put together a clean, mobile-friendly landing page preview for {name} to show how your brand can look online: {{{{DEMO_URL}}}}\n\n"
        f"Would you be open to a quick 5-minute chat this week if you'd like to put this live?\n\n"
        f"Best regards,\nWeb Design Consultant"
    )

    wa_body = (
        f"Hi {name}! {wa_hook} I created a quick sample website preview for you: {{{{DEMO_URL}}}}\n\n"
        f"Would you like me to share a quick walkthrough on how to get this live?"
    )

    return {
        "email_subject": email_subject,
        "email_message": email_body,
        "whatsapp_message": wa_body,
    }


def generate_messages_for_lead(
    lead: Lead,
    api_key: Optional[str] = None,
) -> Dict[str, str]:
    """Generate cold email and WhatsApp message using Claude (claude-sonnet-4-6)."""
    if not api_key:
        api_key = get_anthropic_key()

    if not api_key:
        log.info("ANTHROPIC_API_KEY not set; utilizing deterministic template generation for Lead [ID %s]", lead.id)
        return generate_template_fallback(lead)

    client = anthropic.Anthropic(api_key=api_key)
    user_prompt = build_user_prompt(lead)

    from ..utils.error_handler import log_error, retry_with_backoff, StopPipelineException

    def _call_claude():
        return client.messages.create(
            model=MODEL_NAME,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

    try:
        response = retry_with_backoff(
            _call_claude,
            max_retries=2,
            base_delay=2.0,
            lead_id=lead.id,
            context=f"Claude Personalizer ({lead.name})",
        )

        content = response.content[0].text.strip()
        clean_content = content
        if "```json" in clean_content:
            clean_content = clean_content.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in clean_content:
            clean_content = clean_content.split("```", 1)[1].split("```", 1)[0]

        json_match = re.search(r"\{.*\}", clean_content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0), strict=False)
            except json.JSONDecodeError:
                sanitized = re.sub(r"[\r\n\t]", " ", json_match.group(0))
                parsed = json.loads(sanitized, strict=False)
            return {
                "email_subject": parsed.get("email_subject", f"Website for {lead.name}"),
                "email_message": parsed.get("email_message", ""),
                "whatsapp_message": parsed.get("whatsapp_message", ""),
            }
        else:
            log.warning("Could not parse JSON from Claude response, falling back to template")
            return generate_template_fallback(lead)

    except StopPipelineException:
        raise
    except Exception as exc:
        log_error(exc, lead_id=lead.id, context="Claude message generation")
        log.error("Anthropic API error for lead '%s': %s", lead.name, exc)
        return generate_template_fallback(lead)


def personalize_qualified_leads(
    db: Optional[Database] = None,
    config: Optional[Config] = None,
    city: Optional[str] = None,
    limit: int = 10,
    delay_s: float = 0.5,
) -> List[Dict[str, Any]]:
    """Process QUALIFIED leads sitting at HOT or WARM tier and generate outreach messages."""
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

    api_key = get_anthropic_key(config)

    # Query leads with status QUALIFIED and HOT or WARM tier
    query = (
        "SELECT * FROM leads WHERE status = 'QUALIFIED' "
        "AND (lead_tier = 'HOT' OR lead_tier = 'WARM') "
        "ORDER BY id ASC LIMIT ?"
    )
    if city:
        query = (
            f"SELECT * FROM leads WHERE status = 'QUALIFIED' "
            f"AND (lead_tier = 'HOT' OR lead_tier = 'WARM') "
            f"AND city = '{city}' ORDER BY id ASC LIMIT ?"
        )

    rows = db.conn.execute(query, (limit,)).fetchall()
    leads = [Lead.from_row(dict(r)) for r in rows]

    log.info("Starting AI personalization for %d QUALIFIED leads (limit=%d)...", len(leads), limit)
    results: List[Dict[str, Any]] = []

    for idx, lead in enumerate(leads):
        if idx > 0 and delay_s > 0:
            time.sleep(delay_s)

        log.info(
            "Generating personalized outreach for Lead [ID %d]: '%s' (%s, %s)...",
            lead.id,
            lead.name,
            lead.lead_tier,
            lead.website_status,
        )

        messages = generate_messages_for_lead(lead, api_key=api_key)

        update_fields: Dict[str, Any] = {
            "email_subject": messages["email_subject"],
            "email_message": messages["email_message"],
            "whatsapp_message": messages["whatsapp_message"],
            "personalized_message": messages["whatsapp_message"],
        }

        # Transition status to PERSONALIZED
        db.update_lead(lead.id, update_fields)
        db.transition(
            lead_id=lead.id,
            to_status=LeadStatus.PERSONALIZED.value,
            stage="personalizer",
            event=f"Generated cold email & WhatsApp messages via Claude ({MODEL_NAME})",
            level="INFO",
            extra_fields=update_fields,
        )

        lead.status = LeadStatus.PERSONALIZED
        lead.email_subject = messages["email_subject"]
        lead.email_message = messages["email_message"]
        lead.whatsapp_message = messages["whatsapp_message"]
        lead.personalized_message = messages["whatsapp_message"]

        log.info("Lead [ID %d] '%s' -> PERSONALIZED", lead.id, lead.name)

        results.append({
            "id": lead.id,
            "name": lead.name,
            "category": lead.category,
            "city": lead.city,
            "lead_tier": lead.lead_tier,
            "website_status": lead.website_status,
            "rating": lead.rating,
            "reviews_count": lead.reviews_count,
            "email_subject": messages["email_subject"],
            "email_message": messages["email_message"],
            "whatsapp_message": messages["whatsapp_message"],
            "status": lead.status.value,
        })

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI Personalization")
    parser.add_argument("--city", default="Vadodara", help="City name filter")
    parser.add_argument("--limit", type=int, default=10, help="Max leads to personalize")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between calls in seconds")
    args = parser.parse_args()

    print(f"\n=== Running AI Outreach Personalization (city='{args.city}', limit={args.limit}) ===")
    results = personalize_qualified_leads(city=args.city, limit=args.limit, delay_s=args.delay)

    print("\n==========================================================================================")
    print("                    LEADHUNTER AI — GENERATED OUTREACH MESSAGES                           ")
    print("==========================================================================================")
    for r in results:
        print(f"\n------------------------------------------------------------------------------------------")
        print(f"Lead ID {r['id']} | {r['name']} ({r['city']}) | Tier: {r['lead_tier']} | Status: {r['website_status']}")
        print(f"------------------------------------------------------------------------------------------")
        print(f"📧 COLD EMAIL:")
        print(f"Subject: {r['email_subject']}")
        print(f"\n{r['email_message']}")
        print(f"\n📱 WHATSAPP MESSAGE:")
        print(f"{r['whatsapp_message']}")


if __name__ == "__main__":
    main()
