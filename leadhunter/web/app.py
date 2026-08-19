"""LeadHunter AI — Web Control Dashboard Backend.

Full-stack FastAPI server managing lead operations, human approvals,
interactive pipeline execution, demo previews, and live telemetry.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..approval.approval_queue import process_approval_queue
from ..config import Config, load_env_file, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH
from ..db import Database
from ..demo.server import app as demo_sub_app
from ..demo.url_generator import process_and_generate_demo_urls
from ..discovery.serpapi_search import search_serpapi_google_maps
from ..followup.followup_engine import FollowupEngine
from ..log import get_logger, setup_logging
from ..models import Lead, LeadStatus, utcnow_iso
from ..outreach.email_sender import EmailSender, is_dry_run
from ..outreach.whatsapp_sender import WhatsAppSender
from ..processing.deduplicate import process_leads
from ..processing.lead_scorer import score_and_qualify_leads
from ..processing.website_checker import verify_leads_batch
from ..sheets_logger import SheetsLogger, sync_leads

log = get_logger("web_dashboard")

# Paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DEMO_TEMPLATES_DIR = BASE_DIR.parent / "demo" / "templates"

app = FastAPI(title="LeadHunter AI Web Control Dashboard", version="1.0")

# Mount Static Files
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "js").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
demo_templates = Jinja2Templates(directory=str(DEMO_TEMPLATES_DIR))

# Global DB and Config access
_db_instance: Optional[Database] = None
_config_instance: Optional[Config] = None


def get_db() -> Database:
    data_dir = os.path.join(os.getcwd(), "data")
    db_path = os.path.join(data_dir, "leadhunter.db")
    return Database(db_path)


def get_cfg() -> Optional[Config]:
    global _config_instance
    if _config_instance is None:
        load_env_file(DEFAULT_ENV_PATH)
        try:
            _config_instance = Config.load()
        except Exception:
            _config_instance = None
    return _config_instance


# --------------------------------------------------------------------------
# Page Views & Demo Previews
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard(request: Request):
    """Render main web control dashboard."""
    return templates.TemplateResponse(request=request, name="dashboard.html", context={})


@app.get("/preview/{slug}", response_class=HTMLResponse)
def serve_demo_preview(slug: str, request: Request):
    """Serve live preview landing page for a specific lead slug."""
    db = get_db()
    cur = db.conn.execute("SELECT * FROM leads WHERE demo_url LIKE ? LIMIT 1", (f"%{slug}%",))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Demo preview page not found")

    lead = Lead.from_row(dict(row))
    return demo_templates.TemplateResponse(
        request=request,
        name="preview.html",
        context={"lead": lead, "slug": slug},
    )


# --------------------------------------------------------------------------
# REST API Endpoints
# --------------------------------------------------------------------------

@app.get("/api/stats")
def get_pipeline_stats(city: Optional[str] = None) -> Dict[str, Any]:
    """Return pipeline telemetry and stage metrics."""
    db = get_db()
    city_clause = f"WHERE city = '{city}'" if city else ""

    total = db.conn.execute(f"SELECT COUNT(*) FROM leads {city_clause}").fetchone()[0]
    discovered = db.conn.execute(f"SELECT COUNT(*) FROM leads {city_clause} {'AND' if city else 'WHERE'} status = 'DISCOVERED'").fetchone()[0]
    hot = db.conn.execute(f"SELECT COUNT(*) FROM leads {city_clause} {'AND' if city else 'WHERE'} lead_tier = 'HOT'").fetchone()[0]
    warm = db.conn.execute(f"SELECT COUNT(*) FROM leads {city_clause} {'AND' if city else 'WHERE'} lead_tier = 'WARM'").fetchone()[0]
    demo_ready = db.conn.execute(f"SELECT COUNT(*) FROM leads {city_clause} {'AND' if city else 'WHERE'} demo_url IS NOT NULL AND demo_url != ''").fetchone()[0]
    
    # Approvals pending
    pending_approval = db.conn.execute(
        f"SELECT COUNT(*) FROM approvals WHERE approval_status = 'PENDING_APPROVAL'"
    ).fetchone()[0]

    sent = db.conn.execute(f"SELECT COUNT(*) FROM leads {city_clause} {'AND' if city else 'WHERE'} status = 'SENT'").fetchone()[0]
    dry_run_sent = db.conn.execute(f"SELECT COUNT(*) FROM leads {city_clause} {'AND' if city else 'WHERE'} status = 'DRY_RUN_SENT'").fetchone()[0]

    return {
        "status": "ok",
        "stats": {
            "total": total,
            "discovered": discovered,
            "hot": hot,
            "warm": warm,
            "demo_ready": demo_ready,
            "pending_approval": pending_approval,
            "sent": sent,
            "dry_run_sent": dry_run_sent,
        }
    }


@app.get("/api/leads")
def list_leads(
    city: Optional[str] = None,
    tier: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Query leads with multi-filter and sort options."""
    db = get_db()
    conditions = []
    if city:
        conditions.append(f"city = '{city}'")
    if tier:
        conditions.append(f"lead_tier = '{tier}'")
    if status:
        conditions.append(f"status = '{status}'")

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"SELECT * FROM leads {where_clause} ORDER BY id DESC LIMIT ?"
    rows = db.conn.execute(query, (limit,)).fetchall()

    leads = []
    for r in rows:
        lead_dict = dict(r)
        # Parse tags
        try:
            lead_dict["tags"] = json.loads(lead_dict.get("tags_json") or "{}")
        except Exception:
            lead_dict["tags"] = {}
        try:
            lead_dict["score_reasons"] = json.loads(lead_dict.get("score_reasons_json") or "[]")
        except Exception:
            lead_dict["score_reasons"] = []
        leads.append(lead_dict)

    return {"status": "ok", "count": len(leads), "leads": leads}


@app.get("/api/leads/{lead_id}")
def get_lead_detail(lead_id: int) -> Dict[str, Any]:
    """Fetch complete lead record and history."""
    db = get_db()
    row = db.conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead_dict = dict(row)
    try:
        lead_dict["tags"] = json.loads(lead_dict.get("tags_json") or "{}")
        lead_dict["score_reasons"] = json.loads(lead_dict.get("score_reasons_json") or "[]")
    except Exception:
        pass

    return {"status": "ok", "lead": lead_dict}


class StageRequest(BaseModel):
    stage: str
    city: Optional[str] = "Vadodara"
    category: Optional[str] = "restaurants"
    limit: int = 10


@app.post("/api/pipeline/run-stage")
def execute_stage(req: StageRequest) -> Dict[str, Any]:
    """Execute a single or all pipeline stages on demand."""
    stage = req.stage.lower().strip()
    city = req.city or "Vadodara"
    category = req.category or "restaurants"
    limit = req.limit
    db = get_db()
    cfg = get_cfg()

    try:
        if stage in ("discover", "discovery"):
            search_serpapi_google_maps(city=city, business_type=category, max_results=limit, db=db, config=cfg)
            process_leads(city=city, db=db, config=cfg)
            return {"status": "ok", "message": f"Discovery executed for {category} in {city}"}

        elif stage in ("verify", "verification"):
            verify_leads_batch(city=city, limit=limit, db=db, config=cfg)
            return {"status": "ok", "message": f"Website verification completed for {city}"}

        elif stage in ("score", "scoring", "qualify"):
            score_and_qualify_leads(city=city, limit=limit, db=db, config=cfg)
            return {"status": "ok", "message": f"Lead scoring completed for {city}"}

        elif stage in ("personalize", "personalizer", "ai"):
            from ..ai.personalizer import personalize_qualified_leads
            personalize_qualified_leads(city=city, limit=limit, db=db, config=cfg)
            return {"status": "ok", "message": f"AI personalization completed for {city}"}

        elif stage in ("demo", "demos", "url_generator"):
            process_and_generate_demo_urls(city=city, limit=limit, db=db, config=cfg)
            return {"status": "ok", "message": f"Demo URLs generated for {city}"}

        elif stage in ("approval", "queue_approvals"):
            process_approval_queue(city=city, limit=limit, db=db, config=cfg)
            return {"status": "ok", "message": f"Leads queued for human approval in {city}"}

        elif stage in ("outreach", "dispatch"):
            wa_sender = WhatsAppSender(config=cfg, db=db)
            wa_sender.process_approved_whatsapp(city=city, limit=limit)
            email_sender = EmailSender(config=cfg, db=db)
            email_sender.process_approved_emails(city=city, limit=limit)
            return {"status": "ok", "message": f"Outreach dispatch executed for {city}"}

        elif stage in ("followup", "followups"):
            engine = FollowupEngine(config=cfg, db=db)
            engine.check_and_stage_followups(city=city, limit=limit)
            return {"status": "ok", "message": f"Follow-up sequence executed for {city}"}

        elif stage in ("sync", "sheets"):
            sync_leads(city=city, db=db, config=cfg)
            return {"status": "ok", "message": f"Synced with Google Sheets / Local CSV for {city}"}

        elif stage == "all":
            search_serpapi_google_maps(city=city, business_type=category, max_results=limit, db=db, config=cfg)
            process_leads(city=city, db=db, config=cfg)
            verify_leads_batch(city=city, limit=limit, db=db, config=cfg)
            score_and_qualify_leads(city=city, limit=limit, db=db, config=cfg)
            from ..ai.personalizer import personalize_qualified_leads
            personalize_qualified_leads(city=city, limit=limit, db=db, config=cfg)
            process_and_generate_demo_urls(city=city, limit=limit, db=db, config=cfg)
            process_approval_queue(city=city, limit=limit, db=db, config=cfg)
            sync_leads(city=city, db=db, config=cfg)
            return {"status": "ok", "message": f"Full pipeline executed for {city}"}

        else:
            raise HTTPException(status_code=400, detail=f"Unknown pipeline stage: '{stage}'")

    except Exception as exc:
        log.error("Pipeline stage execution error [%s]: %s", stage, exc)
        return {"status": "error", "error": str(exc)}


@app.get("/api/approvals")
def get_pending_approvals(city: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve all leads in human approval queue."""
    db = get_db()
    city_clause = f" AND l.city = '{city}'" if city else ""
    query = (
        f"SELECT a.*, l.name, l.city, l.category, l.phone, l.email FROM approvals a "
        f"JOIN leads l ON a.lead_id = l.id "
        f"WHERE a.approval_status = 'PENDING_APPROVAL'{city_clause} ORDER BY a.lead_score DESC"
    )
    rows = db.conn.execute(query).fetchall()
    return {"status": "ok", "leads": [dict(r) for r in rows]}


class ReviewDecisionRequest(BaseModel):
    decision: str  # 'APPROVE' or 'REJECT'
    notes: Optional[str] = ""


@app.post("/api/approvals/approve-all")
def approve_all_pending(city: Optional[str] = None) -> Dict[str, Any]:
    """Approve all leads currently pending in approval queue."""
    db = get_db()
    rows = db.conn.execute("SELECT lead_id FROM approvals WHERE approval_status = 'PENDING_APPROVAL'").fetchall()
    count = 0
    for r in rows:
        lid = int(r["lead_id"])
        submit_approval_decision(lid, ReviewDecisionRequest(decision="APPROVE"))
        count += 1
    return {"status": "ok", "count": count}


@app.post("/api/approvals/{lead_id}")
def submit_approval_decision(lead_id: int, req: ReviewDecisionRequest) -> Dict[str, Any]:
    """Update human approval decision for a specific lead."""
    db = get_db()
    now = utcnow_iso()
    decision = req.decision.upper().strip()

    if decision == "APPROVE":
        app_status = "APPROVED"
        lead_status = LeadStatus.APPROVED.value
    elif decision == "REJECT":
        app_status = "REJECTED"
        lead_status = LeadStatus.REJECTED.value
    else:
        raise HTTPException(status_code=400, detail="Invalid decision. Use APPROVE or REJECT.")

    # 1. Update approvals table
    db.conn.execute(
        "UPDATE approvals SET approval_status = ?, reviewed_at = ?, notes = ?, updated_at = ? WHERE lead_id = ?",
        (app_status, now, req.notes or "", now, lead_id),
    )

    # 2. Update leads table & transition
    lead = db.get_lead(lead_id)
    tags = lead.tags or {}
    tags["approval_status"] = app_status
    tags["reviewed_at"] = now

    db.update_lead(lead_id, {
        "tags_json": json.dumps(tags),
        "status": lead_status,
        "updated_at": now,
    })
    db.transition(
        lead_id=lead_id,
        to_status=lead_status,
        stage="web_approval",
        event=f"Lead marked {app_status} via Web Dashboard",
        level="INFO",
    )
    db.conn.commit()

    # Sync to sheets
    sheets = SheetsLogger(config=get_cfg(), db=db)
    sheets.sync_lead(db.get_lead(lead_id))

    return {"status": "ok", "lead_id": lead_id, "decision": app_status}


@app.post("/api/config/dry-run")
def toggle_dry_run() -> Dict[str, Any]:
    """Toggle DRY_RUN safety mode live."""
    current = is_dry_run()
    new_val = not current
    os.environ["DRY_RUN"] = "true" if new_val else "false"
    return {"status": "ok", "dry_run": new_val}


@app.get("/api/logs")
def get_live_logs(limit: int = Query(40, ge=1, le=200)) -> Dict[str, Any]:
    """Stream recent lines from local log file."""
    log_path = Path("./data/logs/leadhunter.log")
    if not log_path.exists():
        return {"status": "ok", "logs": ["[System] Log file empty."]}

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
            return {"status": "ok", "logs": lines[-limit:]}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "logs": []}


@app.get("/api/export/csv")
def export_csv(city: Optional[str] = None):
    """Export database leads to downloadable CSV file."""
    db = get_db()
    city_clause = f"WHERE city = '{city}'" if city else ""
    rows = db.conn.execute(f"SELECT * FROM leads {city_clause} ORDER BY id ASC").fetchall()

    output = io.StringIO()
    if rows:
        keys = rows[0].keys()
        writer = csv.DictWriter(output, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow(dict(r))

    output.seek(0)
    filename = f"leadhunter_export_{city or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Launch uvicorn server programmatically."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
