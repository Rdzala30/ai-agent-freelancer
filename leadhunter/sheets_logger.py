"""Google Sheets synchronization module for LeadHunter AI.

Synchronizes lead records and pipeline runs with Google Sheets using a service account:
- Target sheet tabs: 'Leads' and 'Runs'
- Row-level update based on Lead ID (Column A) or append if new
- Audit columns matching full lifecycle (verification, scoring, AI outreach, demo URL)
- Local CSV mirroring fallback (data/export/leads_sync.csv) when offline / API unavailable
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials

from .config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from .db import Database
from .log import get_logger, setup_logging
from .models import Lead, LeadStatus

log = get_logger("sheets_logger")

LEADS_COLUMNS = [
    "Lead ID",
    "Business Name",
    "Category",
    "City",
    "Phone",
    "Email",
    "Address",
    "Website",
    "Website Status",
    "Lead Score",
    "Lead Tier",
    "Qualification Reason",
    "Demo URL",
    "Demo Status",
    "Email Message",
    "WhatsApp Message",
    "Approval Status",
    "Email Status",
    "WhatsApp Status",
    "First Contacted At",
    "Last Contacted At",
    "Status",
    "Source",
    "Created At",
    "Updated At",
    "Error",
]

RUNS_COLUMNS = [
    "Run Date",
    "City",
    "Business Type",
    "Discovered",
    "Qualified",
    "Hot",
    "Warm",
    "Demo Ready",
    "Errors",
]

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheets_config(config: Optional[Config] = None) -> Tuple[Optional[str], Optional[str]]:
    """Retrieve Google Sheets credentials path and sheet ID."""
    creds_path = None
    sheet_id = None

    if config:
        creds_path = (
            config.get_secret("GOOGLE_CREDS_PATH")
            or config.get_secret("GOOGLE_SHEETS_CREDS_FILE")
        )
        sheet_id = (
            config.get_secret("GOOGLE_SHEET_ID")
            or config.get_secret("GOOGLE_SHEETS_SPREADSHEET_ID")
        )

    if not creds_path:
        creds_path = os.environ.get("GOOGLE_CREDS_PATH") or os.environ.get("GOOGLE_SHEETS_CREDS_FILE")
    if not sheet_id:
        sheet_id = os.environ.get("GOOGLE_SHEET_ID") or os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID")

    return creds_path, sheet_id


def lead_to_sheet_row(lead: Lead) -> List[Any]:
    """Format a Lead instance into the exact column order expected by Google Sheets."""
    tags = lead.tags or {}
    approval_status = tags.get("approval_status", "PENDING" if lead.status == LeadStatus.PENDING_APPROVAL else "N/A")
    email_status = tags.get("email_status", "SENT" if lead.status == LeadStatus.SENT else "NOT_SENT")
    whatsapp_status = tags.get("whatsapp_status", "SENT" if lead.status == LeadStatus.SENT else "NOT_SENT")
    first_contacted_at = tags.get("first_contacted_at", "")
    last_contacted_at = tags.get("last_contacted_at", "")

    return [
        lead.id,
        lead.name,
        lead.category or "",
        lead.city or "",
        lead.phone or lead.phone_normalized or "",
        lead.email or "",
        lead.address or "",
        lead.website or lead.website_verified or "",
        lead.website_status or "",
        lead.score if lead.score is not None else "",
        lead.lead_tier or "",
        lead.qualification_notes or "",
        lead.demo_url or "",
        tags.get("demo_status", "READY" if lead.status == LeadStatus.DEMO_READY else (lead.status.value if "DEMO" in lead.status.value else "")),
        lead.email_message or "",
        lead.whatsapp_message or lead.personalized_message or "",
        approval_status,
        email_status,
        whatsapp_status,
        first_contacted_at,
        last_contacted_at,
        lead.status.value,
        lead.source or "",
        lead.created_at or "",
        lead.updated_at or "",
        lead.last_error or "",
    ]


class SheetsLogger:
    """Manages synchronization of Leads and Run summaries with Google Sheets and local CSV fallback."""

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

        self.export_dir = (config.data_dir / "export") if config else Path("./data/export")
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.local_csv_path = self.export_dir / "leads_sync.csv"
        self.runs_csv_path = self.export_dir / "runs_sync.csv"

        self.creds_path, self.sheet_id = get_sheets_config(self.config)
        self.client: Optional[gspread.Client] = None
        self.spreadsheet: Optional[gspread.Spreadsheet] = None
        self.leads_sheet: Optional[gspread.Worksheet] = None
        self.runs_sheet: Optional[gspread.Worksheet] = None
        self._connected = False

    def connect(self) -> bool:
        """Establish connection with Google Sheets API using service account credentials."""
        if not self.creds_path or not self.sheet_id:
            log.info("Google Sheets credentials or Sheet ID not configured; operating in local mirror mode.")
            return False

        if not Path(self.creds_path).exists():
            log.warning("Google Sheets creds file not found at '%s'. Using local mirror.", self.creds_path)
            return False

        try:
            creds = Credentials.from_service_account_file(self.creds_path, scopes=SHEETS_SCOPES)
            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open_by_key(self.sheet_id)
            self._ensure_worksheets()
            self._connected = True
            log.info("Successfully connected to Google Sheet: '%s'", self.spreadsheet.title)
            return True
        except Exception as exc:
            from .utils.error_handler import log_error
            log_error(exc, context="Google Sheets API Connection")
            log.error("Failed to connect to Google Sheets API: %s. Local CSV will be used.", exc)
            self._connected = False
            return False

    def _ensure_worksheets(self) -> None:
        """Ensure 'Leads' and 'Runs' worksheet tabs exist with proper header rows."""
        if not self.spreadsheet:
            return

        # 1. Leads sheet
        try:
            self.leads_sheet = self.spreadsheet.worksheet("Leads")
        except gspread.WorksheetNotFound:
            self.leads_sheet = self.spreadsheet.add_worksheet(title="Leads", rows=500, cols=len(LEADS_COLUMNS))
            self.leads_sheet.append_row(LEADS_COLUMNS)

        # Check headers
        existing_leads_headers = self.leads_sheet.row_values(1)
        if not existing_leads_headers or existing_leads_headers != LEADS_COLUMNS:
            self.leads_sheet.update("A1", [LEADS_COLUMNS])

        # 2. Runs sheet
        try:
            self.runs_sheet = self.spreadsheet.worksheet("Runs")
        except gspread.WorksheetNotFound:
            self.runs_sheet = self.spreadsheet.add_worksheet(title="Runs", rows=200, cols=len(RUNS_COLUMNS))
            self.runs_sheet.append_row(RUNS_COLUMNS)

        existing_runs_headers = self.runs_sheet.row_values(1)
        if not existing_runs_headers or existing_runs_headers != RUNS_COLUMNS:
            self.runs_sheet.update("A1", [RUNS_COLUMNS])

    def sync_lead(self, lead: Lead) -> bool:
        """Sync an individual lead to Google Sheets (update existing row or append new)."""
        row_data = lead_to_sheet_row(lead)
        self._save_to_local_csv(lead)

        if not self._connected:
            self.connect()

        if not self._connected or not self.leads_sheet:
            return False

        try:
            # Find row by Lead ID (Column A)
            cell = self.leads_sheet.find(str(lead.id), in_column=1)
            if cell:
                # Update existing row (1-indexed row number)
                range_name = f"A{cell.row}:{chr(ord('A') + len(LEADS_COLUMNS) - 1)}{cell.row}"
                self.leads_sheet.update(range_name, [row_data])
                log.info("Updated Lead [ID %d] in Google Sheet 'Leads' at row %d", lead.id, cell.row)
            else:
                # Append new row
                self.leads_sheet.append_row(row_data)
                log.info("Appended new Lead [ID %d] to Google Sheet 'Leads'", lead.id)
            return True
        except Exception as exc:
            log.error("Google Sheets sync failed for Lead [ID %d]: %s", lead.id, exc)
            return False

    def sync_all_leads(self, city: Optional[str] = None) -> List[Dict[str, Any]]:
        """Synchronize all leads in SQLite with Google Sheets and the local CSV mirror."""
        query = "SELECT * FROM leads ORDER BY id ASC"
        if city:
            query = f"SELECT * FROM leads WHERE city = '{city}' ORDER BY id ASC"

        rows = self.db.conn.execute(query).fetchall()
        leads = [Lead.from_row(dict(r)) for r in rows]

        log.info("Syncing %d leads with Google Sheets / local mirror...", len(leads))

        # Write entire snapshot to local CSV
        self._write_full_local_csv(leads)

        synced_count = 0
        if not self._connected:
            self.connect()

        if self._connected and self.leads_sheet:
            try:
                # Read all existing lead IDs from Column A
                col_a = self.leads_sheet.col_values(1)
                id_to_row = {}
                for row_idx, val in enumerate(col_a, start=1):
                    if val.isdigit():
                        id_to_row[int(val)] = row_idx

                for lead in leads:
                    row_data = lead_to_sheet_row(lead)
                    if lead.id in id_to_row:
                        r_idx = id_to_row[lead.id]
                        range_name = f"A{r_idx}:{chr(ord('A') + len(LEADS_COLUMNS) - 1)}{r_idx}"
                        self.leads_sheet.update(range_name, [row_data])
                    else:
                        self.leads_sheet.append_row(row_data)
                    synced_count += 1
                log.info("Successfully synced %d leads to Google Sheets.", synced_count)
            except Exception as exc:
                log.error("Batch Google Sheets sync failed: %s", exc)

        results = []
        for lead in leads:
            results.append({
                "lead_id": lead.id,
                "name": lead.name,
                "category": lead.category,
                "city": lead.city,
                "phone": lead.phone or lead.phone_normalized,
                "website_status": lead.website_status,
                "lead_score": lead.score,
                "lead_tier": lead.lead_tier,
                "demo_url": lead.demo_url,
                "status": lead.status.value,
            })
        return results

    def sync_run_summary(
        self,
        city: str = "Vadodara",
        business_type: str = "restaurants",
    ) -> Dict[str, Any]:
        """Compute and log run summary row to 'Runs' sheet tab and local runs CSV."""
        run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Query stats from DB
        c_discovered = self.db.conn.execute("SELECT COUNT(*) FROM leads WHERE city=?", (city,)).fetchone()[0]
        c_qualified = self.db.conn.execute("SELECT COUNT(*) FROM leads WHERE city=? AND qualified=1", (city,)).fetchone()[0]
        c_hot = self.db.conn.execute("SELECT COUNT(*) FROM leads WHERE city=? AND lead_tier='HOT'", (city,)).fetchone()[0]
        c_warm = self.db.conn.execute("SELECT COUNT(*) FROM leads WHERE city=? AND lead_tier='WARM'", (city,)).fetchone()[0]
        c_demo_ready = self.db.conn.execute("SELECT COUNT(*) FROM leads WHERE city=? AND status='DEMO_READY'", (city,)).fetchone()[0]
        c_errors = self.db.conn.execute("SELECT COUNT(*) FROM leads WHERE city=? AND status='FAILED'", (city,)).fetchone()[0]

        summary_row = [
            run_date,
            city,
            business_type,
            c_discovered,
            c_qualified,
            c_hot,
            c_warm,
            c_demo_ready,
            c_errors,
        ]

        # Save to local runs CSV
        self._append_local_run_csv(summary_row)

        if not self._connected:
            self.connect()

        if self._connected and self.runs_sheet:
            try:
                self.runs_sheet.append_row(summary_row)
                log.info("Appended run summary row to Google Sheet 'Runs': %s", summary_row)
            except Exception as exc:
                log.error("Failed to append run summary to Google Sheets: %s", exc)

        return {
            "run_date": run_date,
            "city": city,
            "business_type": business_type,
            "discovered": c_discovered,
            "qualified": c_qualified,
            "hot": c_hot,
            "warm": c_warm,
            "demo_ready": c_demo_ready,
            "errors": c_errors,
        }

    def _write_full_local_csv(self, leads: List[Lead]) -> None:
        """Write all leads to local CSV backup."""
        with open(self.local_csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(LEADS_COLUMNS)
            for lead in leads:
                writer.writerow(lead_to_sheet_row(lead))
        log.info("Saved local mirror CSV with %d leads to %s", len(leads), self.local_csv_path)

    def _save_to_local_csv(self, lead: Lead) -> None:
        """Update or append single lead to local CSV mirror."""
        # Read existing
        existing_rows = []
        if self.local_csv_path.exists():
            with open(self.local_csv_path, mode="r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                existing_rows = list(reader)

        if not existing_rows:
            existing_rows = [LEADS_COLUMNS]

        row_data = [str(x) for x in lead_to_sheet_row(lead)]
        updated = False
        for idx in range(1, len(existing_rows)):
            if len(existing_rows[idx]) > 0 and existing_rows[idx][0] == str(lead.id):
                existing_rows[idx] = row_data
                updated = True
                break

        if not updated:
            existing_rows.append(row_data)

        with open(self.local_csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(existing_rows)

    def _append_local_run_csv(self, summary_row: List[Any]) -> None:
        """Append run summary row to local CSV."""
        write_header = not self.runs_csv_path.exists()
        with open(self.runs_csv_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(RUNS_COLUMNS)
            writer.writerow(summary_row)


def sync_leads(
    city: str = "Vadodara",
    config: Optional[Config] = None,
    db: Optional[Database] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Helper entrypoint to synchronize leads and run summary."""
    logger = SheetsLogger(config=config, db=db)
    lead_results = logger.sync_all_leads(city=city)
    run_summary = logger.sync_run_summary(city=city, business_type="restaurants")
    return lead_results, run_summary


def main():
    import argparse

    parser = argparse.ArgumentParser(description="LeadHunter AI Google Sheets Sync")
    parser.add_argument("--city", default="Vadodara", help="City name filter")
    args = parser.parse_args()

    print(f"\n=== Running Google Sheets & Local Mirror Sync (city='{args.city}') ===")
    lead_results, run_summary = sync_leads(city=args.city)

    print("\n==========================================================================================")
    print("                    GOOGLE SHEETS / LOCAL MIRROR SYNC OUTPUT                              ")
    print("==========================================================================================")
    print(f"Total Leads Synced : {len(lead_results)}")
    print("\n--- Leads Sheet Rows ---")
    for r in lead_results:
        print(f"ID {r['lead_id']:2d} | {r['name']:<38} | Score: {str(r['lead_score'] or 'N/A'):<4} | Tier: {str(r['lead_tier'] or 'LOW'):<4} | Status: {r['status']:<12} | Web: {r['website_status']}")
        if r['demo_url']:
            print(f"       Demo URL: {r['demo_url']}")

    print("\n--- Runs Summary Sheet Row ---")
    print(f"Date: {run_summary['run_date']} | City: {run_summary['city']} | Category: {run_summary['business_type']}")
    print(f"Discovered: {run_summary['discovered']} | Qualified: {run_summary['qualified']} | Hot: {run_summary['hot']} | Warm: {run_summary['warm']} | Demo Ready: {run_summary['demo_ready']} | Errors: {run_summary['errors']}")


if __name__ == "__main__":
    main()
