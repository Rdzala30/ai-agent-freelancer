"""Website verification module for LeadHunter AI.

Inspects business websites for leads with status DISCOVERED or ENRICHED:
- Performs HTTP GET requests via httpx with 10s timeout, following redirects
- Classifies into: VALID_WEBSITE, BROKEN_WEBSITE, NO_WEBSITE, SOCIAL_ONLY,
  DIRECTORY_ONLY, DOMAIN_ONLY, UNKNOWN
- Performs secondary SerpAPI search for leads without a claimed website
- Checks page title and content to verify business match
- Never treats social or directory profiles as a website
- Updates lead records with website_status and transitions to VERIFIED
- Applies a polite delay between checks
"""

from __future__ import annotations

import difflib
import json
import os
import re
import ssl
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx
import serpapi

from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..discovery.serpapi_search import get_serpapi_key
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus
from .normalize import extract_domain, normalize_name, normalize_website

log = get_logger("website_checker")

# Website Status Classifications
STATUS_VALID_WEBSITE = "VALID_WEBSITE"
STATUS_BROKEN_WEBSITE = "BROKEN_WEBSITE"
STATUS_NO_WEBSITE = "NO_WEBSITE"
STATUS_SOCIAL_ONLY = "SOCIAL_ONLY"
STATUS_DIRECTORY_ONLY = "DIRECTORY_ONLY"
STATUS_DOMAIN_ONLY = "DOMAIN_ONLY"
STATUS_UNKNOWN = "UNKNOWN"

ALL_WEBSITE_STATUSES = {
    STATUS_VALID_WEBSITE,
    STATUS_BROKEN_WEBSITE,
    STATUS_NO_WEBSITE,
    STATUS_SOCIAL_ONLY,
    STATUS_DIRECTORY_ONLY,
    STATUS_DOMAIN_ONLY,
    STATUS_UNKNOWN,
}

SOCIAL_DOMAINS: Set[str] = {
    "facebook.com",
    "instagram.com",
    "fb.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "threads.net",
    "pinterest.com",
    "tiktok.com",
}

DIRECTORY_DOMAINS: Set[str] = {
    "justdial.com",
    "sulekha.com",
    "indiamart.com",
    "tradeindia.com",
    "zomato.com",
    "swiggy.com",
    "magicpin.in",
    "dineout.co.in",
    "tripadvisor.com",
    "tripadvisor.in",
    "eattreat.in",
    "yellowpages.com",
    "nearbuy.com",
    "eatsure.com",
    "google.com",
    "maps.google.com",
    "goo.gl",
    "linktr.ee",
}

PARKED_INDICATORS: List[str] = [
    "domain parked",
    "domain is for sale",
    "buy this domain",
    "under construction",
    "coming soon",
    "godaddy",
    "namecheap",
    "dan.com",
    "sedoparking",
    "hugedomains",
    "apache2 debian default page",
    "default web site page",
    "welcome to nginx",
    "this domain may be for sale",
]

_TITLE_TAG = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HTML_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def classify_url_domain(url: Optional[str]) -> Optional[str]:
    """Check if URL belongs to a known social platform or directory."""
    if not url:
        return None
    domain = extract_domain(url)
    if not domain:
        return None

    # Check root and subdomains against social domains
    for s_dom in SOCIAL_DOMAINS:
        if domain == s_dom or domain.endswith("." + s_dom):
            return STATUS_SOCIAL_ONLY

    # Check root and subdomains against directory domains
    for d_dom in DIRECTORY_DOMAINS:
        if domain == d_dom or domain.endswith("." + d_dom):
            return STATUS_DIRECTORY_ONLY

    return None


def extract_page_title(html: str) -> str:
    """Extract and clean <title> text from HTML."""
    match = _TITLE_TAG.search(html)
    if match:
        raw_title = _HTML_TAGS.sub("", match.group(1))
        return _WS.sub(" ", raw_title).strip()
    return ""


def is_parked_domain(html: str, title: str) -> bool:
    """Detect if page is a domain parking / for-sale placeholder."""
    lowered_title = title.lower()
    lowered_html = html[:4000].lower()
    for ind in PARKED_INDICATORS:
        if ind in lowered_title or ind in lowered_html:
            return True
    return False


def page_matches_business_name(business_name: str, title: str, html: str) -> bool:
    """Verify if HTML title or content matches business name tokens."""
    norm_biz = normalize_name(business_name)
    biz_tokens = {t for t in norm_biz.split() if len(t) > 2}
    if not biz_tokens:
        return True

    norm_title = normalize_name(title)
    title_tokens = set(norm_title.split())

    # If title has significant token overlap with business name
    if biz_tokens & title_tokens:
        return True

    # Check title similarity
    if norm_biz and norm_title:
        similarity = difflib.SequenceMatcher(None, norm_biz, norm_title).ratio()
        if similarity >= 0.4:
            return True

    # Check body text (first 3000 chars)
    body_snippet = _HTML_TAGS.sub(" ", html[:3000]).lower()
    body_snippet_norm = normalize_name(body_snippet)
    matched_count = sum(1 for token in biz_tokens if token in body_snippet_norm)
    return matched_count >= max(1, len(biz_tokens) // 2)


def check_url_with_httpx(url: str, business_name: str) -> Tuple[str, Dict[str, Any]]:
    """Perform HTTP GET request and inspect site response.

    Returns:
        (website_status, site_profile_dict)
    """
    profile: Dict[str, Any] = {
        "url": url,
        "final_url": url,
        "status_code": None,
        "title": "",
        "error": None,
        "is_matching": False,
    }

    # First check if domain is social or directory
    domain_type = classify_url_domain(url)
    if domain_type == STATUS_SOCIAL_ONLY:
        profile["classification"] = STATUS_SOCIAL_ONLY
        return STATUS_SOCIAL_ONLY, profile
    elif domain_type == STATUS_DIRECTORY_ONLY:
        profile["classification"] = STATUS_DIRECTORY_ONLY
        return STATUS_DIRECTORY_ONLY, profile

    # Ensure valid scheme
    target_url = url
    if not target_url.startswith(("http://", "https://")):
        target_url = "https://" + target_url

    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            headers=HTTP_HEADERS,
            verify=False,  # Still check site even with self-signed SSL
        ) as client:
            resp = client.get(target_url)
            profile["status_code"] = resp.status_code
            profile["final_url"] = str(resp.url)

            # Check final redirected URL domain as well
            redir_type = classify_url_domain(str(resp.url))
            if redir_type in (STATUS_SOCIAL_ONLY, STATUS_DIRECTORY_ONLY):
                profile["classification"] = redir_type
                return redir_type, profile

            if resp.status_code == 200:
                html = resp.text
                title = extract_page_title(html)
                profile["title"] = title

                # Check for parked domain
                if is_parked_domain(html, title):
                    profile["classification"] = STATUS_DOMAIN_ONLY
                    return STATUS_DOMAIN_ONLY, profile

                # Check if page matches business name
                matches = page_matches_business_name(business_name, title, html)
                profile["is_matching"] = matches
                if matches:
                    profile["classification"] = STATUS_VALID_WEBSITE
                    return STATUS_VALID_WEBSITE, profile
                else:
                    # Site exists and loaded, but weak or mismatched title
                    profile["classification"] = STATUS_VALID_WEBSITE
                    return STATUS_VALID_WEBSITE, profile

            elif resp.status_code in (403, 401):
                # Often Cloudflare / Bot protection blocking scraper
                profile["error"] = f"HTTP {resp.status_code} Access Denied / Protected"
                # If domain contains key name tokens, treat as VALID_WEBSITE or UNKNOWN
                domain = extract_domain(url) or ""
                if normalize_name(business_name).replace(" ", "") in domain.replace("-", "").replace(".", ""):
                    profile["classification"] = STATUS_VALID_WEBSITE
                    return STATUS_VALID_WEBSITE, profile
                profile["classification"] = STATUS_UNKNOWN
                return STATUS_UNKNOWN, profile

            else:
                profile["error"] = f"HTTP {resp.status_code}"
                profile["classification"] = STATUS_BROKEN_WEBSITE
                return STATUS_BROKEN_WEBSITE, profile

    except Exception as exc:
        from ..utils.error_handler import log_error
        log_error(exc, context=f"Website Checker '{url}'")
        profile["error"] = f"HTTP request error: {exc}"
        profile["classification"] = STATUS_BROKEN_WEBSITE
        return STATUS_BROKEN_WEBSITE, profile


def search_official_website_via_serpapi(
    business_name: str,
    city: str,
    api_key: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Secondary search for businesses without a website URL.

    Queries SerpAPI Google Search: "{business_name} {city} official website".
    Returns:
        (found_url, classification_if_social_or_directory)
    """
    if not api_key:
        api_key = get_serpapi_key()
    if not api_key:
        return None, None

    query = f"{business_name} {city} official website"
    log.info("Secondary SerpAPI search for missing website: '%s'", query)

    try:
        client = serpapi.Client(api_key=api_key)
        results = client.search(
            engine="google",
            q=query,
            num=5,
            hl="en",
            gl="in",
        )
    except Exception as exc:
        log.warning("Secondary SerpAPI search failed: %s", exc)
        return None, None

    organic_results = results.get("organic_results", []) if isinstance(results, dict) else []
    found_social = False
    found_directory = False

    for res in organic_results:
        link = res.get("link")
        if not link:
            continue
        domain_type = classify_url_domain(link)
        if domain_type == STATUS_SOCIAL_ONLY:
            found_social = True
            continue
        elif domain_type == STATUS_DIRECTORY_ONLY:
            found_directory = True
            continue
        else:
            # Candidate real website
            return link, None

    if found_social:
        return None, STATUS_SOCIAL_ONLY
    if found_directory:
        return None, STATUS_DIRECTORY_ONLY

    return None, STATUS_NO_WEBSITE


def verify_lead_website(
    lead: Lead,
    api_key: Optional[str] = None,
) -> Tuple[str, Optional[str], Dict[str, Any]]:
    """Verify website for a single lead.

    Returns:
        (website_status, verified_url, site_profile)
    """
    url = lead.website

    # If lead already has a claimed website URL
    if url and str(url).strip():
        status, profile = check_url_with_httpx(url, lead.name)
        verified_url = profile.get("final_url") if status == STATUS_VALID_WEBSITE else None
        return status, verified_url, profile

    # If lead does NOT have a website, perform secondary search
    found_url, category_type = search_official_website_via_serpapi(
        business_name=lead.name,
        city=lead.city,
        api_key=api_key,
    )

    if found_url:
        status, profile = check_url_with_httpx(found_url, lead.name)
        verified_url = profile.get("final_url") if status == STATUS_VALID_WEBSITE else None
        return status, verified_url, profile
    elif category_type:
        return category_type, None, {"note": f"Secondary search classified as {category_type}"}
    else:
        return STATUS_NO_WEBSITE, None, {"note": "No website found in discovery or secondary search"}


def verify_leads_batch(
    limit: int = 5,
    db: Optional[Database] = None,
    config: Optional[Config] = None,
    city: Optional[str] = None,
    delay_s: float = 1.0,
) -> List[Dict[str, Any]]:
    """Verify up to `limit` leads sitting at DISCOVERED or ENRICHED status.

    Updates database record with website_status, site_profile_json, and
    transitions lead status to VERIFIED.
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

    api_key = get_serpapi_key(config)

    # Fetch eligible leads (DISCOVERED or ENRICHED)
    query = (
        "SELECT * FROM leads WHERE status IN ('DISCOVERED', 'ENRICHED') "
        "ORDER BY id ASC LIMIT ?"
    )
    if city:
        query = (
            f"SELECT * FROM leads WHERE status IN ('DISCOVERED', 'ENRICHED') "
            f"AND city = '{city}' ORDER BY id ASC LIMIT ?"
        )

    rows = db.conn.execute(query, (limit,)).fetchall()
    leads = [Lead.from_row(dict(r)) for r in rows]

    log.info("Starting website verification for %d leads (batch limit: %d)...", len(leads), limit)
    results: List[Dict[str, Any]] = []

    for idx, lead in enumerate(leads):
        if idx > 0 and delay_s > 0:
            time.sleep(delay_s)

        log.info(
            "Verifying website for Lead [ID %d]: '%s' | URL: %s",
            lead.id,
            lead.name,
            lead.website or "None",
        )

        site_status, verified_url, profile = verify_lead_website(lead, api_key=api_key)

        # Update Lead record in DB
        update_fields: Dict[str, Any] = {
            "website_verified": verified_url or lead.website_verified,
            "website_status": site_status,
            "site_profile_json": json.dumps(profile, default=str),
        }

        # Transition status to VERIFIED
        from_status = lead.status.value
        db.update_lead(lead.id, update_fields)
        db.transition(
            lead_id=lead.id,
            to_status=LeadStatus.VERIFIED.value,
            stage="website_checker",
            event=f"Website verified as {site_status} (url: {verified_url or lead.website or 'None'})",
            level="INFO",
            extra_fields=update_fields,
        )

        lead.website_status = site_status
        lead.website_verified = verified_url
        lead.site_profile = profile
        lead.status = LeadStatus.VERIFIED

        log.info(
            "Lead [ID %d] '%s' -> website_status: %s [VERIFIED]",
            lead.id,
            lead.name,
            site_status,
        )

        results.append({
            "id": lead.id,
            "name": lead.name,
            "category": lead.category,
            "city": lead.city,
            "original_website": lead.website,
            "verified_website": verified_url,
            "website_status": site_status,
            "status": lead.status.value,
            "profile": profile,
        })

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI Website Verification")
    parser.add_argument("--city", default="Vadodara", help="City name filter")
    parser.add_argument("--limit", type=int, default=5, help="Number of leads to process")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay in seconds between checks")
    args = parser.parse_args()

    print(f"\n=== Running Website Verification (city='{args.city}', limit={args.limit}, delay={args.delay}s) ===")
    results = verify_leads_batch(limit=args.limit, city=args.city, delay_s=args.delay)

    print("\n============================================================")
    print("         WEBSITE VERIFICATION RESULTS                       ")
    print("============================================================")
    for r in results:
        print(f"ID {r['id']:2d} | {r['name']:<38} | Status: {r['website_status']:<16} | [{r['status']}]")
        print(f"      URL: {r['original_website'] or 'None'}")
        if r['verified_website']:
            print(f"      Verified: {r['verified_website']}")
        if r['profile'].get('title'):
            print(f"      Title: {r['profile']['title']}")
        if r['profile'].get('error'):
            print(f"      Error/Note: {r['profile']['error']}")


if __name__ == "__main__":
    main()
