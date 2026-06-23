# AI SDR Agent — Event Sponsorship Template

An AI-powered SDR agent that researches companies, scores sponsor fit, and drafts personalized outreach email sequences for any B2B event.

## What it does

1. **Research** — type any company name, agent searches the web and scores their fit as a sponsor
2. **Pipeline** — manage 400+ target companies with tier, status, and contact info
3. **Outreach** — generate 3-touch personalized email sequences, review and approve before sending
4. **Radar** — automatically finds new sponsor targets daily based on event signals
5. **Import** — upload CSV from LinkedIn Sales Nav or Seamless.AI to bulk-add companies

## Setup (5 steps)

### 1. Install Python
Download from python.org — check "Add Python to PATH" during install.

### 2. Get API keys
- Anthropic: console.anthropic.com/keys
- Tavily: app.tavily.com (free, 1000 searches/month)

### 3. Configure your event
Edit `event_config.py` — change the event name, dates, location, and point it to your attendee CSV.

### 4. Install and run
Open PowerShell in this folder and run:
```
pip install -r requirements.txt
copy .env.example .env
```
Edit `.env` and add your API keys. Then:
```
python icp_profile.py
streamlit run app.py
```

### 5. Deploy to the web (optional)
Push to GitHub, connect to share.streamlit.io — permanent URL, always on.

## Folder structure
```
sdr_agent_template/
├── event_config.py       ← EDIT THIS for your event
├── app.py                ← Main web app
├── icp_profile.py        ← Analyzes your attendee list
├── score_company.py      ← Scores sponsor fit
├── generate_outreach.py  ← Writes email sequences
├── radar.py              ← Daily prospecting search
├── requirements.txt      ← Python packages
├── .env.example          ← API key template
└── README.md             ← This file
```

## Built with
- Claude (Anthropic) — AI research, scoring, email writing
- Tavily — web search
- Streamlit — web UI
- Python
