# 🎯 LeadHunter AI

Autonomous, human-in-the-loop lead generation and outreach engine tailored for digital agencies, web developers, and freelancers.

LeadHunter AI discovers local businesses with missing or weak online presence, scores and qualifies them, generates tailored personalized pitch emails/WhatsApp messages and dynamic demo landing pages, and gates outreach behind a web-based human approval dashboard.

---

## 🚀 Key Features

- **Multi-Source Discovery**: OSM Overpass API (free, zero API key needed), SerpAPI, and Google Places API.
- **Automated Website Qualification**: Probes HTTP status, SSL, mobile responsiveness, and assets to detect leads lacking modern websites.
- **Intelligent Scoring**: Weighted scoring system ranking leads from 0 to 100 based on digital footprint gaps.
- **AI-Powered Personalization**: Generates high-converting Hinglish / English cold messages with dynamic demo previews using Claude / OpenRouter / local templates.
- **Interactive Web Demo Generator**: Automatically constructs tailored demo landing pages (with live preview server and public tunneling support).
- **Human-in-the-Loop Approval UI**: Modern FastAPI web dashboard (`/review`) to inspect, edit, approve, or reject pitches before sending.
- **Multi-Channel Safe Dispatch**: WhatsApp (Meta Cloud API & bridge) and Email (SMTP), guarded with `DRY_RUN=true` by default and strict rate limiting.
- **Full Audit Logging**: SQLite state machine transitions and live Google Sheets synchronization.

---

## 📁 Repository Structure

```
leadhunter-ai/
├── ai/                     # AI personalization engine & prompts
├── approval/               # Approval queue & review viewer
├── demo/                   # Demo landing page generator & preview server
├── discovery/              # Local business discovery (Overpass / Google / SerpAPI)
├── followup/               # Automated follow-up logic
├── leadhunter/             # Core package modules & database models
├── logging/                # Google Sheets & structured logging
├── outreach/               # WhatsApp & Email dispatchers + rate limiters
├── processing/             # Deduplication, normalization, and scoring
├── utils/                  # Error handling & tunnel managers
├── web/                    # FastAPI web server & approval dashboard
├── config.yaml             # Core pipeline settings
├── .env.example            # Environment variables template
├── main.py                 # Pipeline entrypoint CLI
└── requirements.txt        # Python dependencies
```

---

## 🛠️ Quickstart & Setup

### 1. Prerequisites
- Python 3.9+
- Git

### 2. Installation

Clone the repository and install dependencies in a virtual environment:

```bash
git clone https://github.com/Rdzala30/ai-agent-freelancer.git
cd ai-agent-freelancer

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Secrets

Copy the `.env.example` template to `.env`:

```bash
cp .env.example .env
```

Edit `.env` to provide your API keys (optional — pipeline falls back to free OSM & local templates if keys are omitted):
- `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` (for AI pitch personalization)
- `WHATSAPP_TOKEN` & `WHATSAPP_PHONE_NUMBER_ID` (for WhatsApp outreach)
- `GMAIL_APP_PASSWORD` & `SENDER_EMAIL` (for Email outreach)
- `GOOGLE_SHEETS_CREDS_FILE` (for Google Sheets audit logging)
- `DRY_RUN=true` *(Default: safety mode enabled, never sends live outreach)*

### 4. Running the Pipeline

Run discovery and qualification for a target city and business category:

```bash
# Discover leads in a city
python3 main.py --city "Pune" --category "cafe"

# Start the web review dashboard & demo server
python3 web/app.py
```

Access the Human-in-the-Loop review dashboard at:
👉 **`http://localhost:8500/review`**

---

## 🔒 Safety & Privacy

- **Dry-Run by Default**: All outreach dispatchers enforce `DRY_RUN=true` out-of-the-box.
- **Strict Approval Gating**: Messages are only delivered after an explicit human `APPROVED` state.
- **Zero Committed Secrets**: `.env`, service account credentials (`*.json`), and runtime databases (`data/`) are strictly git-ignored.

---

## 📄 License

MIT License — free to use and customize for your own agency and freelance outreach.
