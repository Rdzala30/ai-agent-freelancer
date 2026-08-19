# 🎯 LeadHunter AI

> An autonomous lead generation agent that discovers local businesses, qualifies them, scores their web presence, generates personalized outreach with live demo pages, and dispatches Emails and WhatsApp messages — with a human approval gate at every send.

Built with **Python + AI**. Designed for digital agencies, web developers, and freelancers.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 📺 Full Tutorial

Watch the complete build on YouTube:
**[I Built an AI Agent for Freelancers That Finds Clients & Does Outreach Automatically](https://youtube.com/@Ai-with-Rajpalsinh)**

---

## 🚀 What It Does

```
Discovery → Normalize → Website Check → Score & Qualify → AI Personalize → Demo Page → Human Approval → Outreach → Follow-Up
```

| Stage | What Happens |
|---|---|
| 🔍 **Discovery** | OSM Overpass (free) + SerpAPI / Google Maps searches for local businesses |
| 🧹 **Normalize & Dedup** | Cleans data, removes duplicates, normalizes Indian phone numbers |
| 🌐 **Website Checker** | Classifies each lead: NO_WEBSITE / BROKEN / SOCIAL_ONLY / WEAK etc. |
| 🔥 **Lead Scoring** | Assigns HOT / WARM / LOW tier based on digital presence gaps |
| 🤖 **AI Personalization** | Generates high-converting Hinglish / English pitch messages + dynamic previews |
| 📄 **Demo Page** | Builds tailored demo landing pages with public tunnel support |
| ✅ **Human Approval** | Web UI dashboard to review, edit, approve, or reject pitches before sending |
| 📧 **Outreach** | Meta WhatsApp Cloud API / bridge + Gmail SMTP sends approved messages |
| 🔄 **Follow-Up Engine** | Auto follow-ups on Day 3 and Day 7 if no reply |

---

## 🛠️ Tech Stack

| Tool | Purpose | Cost |
|---|---|---|
| Python 3.10+ | Core language & pipeline | FREE |
| OpenStreetMap / Overpass | Free zero-key local business discovery | FREE |
| Claude / OpenRouter / DeepSeek | AI message personalization | Pay-as-you-go |
| SerpAPI | Local business discovery (Google Maps) | Free tier available |
| SQLite | Local state machine & lead database | FREE |
| Google Sheets API | Real-time CRM & audit logging | FREE |
| Gmail (App Password) | Email outreach | FREE |
| WhatsApp Cloud API | WhatsApp outreach | FREE |
| FastAPI + Jinja2 | Demo server & Human Approval dashboard | FREE |
| Cloudflare Tunnel | Public HTTPS demo URLs | FREE |

---

## 📁 Project Structure

```
leadhunter-ai/
├── main.py                  ← Master pipeline CLI entrypoint
├── config.yaml              ← Pipeline configuration & settings
├── database.py              ← SQLite database helper
├── requirements.txt         ← Dependencies
├── .env.example             ← Environment variables template
│
├── discovery/               ← Local business discovery modules
│   └── serpapi_search.py
│
├── processing/              ← Data cleansing & qualification
│   ├── normalize.py
│   ├── deduplicate.py
│   ├── website_checker.py
│   └── lead_scorer.py
│
├── ai/                      ← AI pitch personalization
│   └── personalizer.py
│
├── demo/                    ← Live demo generator & preview server
│   ├── url_generator.py
│   ├── server.py
│   └── templates/
│       └── preview.html
│
├── logging/                 ← Sheets & audit loggers
│   └── sheets_logger.py
│
├── approval/                ← Human-in-the-loop review queues
│   ├── approval_queue.py
│   └── approval_viewer.py
│
├── outreach/                ← WhatsApp & Email dispatchers
│   ├── email_sender.py
│   ├── whatsapp_sender.py
│   └── rate_limiter.py
│
├── followup/                ← Automated multi-stage follow-up engine
│   └── followup_engine.py
│
├── web/                     ← FastAPI dashboard application
│   └── app.py
│
└── utils/                   ← Tunneling & error handlers
    ├── error_handler.py
    └── tunnel_manager.py
```

---

## ⚙️ Setup Instructions

### Step 1 — Clone the Repository

```bash
git clone https://github.com/Rdzala30/ai-agent-freelancer.git
cd ai-agent-freelancer
```

### Step 2 — Create Virtual Environment & Install Dependencies

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 3 — Create Your `.env` File

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
# AI Personalization (Claude or OpenRouter)
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=

# Discovery (Optional fallback)
SERPAPI_KEY=
GOOGLE_PLACES_API_KEY=

# Google Sheets Audit CRM (Optional)
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SHEETS_CREDS_FILE=./google_creds.json

# Outreach Channels
GMAIL_APP_PASSWORD=
SENDER_EMAIL=
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=

# Outreach Safety Mode (Default: true = simulation only)
DRY_RUN=true
```

> ⚠️ **NEVER share your `.env` file or commit it to GitHub. Your API keys are strictly secret.**

### Step 4 — Add Google Service Account (Optional for Google Sheets)

- Go to [Google Cloud Console](https://console.cloud.google.com)
- Create a Service Account → Download the JSON key
- Save it as `google_creds.json` in the root folder *(ignored by git)*
- Share your Google Sheet with the service account email as **Editor**

### Step 5 — Run LeadHunter AI

```bash
# Run discovery, scoring, and personalization
python3 main.py --city "Pune" --category "cafe"

# Start the Web Approval Dashboard & Demo Server
python3 web/app.py
```

Access the Human-in-the-Loop review dashboard at:
👉 **`http://localhost:8500/review`**

---

## 🔑 Where to Get API Keys

| Key | Link |
|---|---|
| Anthropic API Key | [console.anthropic.com](https://console.anthropic.com) |
| OpenRouter API Key | [openrouter.ai](https://openrouter.ai) |
| SerpAPI Key | [serpapi.com](https://serpapi.com) |
| Google Cloud Console | [console.cloud.google.com](https://console.cloud.google.com) |
| Gmail App Password | [myaccount.google.com → Security → App Passwords](https://myaccount.google.com) |
| WhatsApp Cloud API | Meta Developers / Business Manager → WhatsApp |
| Cloudflare Tunnel | [developers.cloudflare.com](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) |

---

## 🔥 Lead Scoring System

| Signal | Points |
|---|---|
| NO_WEBSITE | 40 pts — clearest need |
| BROKEN_WEBSITE | 35 pts |
| SOCIAL_ONLY | 30 pts |
| DIRECTORY_ONLY | 28 pts |
| Has phone number | +15 pts |
| Has email | +10 pts |
| Rating 4.0+ with 20+ reviews | +15 pts |
| Has Instagram | +5 pts |
| Is restaurant / clinic / salon / gym | +10 pts |

| Tier | Score | Action |
|---|---|---|
| 🔥 HOT | 70+ | Move forward immediately |
| ⚡ WARM | 45–69 | Worth reaching out |
| ❄️ LOW | Below 45 | Saved, not processed |

---

## 🔄 Follow-Up Schedule

```
Day 0  → Initial message sent
Day 3  → Follow-Up 1 (if no reply)
Day 7  → Follow-Up 2 (if still no reply)
Day 10 → Mark as COLD — stop outreach
```

Follow-ups are automatically skipped if the lead replied, opted out, or converted.

---

## 🛡️ Safety & Privacy

- `DRY_RUN=true` → Runs everything safely without sending live messages until you are ready.
- `HUMAN_APPROVAL` → Every outreach message requires manual confirmation in the web dashboard.
- Built-in rate limiters prevent API and messaging abuse.
- `.env`, service account JSONs (`google_creds.json`), and database files (`data/`) are strictly excluded via `.gitignore`.

---

## 📄 License

MIT License — free to use, modify, and distribute. See [LICENSE](LICENSE) for details.

---

## 🙋 About the Creator

Built by **Rajpalsinh Zala** — AI Automation Engineer & YouTuber

- 📺 YouTube: [@Ai-with-Rajpalsinh](https://youtube.com/@Ai-with-Rajpalsinh)
- 📸 Instagram: [@rajpalsinh__zala](https://instagram.com/rajpalsinh__zala)
- 💼 LinkedIn: [rajpalsinh-zala](https://linkedin.com/in/rajpalsinh-zala-a92b82276/)
- 📧 Email: rajpalsinh.zala.ai@gmail.com

---

> ⭐ If this project helped you, please star the repo and subscribe to the channel!
