"""FastAPI Demo Server for LeadHunter AI.

Renders personalized single-page preview landing pages for leads using Jinja2 templates.
Routes:
- GET /preview/{slug}
- GET /preview?lead_id={id}
- GET /health
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import Config, DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH, load_env_file
from ..db import Database
from ..models import Lead

# Locate templates directory
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
if not TEMPLATES_DIR.exists():
    TEMPLATES_DIR = BASE_DIR.parent.parent / "demo" / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(
    title="LeadHunter AI — Demo Preview Server",
    description="Serves dynamic, personalized demo landing pages for outreach prospects",
    version="0.1.0",
)


def slugify_lead(name: str, city: str) -> str:
    """Generate canonical URL slug for a lead:
    lowercase, spaces/punctuation to hyphens, collapsed.
    Example: 'Sasumaa Gujarati Thali' + 'Vadodara' -> 'sasumaa-gujarati-thali-vadodara'
    """
    combined = f"{name} {city}".lower()
    # Replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", combined)
    # Strip leading/trailing hyphens and multiple hyphens
    return re.sub(r"-+", "-", slug).strip("-")


def get_db() -> Database:
    load_env_file(DEFAULT_ENV_PATH)
    try:
        config = Config.load()
        db_path = config.data_dir / "leadhunter.db"
    except Exception:
        db_path = Path("./data/leadhunter.db")
    return Database(db_path)


def find_lead_by_slug_or_id(db: Database, identifier: str) -> Optional[Lead]:
    """Lookup lead by exact slug, ID, or partial name/demo_url match."""
    # 1. Try integer ID
    if identifier.isdigit():
        try:
            return db.get_lead(int(identifier))
        except Exception:
            pass

    # 2. Check all leads and match slugified name
    rows = db.conn.execute("SELECT * FROM leads").fetchall()
    all_leads = [Lead.from_row(dict(r)) for r in rows]

    for lead in all_leads:
        lead_slug = slugify_lead(lead.name, lead.city)
        if lead_slug == identifier:
            return lead
        if lead.demo_url and identifier in lead.demo_url:
            return lead

    # 3. Fallback: match without city
    for lead in all_leads:
        pure_name_slug = re.sub(r"[^a-z0-9]+", "-", lead.name.lower()).strip("-")
        if pure_name_slug in identifier or identifier in pure_name_slug:
            return lead

    return None


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "leadhunter-demo-server"}


@app.get("/preview/{slug}", response_class=HTMLResponse)
def render_preview_by_slug(request: Request, slug: str):
    """Serve personalized single-page preview site for lead slug."""
    db = get_db()
    lead = find_lead_by_slug_or_id(db, slug)
    if not lead:
        raise HTTPException(
            status_code=404,
            detail=f"No preview demo found for business '{slug}'",
        )

    return templates.TemplateResponse(
        request=request,
        name="preview.html",
        context={
            "lead": lead,
            "slug": slug,
        },
    )


@app.get("/preview", response_class=HTMLResponse)
def render_preview_query(
    request: Request,
    lead_id: Optional[int] = None,
    slug: Optional[str] = None,
):
    """Fallback route supporting ?lead_id=123 or ?slug=..."""
    db = get_db()
    lead = None
    if lead_id is not None:
        try:
            lead = db.get_lead(lead_id)
        except Exception:
            lead = None
    elif slug:
        lead = find_lead_by_slug_or_id(db, slug)

    if not lead:
        raise HTTPException(
            status_code=404,
            detail="No preview demo found. Please provide a valid lead_id or slug.",
        )

    return templates.TemplateResponse(
        request=request,
        name="preview.html",
        context={
            "lead": lead,
            "slug": slug or str(lead.id),
        },
    )


def run_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
