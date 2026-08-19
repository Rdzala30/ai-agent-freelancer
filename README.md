# ai-agent-freelancer
LeadHunter AI — Autonomous lead generation agent that finds local businesses, scores them, and sends personalized Email + WhatsApp outreach. Built with Claude Code + Python.


# 🎯 LeadHunter AI

> An autonomous lead generation agent that discovers local businesses, qualifies them, scores their web presence, generates personalized outreach with live demo pages, and dispatches Emails and WhatsApp messages — with a human approval gate at every send.

Built with **Claude Code + Python** in 13 prompts. No manual coding required.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Claude API](https://img.shields.io/badge/Claude-API-orange.svg)](https://console.anthropic.com)
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
| 🔍 **Discovery** | SerpAPI searches Google Maps for local businesses |
| 🧹 **Normalize & Dedup** | Cleans data, removes duplicates, scores lead quality |
| 🌐 **Website Checker** | Classifies each lead: NO_WEBSITE / BROKEN / SOCIAL_ONLY etc. |
| 🔥 **Lead Scoring** | Assigns HOT / WARM / LOW tier based on 7 signals |
| 🤖 **AI Personalization** | Claude API writes a unique outreach message per lead |
| 📄 **Demo Page** | Generates a live Cloudflare Tunnel URL for each prospect |
| ✅ **Human Approval** | You review and approve every message before it sends |
| 📧 **Outreach** | Gmail + WhatsApp Cloud API sends approved messages |
| 🔄 **Follow-Up Engine** | Auto follow-ups on Day 3, Day 7 if no reply |

---

## 🛠️ Tech Stack

| Tool | Purpose | Cost |
|---|---|---|
| Python 3.11+ | Core language | FREE |
| Claude API | AI message personalization | Paid (per token) |
| SerpAPI | Local business discovery | 100 free searches/month |
| SQLite | Local lead database | FREE |
| Google Sheets API | CRM logging | FREE |
| Gmail (App Password) | Email outreach | FREE |
| WhatsApp Cloud API | WhatsApp outreach | FREE |
| FastAPI | Demo page server | FREE |
| Cloudflare Tunnel | Public demo URLs | FREE |

---

## 📁 Project Structure

```
leadhunter-ai/
├── main.py                  ← Master orchestrator
├── config.py                ← All settings + env vars
├── database.py              ← SQLite setup
├── models.py                ← Lead dataclass
├── .env                     ← API keys (NEVER commit this)
├── google_creds.json        ← Service Account JSON (NEVER commit)
├── requirements.txt
│
├── discovery/
│   └── serpapi_search.py
│
├── processing/
│   ├── normalize.py
│   ├── deduplicate.py
│   ├── website_checker.py
│   └── lead_scorer.py
│
├── ai/
│   └── personalizer.py
│
├── demo/
│   ├── url_generator.py
│   ├── server.py
│   └── templates/
│       └── preview.html
│
├── logging/
│   └── sheets_logger.py
│
├── approval/
│   ├── approval_queue.py
│   └── approval_viewer.py
│
├── outreach/
│   ├── email_sender.py
│   ├── whatsapp_sender.py
│   └── rate_limiter.py
│
├── followup/
│   └── followup_engine.py
│
├── web/
│   └── app.py              ← Web dashboard
│
└── utils/
    ├── logger.py
    └── error_handler.py
```

---

## ⚙️ Setup Instructions

### Step 1 — Clone the Repository

```bash
git clone https://github.com/Rdzala30/ai-agent-freelancer.git
cd ai-agent-freelancer
```

### Step 2 — Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Create Your `.env` File

Create a file named `.env` in the root folder and fill in your keys:

```env
ANTHROPIC_API_KEY=sk-ant-your-key-here
SERPAPI_KEY=your-serpapi-key
GOOGLE_SHEET_ID=your-sheet-id-from-url
GOOGLE_CREDS_PATH=./google_creds.json
GMAIL_SENDER=your-email@gmail.com
GMAIL_APP_PASSWORD=your-16-char-app-password
WHATSAPP_TOKEN=your-meta-whatsapp-token
WHATSAPP_PHONE_ID=your-phone-number-id
DEMO_BASE_URL=https://your-cloudflare-tunnel-url.com
DRY_RUN=true
HUMAN_APPROVAL=true
```

> ⚠️ **NEVER share your `.env` file or commit it to GitHub. Your API keys are secret.**

### Step 4 — Add Google Service Account

- Go to [Google Cloud Console](https://console.cloud.google.com)
- Create a Service Account → Download the JSON
- Save it as `google_creds.json` in the root folder
- Share your Google Sheet with the service account email as **Editor**

### Step 5 — Run the Agent

```bash
# Full pipeline (discovery → outreach)
python main.py

# Run follow-ups only
python main.py --followups

# Start web dashboard
python web/app.py
```

---

## 🔑 Where to Get API Keys

| Key | Link |
|---|---|
| Anthropic API Key | [console.anthropic.com](https://console.anthropic.com) |
| SerpAPI Key | [serpapi.com](https://serpapi.com) |
| Google Sheets API | [console.cloud.google.com](https://console.cloud.google.com) |
| Gmail App Password | [myaccount.google.com → Security → App Passwords](https://myaccount.google.com) |
| WhatsApp Cloud API | Meta Business Manager → WhatsApp |
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

Follow-ups are skipped if lead replied, said stop, or converted.

---

## 🐛 Common Errors & Fixes

| Error | Cause | Fix |
|---|---|---|
| HTTP 429 | Too many API requests | Add delay between calls |
| GOOGLE_AUTH_ERROR | Wrong credentials path | Check `GOOGLE_CREDS_PATH` in `.env` |
| Demo URL broken | FastAPI server not running | Start with `uvicorn demo.server:app` |
| Duplicate leads | Normalization order issue | Ensure normalize runs before hashing |
| Google Sheets not updating | Service account not added as Editor | Share sheet → paste service account email → Editor |
| Phone number format wrong | +91 not stripped | Ensure `normalize.py` runs first |

---

## 🛡️ Safety Features

- `DRY_RUN=true` → Runs everything but **does not send** any message
- `HUMAN_APPROVAL=true` → Every message requires your approval before sending
- Rate limiter built-in to prevent API abuse
- `.env` and `google_creds.json` excluded from git via `.gitignore`

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
