"""LeadHunter AI — Main Pipeline CLI Entrypoint.

Coordinates pipeline stages:
- Discovery (SerpAPI / Google Maps)
- Processing (Normalization, Deduplication, Website Verification, Scoring)
- AI Personalization (Claude Sonnet outreach copywriting)
- Demo URL generation & landing page validation
- Human Approval Queue & Terminal Viewer
- Outbound Dispatch (Email & WhatsApp with safety rules)
- Google Sheets Sync
- Follow-up Sequence Engine (--followups)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from leadhunter.approval.approval_queue import process_approval_queue
from leadhunter.approval.approval_viewer import ApprovalViewer
from leadhunter.config import Config, load_env_file, DEFAULT_ENV_PATH
from leadhunter.db import Database
from leadhunter.demo.url_generator import process_and_generate_demo_urls
from leadhunter.discovery.serpapi_search import search_serpapi_google_maps
from leadhunter.followup.followup_engine import FollowupEngine
from leadhunter.outreach.email_sender import EmailSender, is_dry_run
from leadhunter.outreach.whatsapp_sender import WhatsAppSender
from leadhunter.processing.deduplicate import process_leads
from leadhunter.processing.lead_scorer import score_and_qualify_leads
from leadhunter.processing.website_checker import verify_leads_batch
from leadhunter.sheets_logger import sync_leads


def main():
    parser = argparse.ArgumentParser(description="LeadHunter AI Orchestrator")
    parser.add_argument("--city", default="Vadodara", help="Target city")
    parser.add_argument("--category", default="restaurants", help="Business category")
    parser.add_argument("--limit", type=int, default=10, help="Max leads to process")
    
    # Mode flags
    parser.add_argument("--web", "--dashboard", dest="web", action="store_true", help="Launch interactive Web Control Dashboard")
    parser.add_argument("--port", type=int, default=8000, help="Web dashboard server port (default 8000)")
    parser.add_argument("--followups", action="store_true", help="Run follow-up sequence engine")
    parser.add_argument("--discover", action="store_true", help="Run SerpAPI discovery")
    parser.add_argument("--dedup", action="store_true", help="Run normalization and deduplication")
    parser.add_argument("--verify", action="store_true", help="Run website verification")
    parser.add_argument("--score", action="store_true", help="Run lead scoring & qualification")
    parser.add_argument("--personalize", action="store_true", help="Run AI message personalization")
    parser.add_argument("--demos", action="store_true", help="Generate & verify demo URLs")
    parser.add_argument("--approve", action="store_true", help="Run interactive human approval viewer")
    parser.add_argument("--outreach", action="store_true", help="Dispatch email and WhatsApp outreach")
    parser.add_argument("--sync", action="store_true", help="Sync leads with Google Sheets & local CSV")
    parser.add_argument("--all", action="store_true", help="Run complete pipeline from discovery to outreach")

    args = parser.parse_args()
    load_env_file(DEFAULT_ENV_PATH)

    # 0. Web Dashboard mode
    if args.web:
        from leadhunter.web.app import run_server
        print(f"\n⚡ Launching LeadHunter AI Web Control Dashboard at http://localhost:{args.port} ...")
        run_server(port=args.port)
        return

    # 1. Follow-ups mode
    if args.followups:
        print(f"\n==========================================================================================")
        print(f"               LEADHUNTER AI — EXECUTING FOLLOW-UP SEQUENCE ENGINE                        ")
        print(f"==========================================================================================")
        engine = FollowupEngine()
        results = engine.check_and_stage_followups(city=args.city, limit=args.limit)

        print("\n==========================================================================================")
        print("                    LEADS DUE FOR FOLLOW-UP & STAGED MESSAGES                             ")
        print("==========================================================================================")
        if not results:
            print("No contacted leads currently due for follow-up.")
            return

        for r in results:
            print(f"\n------------------------------------------------------------------------------------------")
            print(f"Lead ID {r['lead_id']} | {r['name']} ({r['city']}) | Staged: Follow-up #{r['followup_number']}")
            print(f"Demo URL: {r['demo_url']}")
            print(f"Approval Queue Status: [{r['status']}]")
            print(f"------------------------------------------------------------------------------------------")
            print(f"📧 FOLLOW-UP EMAIL PREVIEW:")
            print(f"Subject: {r['email_subject']}")
            print(f"\n{r['email_message']}")
            print(f"\n📱 FOLLOW-UP WHATSAPP PREVIEW:")
            print(f"{r['whatsapp_message']}")
        return

    # 2. Stage-by-stage executions
    if args.discover or args.all:
        print(f"\n--- Stage 1: Discovery ({args.category} in {args.city}) ---")
        search_serpapi_google_maps(city=args.city, business_type=args.category, max_results=args.limit)

    if args.dedup or args.all:
        print(f"\n--- Stage 2: Normalization & Deduplication ---")
        process_leads(city=args.city)

    if args.verify or args.all:
        print(f"\n--- Stage 3: Website Verification ---")
        verify_leads_batch(city=args.city, limit=args.limit)

    if args.score or args.all:
        print(f"\n--- Stage 4: Scoring & Qualification ---")
        score_and_qualify_leads(city=args.city, limit=args.limit)

    if args.personalize or args.all:
        print(f"\n--- Stage 5: AI Personalization ---")
        from leadhunter.ai.personalizer import personalize_qualified_leads
        personalize_qualified_leads(city=args.city, limit=args.limit)

    if args.demos or args.all:
        print(f"\n--- Stage 6: Demo URL Generation & Verification ---")
        process_and_generate_demo_urls(city=args.city, limit=args.limit)

    if args.approve:
        print(f"\n--- Stage 7: Human Approval Queue ---")
        process_approval_queue(city=args.city, limit=args.limit)
        viewer = ApprovalViewer()
        viewer.review_interactive(city=args.city)

    if args.outreach or args.all:
        print(f"\n--- Stage 8: Outreach Dispatch (DRY_RUN={is_dry_run()}) ---")
        wa_sender = WhatsAppSender()
        wa_sender.process_approved_whatsapp(city=args.city, limit=args.limit)
        email_sender = EmailSender()
        email_sender.process_approved_emails(city=args.city, limit=args.limit)

    if args.sync or args.all:
        print(f"\n--- Stage 9: Google Sheets & Local Mirror Synchronization ---")
        sync_leads(city=args.city)


if __name__ == "__main__":
    main()
