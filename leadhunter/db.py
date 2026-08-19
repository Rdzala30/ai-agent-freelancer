"""Persistent lead state store (SQLite).

Resumability contract:
- The `leads.status` column IS the pipeline position. A stage processes only
  leads sitting at that stage's input status; a crashed/stopped run leaves
  statuses untouched, and the next run continues from exactly there.
- `lead_events` is the append-only audit trail (who/what/when/level).
- `kv` stores one-shot markers (e.g. "discovery done for Pune/cafe") so a
  completed discovery is not repeated unless --refresh is passed.
- `runs` records per-run metadata and stage statistics.
- FAILED leads remember their `stage_status` (the stage input they came from)
  and are re-promoted when retries remain and the failure was retryable.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import state_machine as sm
from .errors import NotFoundError, StateTransitionError
from .log import get_logger
from .models import Lead, utcnow_iso

log = get_logger("db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    city TEXT NOT NULL,
    category TEXT NOT NULL,
    params_json TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    stats_json TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT,
    source TEXT NOT NULL,
    run_id INTEGER,
    name TEXT NOT NULL,
    category TEXT,
    city TEXT,
    address TEXT,
    lat REAL,
    lon REAL,
    phone TEXT,
    phone_normalized TEXT,
    email TEXT,
    website TEXT,
    website_verified TEXT,
    website_status TEXT,
    rating REAL,
    reviews_count INTEGER,
    tags_json TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    score REAL,
    score_reasons_json TEXT DEFAULT '[]',
    lead_tier TEXT,
    qualified INTEGER DEFAULT 0,
    qualification_notes TEXT DEFAULT '',
    site_profile_json TEXT DEFAULT '{}',
    personalized_message TEXT,
    email_subject TEXT,
    email_message TEXT,
    whatsapp_message TEXT,
    demo_url TEXT,
    demo_path TEXT,
    outreach_channel TEXT,
    outreach_status TEXT,
    fingerprint TEXT UNIQUE,
    stage_status TEXT,
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_run ON leads(run_id);

CREATE TABLE IF NOT EXISTS lead_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    run_id INTEGER,
    ts TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    stage TEXT,
    level TEXT DEFAULT 'INFO',
    event TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_lead ON lead_events(lead_id);
CREATE INDEX IF NOT EXISTS idx_events_run ON lead_events(run_id);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL UNIQUE,
    business_name TEXT NOT NULL,
    lead_score REAL,
    lead_tier TEXT,
    email_message TEXT,
    whatsapp_message TEXT,
    demo_url TEXT,
    website_status TEXT,
    approval_status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL',
    reviewed_at TEXT,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_approvals_lead ON approvals(lead_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(approval_status);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.init_schema()

    # ---- schema / lifecycle ---------------------------------------------

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        for col in ("website_status", "lead_tier", "email_message", "whatsapp_message", "demo_status", "last_contacted_at", "next_followup_due"):
            try:
                self.conn.execute(f"ALTER TABLE leads ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        try:
            self.conn.execute("ALTER TABLE leads ADD COLUMN followup_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- runs ------------------------------------------------------------

    def start_run(self, city: str, category: str, params: Dict[str, Any]) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, city, category, params_json) VALUES (?,?,?,?)",
            (utcnow_iso(), city, category, json.dumps(params, default=str)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def end_run(self, run_id: int, status: str, stats: Dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, status=?, stats_json=? WHERE id=?",
            (utcnow_iso(), status, json.dumps(stats, default=str), run_id),
        )
        self.conn.commit()

    def get_run(self, run_id: int) -> Dict[str, Any]:
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"run {run_id} not found")
        return dict(row)

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- leads -----------------------------------------------------------

    def insert_lead(self, lead: Lead) -> Tuple[int, bool]:
        """Insert a new lead. Returns (lead_id, inserted).

        `inserted=False` means a lead with the same dedup fingerprint already
        exists; the existing id is returned and nothing is duplicated.
        """
        row = lead.to_row()
        if row["fingerprint"]:
            existing = self.conn.execute(
                "SELECT id FROM leads WHERE fingerprint=?", (row["fingerprint"],)
            ).fetchone()
            if existing:
                return int(existing["id"]), False
        cur = self.conn.execute(
            """INSERT INTO leads (
                external_id, source, run_id, name, category, city, address,
                lat, lon, phone, phone_normalized, email, website,
                website_verified, website_status, rating, reviews_count, tags_json, status,
                score, score_reasons_json, lead_tier, qualified, qualification_notes,
                site_profile_json, personalized_message, email_subject,
                email_message, whatsapp_message,
                demo_url, demo_path, outreach_channel, outreach_status,
                fingerprint, stage_status, retry_count, last_error,
                created_at, updated_at
            ) VALUES (
                :external_id, :source, :run_id, :name, :category, :city, :address,
                :lat, :lon, :phone, :phone_normalized, :email, :website,
                :website_verified, :website_status, :rating, :reviews_count, :tags_json, :status,
                :score, :score_reasons_json, :lead_tier, :qualified, :qualification_notes,
                :site_profile_json, :personalized_message, :email_subject,
                :email_message, :whatsapp_message,
                :demo_url, :demo_path, :outreach_channel, :outreach_status,
                :fingerprint, :stage_status, :retry_count, :last_error,
                :created_at, :updated_at
            )""",
            row,
        )
        self.conn.commit()
        return int(cur.lastrowid), True

    def get_lead(self, lead_id: int) -> Lead:
        row = self.conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"lead {lead_id} not found")
        return Lead.from_row(dict(row))

    def get_lead_by_fingerprint(self, fingerprint: str) -> Optional[Lead]:
        row = self.conn.execute(
            "SELECT * FROM leads WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        return Lead.from_row(dict(row)) if row else None

    def get_leads_by_status(self, status: str, limit: int = 100) -> List[Lead]:
        rows = self.conn.execute(
            "SELECT * FROM leads WHERE status=? ORDER BY id LIMIT ?", (status, limit)
        ).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    def get_leads_by_statuses(self, statuses: List[str], limit: int = 100) -> List[Lead]:
        if not statuses:
            return []
        marks = ",".join("?" * len(statuses))
        rows = self.conn.execute(
            f"SELECT * FROM leads WHERE status IN ({marks}) ORDER BY id LIMIT ?",
            (*statuses, limit),
        ).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    def get_lead_ids_by_status(self, status: str, limit: int = 100) -> List[int]:
        rows = self.conn.execute(
            "SELECT id FROM leads WHERE status=? ORDER BY id LIMIT ?", (status, limit)
        ).fetchall()
        return [int(r["id"]) for r in rows]

    # ---- resume capabilities --------------------------------------------

    def get_resumable_leads(
        self,
        stage: str,
        city: Optional[str] = None,
        limit: int = 100,
    ) -> List[Lead]:
        """Fetch only leads that need processing for the requested stage,
        skipping all leads that have already completed this stage or later stages.
        """
        stage_lower = stage.lower().strip()
        city_clause = f" AND city = '{city}'" if city else ""

        if stage_lower in ("verification", "website_checker", "verify"):
            # Needs website verification: DISCOVERED / ENRICHED without website_status
            query = (
                f"SELECT * FROM leads WHERE status IN ('DISCOVERED', 'ENRICHED') "
                f"AND (website_status IS NULL OR website_status = '')"
                f"{city_clause} ORDER BY id ASC LIMIT ?"
            )
        elif stage_lower in ("scoring", "lead_scorer", "qualify"):
            # Needs scoring: VERIFIED but not yet QUALIFIED/SCORED
            query = (
                f"SELECT * FROM leads WHERE status = 'VERIFIED' "
                f"AND (score IS NULL OR lead_tier IS NULL)"
                f"{city_clause} ORDER BY id ASC LIMIT ?"
            )
        elif stage_lower in ("personalization", "personalizer", "ai"):
            # Needs message generation: QUALIFIED/HOT/WARM with missing messages
            query = (
                f"SELECT * FROM leads WHERE status = 'QUALIFIED' "
                f"AND (lead_tier = 'HOT' OR lead_tier = 'WARM') "
                f"AND (email_message IS NULL OR email_message = '')"
                f"{city_clause} ORDER BY id ASC LIMIT ?"
            )
        elif stage_lower in ("demo", "url_generator", "demo_generator"):
            # Needs demo page: PERSONALIZED but demo_status != 'READY'
            query = (
                f"SELECT * FROM leads WHERE status = 'PERSONALIZED' "
                f"AND (demo_status IS NULL OR demo_status != 'READY')"
                f"{city_clause} ORDER BY id ASC LIMIT ?"
            )
        elif stage_lower in ("approval", "approval_queue", "approval_viewer"):
            # Needs approval: DEMO_READY or PENDING_APPROVAL with pending decision
            query = (
                f"SELECT * FROM leads WHERE (status = 'DEMO_READY' OR status = 'PENDING_APPROVAL') "
                f"AND status NOT IN ('APPROVED', 'REJECTED', 'SENT', 'DO_NOT_CONTACT')"
                f"{city_clause} ORDER BY id ASC LIMIT ?"
            )
        elif stage_lower in ("outreach", "email_sender", "whatsapp_sender"):
            # Ready for outreach: APPROVED but not yet sent
            query = (
                f"SELECT * FROM leads WHERE status = 'APPROVED' "
                f"AND (whatsapp_status IS NULL OR whatsapp_status NOT IN ('SENT', 'DRY_RUN_SENT'))"
                f"{city_clause} ORDER BY id ASC LIMIT ?"
            )
        else:
            # Fallback
            query = f"SELECT * FROM leads WHERE 1=1{city_clause} ORDER BY id ASC LIMIT ?"

        rows = self.conn.execute(query, (limit,)).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    def is_stage_completed(self, lead_id: int, stage: str) -> bool:
        """Check if a lead has already completed a specific stage."""
        lead = self.get_lead(lead_id)
        stage_lower = stage.lower().strip()

        if stage_lower in ("verification", "website_checker"):
            return lead.website_status is not None and lead.website_status != ""
        elif stage_lower in ("scoring", "lead_scorer"):
            return lead.score is not None and lead.lead_tier is not None
        elif stage_lower in ("personalization", "personalizer"):
            return lead.email_message is not None and lead.email_message != ""
        elif stage_lower in ("demo", "url_generator"):
            return lead.demo_url is not None and lead.demo_url != ""
        elif stage_lower in ("approval", "approval_gate"):
            tags = lead.tags or {}
            return lead.status in (LeadStatus.APPROVED, LeadStatus.REJECTED) or tags.get("approval_status") in ("APPROVED", "REJECTED")
        elif stage_lower in ("outreach", "email", "whatsapp"):
            tags = lead.tags or {}
            return lead.status in (LeadStatus.SENT, LeadStatus.DRY_RUN_SENT) or tags.get("whatsapp_status") == "SENT" or tags.get("email_status") == "SENT"
        return False

    def update_lead(self, lead_id: int, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        fields["updated_at"] = utcnow_iso()
        assignments = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"UPDATE leads SET {assignments} WHERE id=?",
            (*fields.values(), lead_id),
        )
        self.conn.commit()

    def transition(
        self,
        lead_id: int,
        to_status: str,
        *,
        run_id: Optional[int] = None,
        stage: str = "",
        event: str = "",
        level: str = "INFO",
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Validate + apply a state transition, and audit it."""
        lead = self.get_lead(lead_id)
        from_status = lead.status.value
        if from_status == to_status:
            return
        sm.assert_transition(from_status, to_status)
        fields: Dict[str, Any] = {"status": to_status}
        if to_status == "FAILED":
            fields["stage_status"] = stage or from_status
            fields["retry_count"] = lead.retry_count + 1
            fields["last_error"] = event
        elif to_status != "FAILED":
            fields["stage_status"] = None
            if to_status == "DISCARDED":
                fields["last_error"] = None
        if extra_fields:
            fields.update(extra_fields)
        self.update_lead(lead_id, fields)
        self.record_event(
            lead_id=lead_id,
            run_id=run_id,
            from_status=from_status,
            to_status=to_status,
            stage=stage,
            event=event,
            level=level,
        )

    def recover_failed(self, max_retries: int) -> List[int]:
        """Re-promote retryable FAILED leads back to their stage status.

        Returns the list of recovered lead ids. FAILED leads whose retry
        budget is spent, or whose last error is non-retryable, stay FAILED.
        """
        rows = self.conn.execute(
            "SELECT id, stage_status, retry_count, last_error FROM leads WHERE status='FAILED'"
        ).fetchall()
        recovered: List[int] = []
        from .retry import is_retryable

        for row in rows:
            if row["retry_count"] >= max_retries:
                continue
            try:
                error_obj = json.loads(row["last_error"] or "") if row["last_error"] else None
                retryable = bool(error_obj.get("retryable")) if isinstance(error_obj, dict) else True
            except (ValueError, AttributeError):
                retryable = True
            if not retryable:
                continue
            target = row["stage_status"] or "DISCOVERED"
            try:
                sm.assert_transition("FAILED", target)
            except StateTransitionError:
                continue
            self.conn.execute(
                "UPDATE leads SET status=?, stage_status=NULL WHERE id=?",
                (target, row["id"]),
            )
            self.conn.commit()
            self.record_event(
                lead_id=row["id"],
                from_status="FAILED",
                to_status=target,
                stage="recovery",
                event="retryable failure — re-promoted for retry",
                level="WARN",
            )
            recovered.append(int(row["id"]))
        return recovered

    # ---- audit trail -----------------------------------------------------

    def record_event(
        self,
        *,
        lead_id: Optional[int] = None,
        run_id: Optional[int] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        stage: str = "",
        event: str = "",
        level: str = "INFO",
    ) -> None:
        self.conn.execute(
            """INSERT INTO lead_events
               (lead_id, run_id, ts, from_status, to_status, stage, level, event)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                lead_id,
                run_id,
                utcnow_iso(),
                from_status,
                to_status,
                stage,
                level,
                event,
            ),
        )
        self.conn.commit()

    def events_for_lead(self, lead_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM lead_events WHERE lead_id=? ORDER BY id DESC LIMIT ?",
            (lead_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def events_for_run(self, run_id: int, limit: int = 1000) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM lead_events WHERE run_id=? ORDER BY id LIMIT ?",
            (run_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- kv markers ------------------------------------------------------

    def kv_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO kv (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def kv_get(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    # ---- stats -----------------------------------------------------------

    def counts_by_status(self) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM leads GROUP BY status"
        ).fetchall()
        return {r["status"]: int(r["n"]) for r in rows}

    def leads_for_report(self, run_id: Optional[int] = None, limit: int = 200) -> List[Dict[str, Any]]:
        if run_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM leads WHERE run_id=? ORDER BY id LIMIT ?", (run_id, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
