# 🤖 JobAgent

> AI-powered personal job application agent — scans LinkedIn, tailors CVs, gates applications behind WhatsApp approval, auto-applies, and tracks everything in a dashboard.

[![CI](https://github.com/prabhay759/jobagent/actions/workflows/ci.yml/badge.svg)](https://github.com/prabhay759/jobagent/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Powered by Claude](https://img.shields.io/badge/AI-Claude%20Sonnet-orange)](https://anthropic.com)

---

## How It Works

```
LinkedIn Scan (Playwright)
        │
        ▼
 AI Analysis (Claude)         match score · gaps · salary estimate
        │
        ▼  score ≥ threshold?
 WhatsApp Approval Gate ◄──── YOU decide YES / NO / INFO
        │
        ▼  approved
 Tailored CV + Cover Letter   AI-customised per job description
        │
        ▼
 Auto-Apply                   Easy Apply or external form filler
        │
        ▼
 Dashboard                    full pipeline visibility + job chat
```

**Key principle:** You are always in the loop. The WhatsApp gate means nothing is submitted without your explicit approval.

---

## Features

| Feature | Description |
|---|---|
| **LinkedIn Scanner** | Playwright-based, stealth mode, cookie auth, human-like delays |
| **AI Job Analysis** | Claude scores fit 0–100, surfaces gaps, estimates salary |
| **WhatsApp Gate** | Twilio or CallMeBot — YES / NO / INFO before every application |
| **Tailored CV** | AI rewrites bullets to match JD keywords, exports PDF |
| **Cover Letter** | Role-specific, quantified, no generic templates |
| **Easy Apply** | Multi-step form filler (LinkedIn native apply) |
| **External Apply** | Opens browser, fills what it can, you complete the rest |
| **Job Chat** | Ask Claude anything about any job in your pipeline |
| **Dashboard** | React UI — pipeline view, analytics, settings |
| **Cost Control** | Score threshold, daily cap, usage tracker, ~$0.10–0.50/day |

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/prabhay759/jobagent.git
cd jobagent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

### 2. Configure

```bash
jobagent setup
# → creates config/config.yaml and config/profile.yaml from templates
```

Edit `config/config.yaml`:
```yaml
anthropic:
  api_key: "sk-ant-..."       # get from console.anthropic.com

linkedin:
  email: "you@email.com"
  password: "yourpassword"

search:
  keywords: ["Product Manager AI", "Head of Product"]
  locations: ["India", "Remote"]
  min_match_score: 75

whatsapp:
  provider: "twilio"           # or "callmebot" or "mock" (for testing)
  twilio:
    account_sid: "ACxxxxxxxx"
    auth_token: "xxxxxxxx"
    from_number: "whatsapp:+14155238886"
    to_number: "whatsapp:+91XXXXXXXXXX"
```

Edit `config/profile.yaml` — fill in your CV, experience, skills, preferences.

### 3. Run

```bash
# Scan LinkedIn + full pipeline
jobagent scan

# Start web dashboard
jobagent dashboard            # opens http://localhost:8080

# Chat about a specific job
jobagent chat <job_id>

# Process a single job URL
jobagent apply https://linkedin.com/jobs/view/...

# View stats
jobagent stats
```

---

## WhatsApp Approval Flow

When a job scores above your threshold, you get:

```
🤖 JobAgent — New match found!

Senior Product Manager - AI at Anthropic
📍 Remote  |  🌐 External Apply
🎯 Match: 94/100  (Strong Apply)

✅ Strengths: AI domain expertise · PM leadership at scale
⚠️ Gap: No published research
💰 Est. Salary: $180K–220K

🔗 https://linkedin.com/jobs/view/...

Reply YES to apply · NO to skip · INFO to ask questions first
```

| Reply | Action |
|---|---|
| `YES` | CV generated → application submitted |
| `NO` | Job marked skipped |
| `INFO` | Opens chat session in dashboard — re-prompted afterward |

---

## WhatsApp Setup

### Option A: Twilio (Recommended)

1. Create a free [Twilio account](https://console.twilio.com)
2. Enable the **WhatsApp Sandbox** (Messaging → Try it out → Send a WhatsApp message)
3. Note your Account SID, Auth Token, and sandbox number
4. Add to `config/config.yaml` under `whatsapp.twilio`
5. Expose the webhook for replies:
   ```bash
   # Install ngrok: https://ngrok.com/download
   ngrok http 8081
   # Set the ngrok HTTPS URL as your Twilio Sandbox webhook
   ```

### Option B: CallMeBot (Free, simpler)

1. Follow [CallMeBot setup](https://www.callmebot.com/blog/free-api-whatsapp-messages/) (takes ~2 mins)
2. Set `provider: callmebot` and add `phone` + `apikey` to config

### Testing without WhatsApp

Set `provider: mock` — messages are logged to console, replies auto-resolve as `YES`.

---

## LinkedIn Cookie Auth (Recommended)

Password login triggers LinkedIn's bot detection. Use cookies instead:

1. Log into LinkedIn in Chrome
2. Install the [EditThisCookie](https://chrome.google.com/webstore/detail/editthiscookie) extension
3. Export cookies → save as `config/linkedin_cookies.json`
4. Set `use_cookies: true` in config

Cookies typically last 30–90 days before needing refresh.

---

## Dashboard

```bash
jobagent dashboard
# Opens http://localhost:8080
```

![Dashboard Pipeline View](docs/dashboard-preview.png)

**Tabs:**
- **Pipeline** — all jobs, status, match score, pending approvals
- **Analytics** — conversion funnel, charts, rates
- **Settings** — edit config without touching YAML

**Per-job panel:**
- AI analysis: strengths, gaps, salary estimate
- Download tailored CV (PDF)
- Chat: ask Claude about compensation, interview prep, culture

---

## Project Structure

```
jobagent/
├── jobagent/                    # Python package
│   ├── cli.py                   # Click CLI entry point
│   ├── pipeline.py              # Main orchestrator
│   ├── settings.py              # Pydantic-validated config
│   ├── logging_config.py        # Rich structured logging
│   ├── agent/
│   │   ├── ai_client.py         # All Claude API calls + cost tracking
│   │   ├── scanner.py           # LinkedIn Playwright scanner
│   │   └── easy_apply.py        # Easy Apply form filler
│   ├── cv/
│   │   └── generator.py         # CV tailoring + PDF export
│   ├── db/
│   │   └── tracker.py           # SQLite tracker (WAL, migrations)
│   ├── notifier/
│   │   └── whatsapp.py          # Twilio + CallMeBot + webhook server
│   └── dashboard/
│       └── server.py            # FastAPI REST API
├── dashboard/                   # React frontend
│   ├── src/
│   │   ├── App.jsx              # Main dashboard UI
│   │   └── components/
│   └── package.json
├── tests/
│   └── unit/                    # pytest unit tests
├── config/
│   ├── config.example.yaml      # Config template
│   └── profile.example.yaml     # Profile template
├── .github/workflows/ci.yml     # GitHub Actions CI
├── pyproject.toml               # Modern Python packaging
└── README.md
```

---

## Cost Estimate

| Operation | Tokens | Cost (Sonnet) |
|---|---|---|
| Job analysis | ~2K | ~$0.003 |
| CV tailoring | ~4K | ~$0.006 |
| Cover letter | ~1.5K | ~$0.002 |
| Chat message | ~3K | ~$0.005 |

With `min_match_score: 75` and `max_applications_per_day: 10`:
- **Typical daily cost: $0.10–$0.50**
- Run `jobagent stats` to see live usage

---

## Development

```bash
# Install with dev extras
pip install -e ".[dev]"

# Run tests
pytest tests/unit/ -v

# Lint
ruff check jobagent/

# Type check
mypy jobagent/

# Build dashboard
cd dashboard && npm install && npm run dev
```

---

## Roadmap

- [ ] Naukri.com / Indeed / AngelList scanners
- [ ] Telegram bot as WhatsApp alternative
- [ ] Interview prep mode (STAR story bank)
- [ ] ATS score checker for CV
- [ ] Email follow-up automation
- [ ] Salary benchmarking (Glassdoor / Levels.fyi)
- [ ] Scheduled scans (cron)
- [ ] Docker Compose for one-command setup

---

## Ethical Notes

- Uses **your own LinkedIn session** — not mass scraping
- **WhatsApp gate** — you approve every application
- Forms filled with your **real information**
- Please use responsibly — quality over volume

---

## License

MIT — see [LICENSE](LICENSE)

---

## Acknowledgements

Inspired by [career-ops](https://github.com/santifer/career-ops) by [@santifer](https://github.com/santifer).
