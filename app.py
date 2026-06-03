"""
Field Service East — AI SDR Agent
Run with: streamlit run app.py
"""
import streamlit as st
import json
import csv
import os
import importlib
from pathlib import Path
from dotenv import load_dotenv
import anthropic
from tavily import TavilyClient
import outlook_integration as outlook
import storage

load_dotenv()

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FSE SDR Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Data files ────────────────────────────────────────────────────────────────
ICP_FILE = "icp_summary.json"
PIPELINE_FILE = "pipeline.json"

# ── Load ICP ──────────────────────────────────────────────────────────────────
def load_icp():
    return storage.load_icp()

# ── Pipeline helpers ──────────────────────────────────────────────────────────
def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    with open(p) as f:
        return json.load(f)

def load_pipeline():
    return storage.load_pipeline()

def save_pipeline(pipeline):
    storage.save_pipeline(pipeline)

def get_company(pipeline, name):
    return next((c for c in pipeline if c["company"].lower() == name.lower()), None)

def upsert_company(pipeline, company_data):
    for i, c in enumerate(pipeline):
        if c["company"].lower() == company_data["company"].lower():
            pipeline[i] = {**c, **company_data}
            return pipeline
    pipeline.append(company_data)
    return pipeline

# ── AI helpers ────────────────────────────────────────────────────────────────
def research_company(company_name: str, icp: dict) -> dict:
    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Web research
    results = tavily.search(
        query=f"{company_name} field service software products customers target market",
        max_results=5,
        search_depth="advanced",
    )
    web_context = "\n\n".join([
        f"Source: {r['url']}\n{r['content']}"
        for r in results.get("results", [])
    ])

    prompt = f"""You are a sponsorship sales analyst for Field Service East (Orlando, Aug 10-12, 2025).

EVENT BUYER PROFILE:
- {icp['buyer_count']} registered buyers, {icp['senior_buyer_pct']}% VP/Director/SVP level
- Industries: Industrial/Manufacturing Equipment (41), Medical/Life Sciences (30), Tech/IT (17), Utilities (13)
- Top companies attending: {', '.join(icp['top_companies'][:10])}
- Top titles: {', '.join(icp['top_titles'][:8])}
- Existing sponsors: {', '.join(set(icp['existing_sponsors']))}

WEB RESEARCH ON {company_name}:
{web_context}

Based on this research, analyze {company_name} as a potential sponsor.

Return ONLY valid JSON:
{{
  "company": "{company_name}",
  "what_they_do": "<1-2 sentence plain English description>",
  "who_they_sell_to": "<their target buyer persona>",
  "score": <0-100>,
  "tier": "<A|B|C>",
  "fit_reason": "<2-3 sentences on why they fit this audience>",
  "pitch_angle": "<the ONE strongest reason they should sponsor — specific to our attendee list>",
  "risk": "<one sentence on potential objection>",
  "status": "researched"
}}
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def generate_emails(company_data: dict, contact_name: str, contact_title: str, icp: dict) -> list:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Build competitor context if available
    vs_sponsor = company_data.get("vs_sponsor", "")
    competitor_line = f"- Their competitors already sponsoring this event: {vs_sponsor}" if vs_sponsor else ""

    # Outreach note from the prospect list
    outreach_note = company_data.get("outreach_note", "")
    outreach_line = f"- Internal outreach note: {outreach_note}" if outreach_note else ""

    # Category context
    category = company_data.get("category", "")
    category_line = f"- Their market category: {category}" if category else ""

    prompt = f"""You are a senior sponsorship sales rep for Field Service East (Orlando, Aug 10-12, 2025).

EVENT AUDIENCE:
- {icp['buyer_count']} registered buyers, {icp['senior_buyer_pct']}% VP/Director/SVP level
- Top attending companies: {', '.join(icp['top_companies'][:12])}
- Top titles: {', '.join(icp['top_titles'][:10])}
- Already sponsoring: {', '.join(set(icp['existing_sponsors']))}

TARGET COMPANY INTEL:
- Name: {company_data['company']}
- What they do: {company_data.get('what_they_do', '')}
- Who they sell to: {company_data.get('who_they_sell_to', company_data.get('what_they_do', ''))}
- Best pitch angle: {company_data.get('pitch_angle', company_data.get('outreach_note', ''))}
{competitor_line}
{outreach_line}
{category_line}

CONTACT: {contact_name}, {contact_title}

Write a 3-touch cold email sequence to sell them a sponsorship.

Rules:
- Email 1: Lead with ONE specific audience insight most relevant to them. Under 150 words. Curiosity only, no hard pitch.
- Email 2 (Day 4): Connect their product to specific buyer titles/companies attending. If their competitors are sponsoring, mention it as social proof — not as a threat. Under 175 words.
- Email 3 (Day 9): Soft close, limited spots, reference existing sponsors as validation. Under 100 words.
- Tone: Direct, peer-to-peer, confident. No fluff, no corporate speak.
- Never use: "I hope this email finds you well", "synergy", "leverage", "cutting-edge", "robust", "game-changing"
- Always sign off: Ryan Casale, Field Service East

Return ONLY valid JSON:
[
  {{"touch": 1, "send_day": "Day 1", "subject": "...", "body": "..."}},
  {{"touch": 2, "send_day": "Day 4", "subject": "...", "body": "..."}},
  {{"touch": 3, "send_day": "Day 9", "subject": "...", "body": "..."}}
]
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ── Sidebar ───────────────────────────────────────────────────────────────────
icp = load_icp()
pipeline = load_pipeline()

with st.sidebar:
    st.image("https://img.icons8.com/emoji/96/lightning-emoji.png", width=48)
    st.title("FSE SDR Agent")
    st.caption("Field Service East · Orlando · Aug 10-12")
    st.divider()

    if icp:
        st.metric("Registered Buyers", icp["buyer_count"])
        st.metric("Senior (VP+/Director)", f"{icp['senior_buyer_pct']}%")
        st.metric("Companies in Pipeline", len(pipeline))
        approved = len([c for c in pipeline if c.get("status") == "approved"])
        st.metric("Emails Approved", approved)
    else:
        st.warning("Run icp_profile.py first")

    st.divider()
    # Radar badge
    radar_finds = load_json("radar_finds.json", [])
    unreviewed = [c for c in radar_finds if not c.get("reviewed")]
    if unreviewed:
        st.error(f"📡 {len(unreviewed)} new radar finds waiting!")
    else:
        st.caption("📡 Radar: no new finds")

    st.divider()
    # Storage status
    if storage.github_configured():
        st.success("💾 Saving to GitHub (persistent)")
        if st.button("🔄 Refresh data"):
            storage.refresh_cache()
            st.rerun()
    elif storage.gsheets_configured():
        st.success("💾 Saving to Google Sheets")
        if st.button("🔄 Refresh data"):
            storage.refresh_cache()
            st.rerun()
    else:
        st.warning("💾 Local storage only\n(edits reset on reboot)")

    # Rebuild ICP from an uploaded attendee CSV (persists to storage)
    with st.expander("⚙️ Rebuild ICP"):
        st.caption("Upload your attendee registration CSV to regenerate the buyer profile.")
        icp_csv = st.file_uploader("Attendee CSV", type="csv", key="icp_csv")
        if icp_csv and st.button("Rebuild ICP from CSV"):
            import tempfile, os
            from icp_profile import build_icp
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
                tmp.write(icp_csv.read())
                tmp_path = tmp.name
            try:
                new_icp = build_icp(tmp_path)
                storage.save_icp(new_icp)
                st.success(f"ICP rebuilt — {new_icp['buyer_count']} buyers.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")
            finally:
                os.unlink(tmp_path)

    st.divider()
    # Outlook status
    if outlook.is_configured():
        if outlook.is_authenticated():
            profile = outlook.get_profile()
            name = profile.get("displayName", "") if profile else ""
            st.success(f"📧 Outlook: {name or 'Connected'}")
        else:
            st.warning("📧 Outlook: needs auth")
    else:
        st.caption("📧 Outlook: awaiting Azure setup")

    st.divider()
    # Hot leads badge
    hot = [c for c in pipeline if c.get("priority") == "hot" and c.get("status") not in ("closed_won","closed_lost")]
    replied = [c for c in pipeline if c.get("status") == "replied"]
    if replied:
        st.error(f"🔥 {len(replied)} replied — follow up!")
    if hot:
        st.warning(f"⚡ {len(hot)} hot prospects")

    st.divider()
    st.caption("Sales stages")
    st.markdown("🔵 Researched · 📞 Contacted · 💬 Replied · 📅 Meeting · 📄 Contract · ✅ Won · ❌ Lost")

# ── Helpers: activity log & CRM ───────────────────────────────────────────────
from datetime import date, datetime

STATUSES = [
    "researched", "contacted", "replied",
    "meeting_booked", "contract_out", "closed_won", "closed_lost",
]
STATUS_LABELS = {
    "researched":    "🔵 Researched",
    "contacted":     "📞 Contacted",
    "replied":       "💬 Replied",
    "meeting_booked":"📅 Meeting Booked",
    "contract_out":  "📄 Contract Out",
    "closed_won":    "✅ Closed Won",
    "closed_lost":   "❌ Closed Lost",
    # legacy values
    "contact_found": "📞 Contacted",
    "approved":      "📞 Contacted",
    "sent":          "📞 Contacted",
    "skipped":       "🔵 Researched",
}
PRIORITY_LABELS = {"hot": "🔥 Hot", "medium": "⚡ Medium", "cold": "🧊 Cold"}

def log_activity(company: dict, activity_type: str, **kwargs) -> dict:
    """Append an activity entry to company['activity_log']."""
    if "activity_log" not in company:
        company["activity_log"] = []
    entry = {
        "type": activity_type,
        "date": date.today().isoformat(),
        "source": "manual",
        **kwargs,
    }
    company["activity_log"].append(entry)
    return company

def days_since_last_activity(company: dict) -> int | None:
    log = company.get("activity_log", [])
    if not log:
        return None
    last = max(log, key=lambda x: x.get("date",""))
    try:
        delta = date.today() - date.fromisoformat(last["date"])
        return delta.days
    except Exception:
        return None

def render_activity_log(company: dict, key_prefix: str):
    """Render timeline + manual log controls for a company."""
    log = sorted(company.get("activity_log", []), key=lambda x: x.get("date",""), reverse=True)

    icons = {
        "email_sent":       "📤",
        "reply_received":   "💬",
        "call":             "📞",
        "note":             "📝",
        "meeting_booked":   "📅",
        "contract_sent":    "📄",
        "status_change":    "🔄",
    }

    if log:
        st.markdown("**Activity Log**")
        for entry in log:
            icon = icons.get(entry["type"], "•")
            date_str = entry.get("date","")
            src = "🔗" if entry.get("source") == "outlook" else ""
            label = entry["type"].replace("_"," ").title()
            detail = entry.get("subject") or entry.get("note") or entry.get("preview","")
            st.markdown(f"{icon} **{label}** {src} · {date_str}")
            if detail:
                st.caption(f"  {detail[:120]}")
    else:
        st.caption("No activity logged yet.")

    st.markdown("**Log Activity**")
    log_cols = st.columns(4)
    if log_cols[0].button("📤 Email Sent", key=f"{key_prefix}_log_sent"):
        touch_opt = st.session_state.get(f"{key_prefix}_touch", 1)
        company = log_activity(company, "email_sent", touch=touch_opt, subject=f"Touch {touch_opt}")
        pipeline_local = load_pipeline()
        pipeline_local = upsert_company(pipeline_local, company)
        if company.get("status") in ("researched",):
            company["status"] = "contacted"
        save_pipeline(pipeline_local)
        st.rerun()
    if log_cols[1].button("💬 Reply In", key=f"{key_prefix}_log_reply"):
        company = log_activity(company, "reply_received")
        company["status"] = "replied"
        pipeline_local = load_pipeline()
        pipeline_local = upsert_company(pipeline_local, company)
        save_pipeline(pipeline_local)
        st.rerun()
    if log_cols[2].button("📅 Mtg Booked", key=f"{key_prefix}_log_mtg"):
        company = log_activity(company, "meeting_booked")
        company["status"] = "meeting_booked"
        pipeline_local = load_pipeline()
        pipeline_local = upsert_company(pipeline_local, company)
        save_pipeline(pipeline_local)
        st.rerun()
    if log_cols[3].button("📞 Call", key=f"{key_prefix}_log_call"):
        company = log_activity(company, "call")
        pipeline_local = load_pipeline()
        pipeline_local = upsert_company(pipeline_local, company)
        save_pipeline(pipeline_local)
        st.rerun()

    note_text = st.text_input("Add a note", key=f"{key_prefix}_note_input", placeholder="e.g. Left voicemail, asked about budget...")
    if st.button("📝 Save Note", key=f"{key_prefix}_save_note") and note_text:
        company = log_activity(company, "note", note=note_text)
        pipeline_local = load_pipeline()
        pipeline_local = upsert_company(pipeline_local, company)
        save_pipeline(pipeline_local)
        st.rerun()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🔍 Research", "📋 Pipeline", "✉️ Outreach Queue",
    "📡 Radar", "📥 Import", "🏆 Funnel", "📬 Outlook",
])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — RESEARCH
# ════════════════════════════════════════════════════════════════════════════
with tab1:  # Research
    st.header("Research a Company")
    st.caption("Enter any company name — the agent will research them online, score their fit, and explain why they should sponsor.")

    col1, col2 = st.columns([3, 1])
    with col1:
        company_input = st.text_input("Company name", placeholder="e.g. ServiceMax, Aquant, TeamViewer...")
    with col2:
        st.write("")
        st.write("")
        research_btn = st.button("🔍 Research", type="primary", use_container_width=True)

    if research_btn and company_input:
        if not icp:
            st.error("Run icp_profile.py first to generate icp_summary.json")
        else:
            with st.spinner(f"Researching {company_input}..."):
                try:
                    result = research_company(company_input, icp)

                    # Score color
                    score = result.get("score", 0)
                    tier = result.get("tier", "C")
                    score_color = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"

                    st.divider()
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric("Fit Score", f"{score}/100")
                    col_b.metric("Tier", f"{score_color} Tier {tier}")
                    col_c.metric("Status", "Researched")

                    st.subheader(result["company"])
                    st.write(f"**What they do:** {result.get('what_they_do','')}")
                    st.write(f"**Who they sell to:** {result.get('who_they_sell_to','')}")

                    st.info(f"**Why they fit:** {result.get('fit_reason','')}")
                    st.success(f"**Your pitch angle:** {result.get('pitch_angle','')}")
                    st.warning(f"**Watch out for:** {result.get('risk','')}")

                    # Add to pipeline
                    st.divider()
                    if st.button("➕ Add to Pipeline", type="primary"):
                        pipeline = upsert_company(pipeline, result)
                        save_pipeline(pipeline)
                        st.success(f"✅ {result['company']} added to your pipeline!")
                        st.rerun()

                    # Store in session for re-use
                    st.session_state["last_research"] = result

                except Exception as e:
                    st.error(f"Error: {e}")

    elif "last_research" in st.session_state:
        r = st.session_state["last_research"]
        st.info(f"Last researched: **{r['company']}** — Score {r['score']}/100")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — PIPELINE
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    st.header("My Sponsor Pipeline")

    pipeline = load_pipeline()

    if not pipeline:
        st.info("No companies yet — research one in the 🔍 tab to get started.")
    else:
        # Filters
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        status_filter = col_f1.selectbox("Sales stage", ["All"] + STATUSES)
        priority_filter = col_f2.selectbox("Priority", ["All", "hot", "medium", "cold"])
        tier_filter = col_f3.selectbox("AI tier", ["All", "A", "B", "C"])
        categories = sorted(set(c.get("category","") for c in pipeline if c.get("category")))
        cat_filter = col_f4.selectbox("Category", ["All"] + categories)

        filtered = pipeline
        if status_filter != "All":
            filtered = [c for c in filtered if c.get("status") == status_filter]
        if priority_filter != "All":
            filtered = [c for c in filtered if c.get("priority") == priority_filter]
        if tier_filter != "All":
            filtered = [c for c in filtered if str(c.get("tier","")) == tier_filter]
        if cat_filter != "All":
            filtered = [c for c in filtered if c.get("category","") == cat_filter]

        st.caption(f"Showing {len(filtered)} of {len(pipeline)} companies")
        # Sort: hot first, then by score
        priority_order = {"hot": 0, "medium": 1, "cold": 2, None: 3, "": 3}
        filtered_sorted = sorted(filtered, key=lambda x: (priority_order.get(x.get("priority"), 3), -x.get("score", 0)))

        for idx, company in enumerate(filtered_sorted):
            score = company.get("score", 0)
            tier = company.get("tier", "?")
            status = company.get("status", "researched")
            priority = company.get("priority", "")
            score_color = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
            status_label = STATUS_LABELS.get(status, status.replace("_"," ").title())
            priority_label = PRIORITY_LABELS.get(priority, "")
            days = days_since_last_activity(company)
            days_str = f"· {days}d ago" if days is not None else ""

            header = f"{score_color} **{company['company']}** — {score}/100 · {status_label}"
            if priority_label:
                header += f" · {priority_label}"
            if days_str:
                header += f" {days_str}"

            with st.expander(header):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**What they do:** {company.get('what_they_do','—')}")
                    st.write(f"**Who they sell to:** {company.get('who_they_sell_to', company.get('what_they_do','—'))}")
                    if company.get("fit_reason"):
                        st.write(f"**Fit reason:** {company.get('fit_reason')}")
                    if company.get("hq"):
                        st.write(f"**HQ:** {company.get('hq')}")
                with col2:
                    if company.get("pitch_angle") or company.get("outreach_note"):
                        st.info(f"**Pitch angle:** {company.get('pitch_angle', company.get('outreach_note','—'))}")
                    if company.get("vs_sponsor"):
                        st.warning(f"**Competitors already sponsoring:** {company.get('vs_sponsor')}")
                    if company.get("risk"):
                        st.error(f"**Watch out for:** {company.get('risk')}")

                st.divider()
                # Priority + stage controls
                ctrl1, ctrl2, ctrl3 = st.columns(3)
                new_priority = ctrl1.selectbox(
                    "Priority", ["hot","medium","cold"],
                    index=["hot","medium","cold"].index(company.get("priority","cold")) if company.get("priority") in ["hot","medium","cold"] else 2,
                    key=f"pri_{idx}",
                )
                new_status = ctrl2.selectbox(
                    "Sales stage", STATUSES,
                    index=STATUSES.index(status) if status in STATUSES else 0,
                    key=f"stage_{idx}",
                )
                if ctrl3.button("💾 Save Stage", key=f"savestage_{idx}"):
                    old_status = company.get("status","")
                    company["priority"] = new_priority
                    company["status"] = new_status
                    if old_status != new_status:
                        company = log_activity(company, "status_change", note=f"{old_status} → {new_status}")
                    pipeline = upsert_company(pipeline, company)
                    save_pipeline(pipeline)
                    st.success("Saved!")
                    st.rerun()

                st.divider()
                # Contact info
                st.write("**Contact Details**")
                c1, c2, c3 = st.columns(3)
                contact_name = c1.text_input("Contact name", value=company.get("contact_name",""), key=f"cn_{idx}")
                contact_title = c2.text_input("Title", value=company.get("contact_title",""), key=f"ct_{idx}")
                contact_email = c3.text_input("Email", value=company.get("contact_email",""), key=f"ce_{idx}")

                col_a, col_b, col_c = st.columns(3)
                if col_a.button("💾 Save Contact", key=f"save_{idx}"):
                    company["contact_name"] = contact_name
                    company["contact_title"] = contact_title
                    company["contact_email"] = contact_email
                    if company.get("status") == "researched":
                        company["status"] = "contacted"
                    pipeline = upsert_company(pipeline, company)
                    save_pipeline(pipeline)
                    st.success("Contact saved!")
                    st.rerun()

                if col_b.button("✉️ Generate Emails", key=f"gen_{idx}"):
                    if not contact_name:
                        st.warning("Add a contact name first")
                    else:
                        with st.spinner("Writing personalized emails..."):
                            emails = generate_emails(company, contact_name, contact_title, icp)
                            company["emails"] = emails
                            if company.get("status") == "researched":
                                company["status"] = "contacted"
                            pipeline = upsert_company(pipeline, company)
                            save_pipeline(pipeline)
                            st.success("Emails generated — review them in ✉️ Outreach Queue")
                            st.rerun()

                if col_c.button("🗑️ Remove", key=f"del_{idx}"):
                    pipeline = [c for c in pipeline if c["company"] != company["company"]]
                    save_pipeline(pipeline)
                    st.rerun()

                st.divider()
                render_activity_log(company, key_prefix=f"pl_{idx}")

        st.divider()
        if st.button("📥 Export Pipeline to CSV"):
            rows = []
            for c in pipeline:
                rows.append({
                    "Company": c.get("company",""),
                    "Score": c.get("score",""),
                    "Tier": c.get("tier",""),
                    "Status": c.get("status",""),
                    "Contact Name": c.get("contact_name",""),
                    "Contact Title": c.get("contact_title",""),
                    "Contact Email": c.get("contact_email",""),
                    "What They Do": c.get("what_they_do",""),
                    "Pitch Angle": c.get("pitch_angle",""),
                })
            with open("pipeline_export.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            st.success("Saved to pipeline_export.csv")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — OUTREACH QUEUE
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    st.header("Outreach Queue")
    st.caption("Review and approve email sequences before anything gets sent.")

    pipeline = load_pipeline()
    companies_with_emails = [c for c in pipeline if c.get("emails")]

    if not companies_with_emails:
        st.info("No emails drafted yet. Go to 📋 Pipeline, add a contact, and click 'Generate Emails'.")
    else:
        for company in companies_with_emails:
            status = company.get("status", "")
            status_icon = "✅" if status == "approved" else "🟡"

            with st.expander(f"{status_icon} **{company['company']}** · {company.get('contact_name','No contact')} · {status.replace('_',' ').title()}"):
                for email in company.get("emails", []):
                    st.markdown(f"#### Touch {email['touch']} — {email['send_day']}")
                    st.markdown(f"**Subject:** {email['subject']}")
                    st.text_area(
                        "Body",
                        value=email["body"],
                        height=180,
                        key=f"email_{company['company']}_{email['touch']}",
                    )
                    st.divider()

                col1, col2, col3 = st.columns(3)
                if col1.button("✅ Approve Sequence", key=f"approve_{company['company']}", type="primary"):
                    company["status"] = "approved"
                    pipeline = upsert_company(pipeline, company)
                    save_pipeline(pipeline)
                    st.success(f"✅ {company['company']} approved! Ready to load into Tiga.")
                    st.rerun()

                if col2.button("🔄 Regenerate", key=f"regen_{company['company']}"):
                    with st.spinner("Rewriting..."):
                        emails = generate_emails(
                            company,
                            company.get("contact_name","[First Name]"),
                            company.get("contact_title",""),
                            icp
                        )
                        company["emails"] = emails
                        pipeline = upsert_company(pipeline, company)
                        save_pipeline(pipeline)
                        st.rerun()

                if col3.button("⏭️ Skip", key=f"skip_{company['company']}"):
                    company["status"] = "skipped"
                    pipeline = upsert_company(pipeline, company)
                    save_pipeline(pipeline)
                    st.rerun()

        # Export approved to Tiga-ready CSV
        approved = [c for c in pipeline if c.get("status") == "approved"]
        if approved:
            st.divider()
            st.subheader(f"✅ {len(approved)} sequences approved")
            if st.button("📤 Export Approved to Tiga CSV", type="primary"):
                rows = []
                for c in approved:
                    emails = c.get("emails", [{},{},{}])
                    rows.append({
                        "First Name": c.get("contact_name","").split(" ")[0],
                        "Last Name": " ".join(c.get("contact_name","").split(" ")[1:]),
                        "Email": c.get("contact_email",""),
                        "Job Title": c.get("contact_title",""),
                        "Company": c.get("company",""),
                        "Email 1 Subject": emails[0].get("subject","") if len(emails) > 0 else "",
                        "Email 1 Body": emails[0].get("body","") if len(emails) > 0 else "",
                        "Email 2 Subject": emails[1].get("subject","") if len(emails) > 1 else "",
                        "Email 2 Body": emails[1].get("body","") if len(emails) > 1 else "",
                        "Email 3 Subject": emails[2].get("subject","") if len(emails) > 2 else "",
                        "Email 3 Body": emails[2].get("body","") if len(emails) > 2 else "",
                    })
                with open("tiga_import.csv", "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                st.success("✅ Saved to tiga_import.csv — ready to import into Tiga!")


# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — RADAR
# ════════════════════════════════════════════════════════════════════════════
with tab4:
    st.header("📡 Prospecting Radar")
    st.caption("New companies found automatically based on event signals, press releases, and competitor tracking. Review and approve before they hit your pipeline.")

    RADAR_FILE = "radar_finds.json"
    radar_finds = load_json(RADAR_FILE, [])
    unreviewed = [c for c in radar_finds if not c.get("reviewed")]
    reviewed = [c for c in radar_finds if c.get("reviewed")]

    # Manual run button
    col_r1, col_r2 = st.columns([2,1])
    col_r1.info(f"**{len(unreviewed)} new companies** waiting for review · {len(reviewed)} previously reviewed")
    if col_r2.button("🔍 Run Radar Now", type="primary"):
        with st.spinner("Searching for new sponsor targets... (this takes ~2 minutes)"):
            try:
                import radar as radar_module
                importlib.reload(radar_module)
                finds = radar_module.run_radar()
                st.success(f"Found {len(finds)} new companies!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    st.divider()

    if not unreviewed:
        st.success("✅ All caught up — no new companies to review.")
        st.caption("The radar runs every morning automatically. Check back tomorrow for new finds.")
    else:
        st.subheader(f"Review New Finds ({len(unreviewed)})")

        for ridx, company in enumerate(unreviewed):
            score = company.get("score", 0)
            tier = company.get("tier", "?")
            score_color = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
            signal = company.get("signal", "")

            with st.expander(f"{score_color} **{company['company']}** — {score}/100 · Tier {tier} · 📍 {signal}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**What they do:** {company.get('what_they_do','—')}")
                    st.write(f"**Category:** {company.get('category','—')}")
                    st.write(f"**Found:** {company.get('found_date','—')}")
                    if company.get("source_url"):
                        st.write(f"**Source:** [{company['source_url'][:60]}...]({company['source_url']})")
                with col2:
                    st.info(f"**Pitch angle:** {company.get('pitch_angle','—')}")
                    st.write(f"**Fit reason:** {company.get('fit_reason','—')}")

                col_a, col_b = st.columns(2)
                if col_a.button("✅ Add to Pipeline", key=f"radar_add_{ridx}", type="primary"):
                    company["reviewed"] = True
                    company["status"] = "researched"
                    pipeline = upsert_company(pipeline, company)
                    save_pipeline(pipeline)
                    # Update radar file
                    for rc in radar_finds:
                        if rc["company"] == company["company"]:
                            rc["reviewed"] = True
                    with open(RADAR_FILE, "w") as f:
                        json.dump(radar_finds, f, indent=2)
                    st.success(f"✅ {company['company']} added to pipeline!")
                    st.rerun()

                if col_b.button("⏭️ Dismiss", key=f"radar_skip_{ridx}"):
                    for rc in radar_finds:
                        if rc["company"] == company["company"]:
                            rc["reviewed"] = True
                            rc["dismissed"] = True
                    with open(RADAR_FILE, "w") as f:
                        json.dump(radar_finds, f, indent=2)
                    st.rerun()

    # Previously reviewed
    if reviewed:
        with st.expander(f"Previously reviewed ({len(reviewed)})"):
            for c in reviewed:
                dismissed = c.get("dismissed", False)
                icon = "⏭️" if dismissed else "✅"
                st.write(f"{icon} {c['company']} — {c.get('signal','')}")


# ════════════════════════════════════════════════════════════════════════════
# TAB 5 — IMPORT
# ════════════════════════════════════════════════════════════════════════════
with tab5:
    st.header("📥 Import Companies")
    st.caption("Upload a CSV from LinkedIn Sales Navigator, Seamless.AI, or any spreadsheet. The agent scores each company and adds them to your pipeline.")

    # ── Format guide ──
    with st.expander("📋 How to export from LinkedIn Sales Navigator"):
        st.markdown("""
**LinkedIn Sales Navigator:**
1. Run your search (filter by industry, company size, title)
2. Click **Export** → download CSV
3. Upload it here — the agent reads: Company, Industry, Employee Count, Website

**Seamless.AI:**
1. Run a company search
2. Click **Export to CSV**
3. Upload here

**Any spreadsheet:**
Just make sure it has at least a **Company Name** column.
The agent will figure out the rest.
        """)

    st.divider()

    uploaded_file = st.file_uploader(
        "Drop your CSV here",
        type=["csv"],
        help="CSV from LinkedIn Sales Nav, Seamless.AI, or any spreadsheet with company names"
    )

    if uploaded_file:
        import io
        import pandas as pd

        df = pd.read_csv(uploaded_file, encoding="latin1")
        st.success(f"✅ Loaded {len(df)} rows · {len(df.columns)} columns")

        # Show preview
        st.subheader("Preview")
        st.dataframe(df.head(5), use_container_width=True)

        # Column mapping
        st.subheader("Map your columns")
        st.caption("Tell the agent which column has the company name, and optionally more context.")
        cols = ["(none)"] + list(df.columns)

        col_m1, col_m2, col_m3 = st.columns(3)
        company_col = col_m1.selectbox("Company Name *", [c for c in cols if c != "(none)"], index=0)
        description_col = col_m2.selectbox("Description / What they do", cols, index=0)
        contact_name_col = col_m3.selectbox("Contact Name (optional)", cols, index=0)

        col_m4, col_m5, col_m6 = st.columns(3)
        contact_title_col = col_m4.selectbox("Contact Title (optional)", cols, index=0)
        contact_email_col = col_m5.selectbox("Contact Email (optional)", cols, index=0)
        industry_col = col_m6.selectbox("Industry (optional)", cols, index=0)

        st.divider()

        # Filter out already-in-pipeline companies
        pipeline = load_pipeline()
        existing = set(c["company"].lower() for c in pipeline)
        new_rows = df[~df[company_col].str.lower().isin(existing)]
        already_in = len(df) - len(new_rows)

        st.info(f"**{len(new_rows)} new companies** to import · {already_in} already in your pipeline")

        if len(new_rows) == 0:
            st.warning("All companies from this file are already in your pipeline.")
        else:
            col_opt1, col_opt2 = st.columns(2)
            score_them = col_opt1.checkbox("Score each company with AI", value=True,
                help="Uses Claude to score sponsor fit. Takes ~1-2 min per 10 companies.")
            limit = col_opt2.number_input("Max companies to import", min_value=1,
                max_value=len(new_rows), value=min(50, len(new_rows)))

            if st.button("🚀 Import to Pipeline", type="primary"):
                new_rows = new_rows.head(limit)
                progress = st.progress(0)
                status = st.empty()
                added = 0
                errors = 0

                for i, (_, row) in enumerate(new_rows.iterrows()):
                    company_name = str(row[company_col]).strip()
                    if not company_name or company_name.lower() == "nan":
                        continue

                    status.write(f"Processing {company_name}... ({i+1}/{len(new_rows)})")

                    description = str(row[description_col]).strip() if description_col != "(none)" else ""
                    if description.lower() == "nan":
                        description = ""

                    industry = str(row[industry_col]).strip() if industry_col != "(none)" else ""
                    contact_name = str(row[contact_name_col]).strip() if contact_name_col != "(none)" else ""
                    contact_title = str(row[contact_title_col]).strip() if contact_title_col != "(none)" else ""
                    contact_email = str(row[contact_email_col]).strip() if contact_email_col != "(none)" else ""

                    if score_them and icp:
                        try:
                            result = research_company(company_name, icp)
                            result["source"] = "csv_import"
                            result["import_file"] = uploaded_file.name
                        except Exception as e:
                            # Fall back to basic entry if scoring fails
                            result = {
                                "company": company_name,
                                "what_they_do": description,
                                "category": industry,
                                "score": 70,
                                "tier": "B",
                                "fit_reason": "Imported — not yet scored",
                                "pitch_angle": "",
                                "status": "researched",
                                "source": "csv_import",
                            }
                    else:
                        result = {
                            "company": company_name,
                            "what_they_do": description,
                            "category": industry,
                            "score": 0,
                            "tier": "?",
                            "fit_reason": "Not scored yet — click Research to score",
                            "pitch_angle": "",
                            "status": "researched",
                            "source": "csv_import",
                        }

                    # Add contact info if provided
                    if contact_name and contact_name.lower() != "nan":
                        result["contact_name"] = contact_name
                        result["contact_title"] = contact_title
                        result["contact_email"] = contact_email
                        result["status"] = "contact_found"

                    pipeline = upsert_company(pipeline, result)
                    save_pipeline(pipeline)
                    added += 1
                    progress.progress((i + 1) / len(new_rows))

                status.empty()
                progress.empty()
                st.success(f"✅ Imported {added} companies into your pipeline!")
                if not score_them:
                    st.info("Go to 📋 Pipeline to research and score each company.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 6 — FUNNEL
# ════════════════════════════════════════════════════════════════════════════
with tab6:
    st.header("🏆 Sales Funnel")
    st.caption("Pipeline by sales stage and priority. Your CRM view.")

    pipeline = load_pipeline()

    if not pipeline:
        st.info("No companies yet — start in 🔍 Research.")
    else:
        # ── Summary metrics ──
        m_cols = st.columns(7)
        for i, s in enumerate(STATUSES):
            count = sum(1 for c in pipeline if c.get("status") == s)
            m_cols[i].metric(STATUS_LABELS[s].split(" ",1)[1], count)

        st.divider()

        # ── Priority breakdown ──
        st.subheader("By Priority")
        p_cols = st.columns(3)
        for col, (pkey, plabel) in zip(p_cols, PRIORITY_LABELS.items()):
            companies = [c for c in pipeline if c.get("priority") == pkey and c.get("status") not in ("closed_won","closed_lost")]
            with col:
                st.markdown(f"### {plabel} ({len(companies)})")
                for c in sorted(companies, key=lambda x: -x.get("score",0)):
                    score = c.get("score",0)
                    score_color = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
                    status_label = STATUS_LABELS.get(c.get("status",""), c.get("status",""))
                    days = days_since_last_activity(c)
                    days_str = f" · {days}d" if days is not None else ""
                    st.markdown(f"{score_color} **{c['company']}**")
                    st.caption(f"{status_label}{days_str}")
                    st.divider()

        st.divider()

        # ── Stage columns ──
        st.subheader("By Sales Stage")
        active_statuses = [s for s in STATUSES if s not in ("closed_won","closed_lost")]
        stage_cols = st.columns(len(active_statuses))
        for col, s in zip(stage_cols, active_statuses):
            companies = [c for c in pipeline if c.get("status") == s or (s == "researched" and c.get("status") not in STATUSES)]
            with col:
                st.markdown(f"**{STATUS_LABELS[s]}**")
                st.caption(f"{len(companies)} companies")
                for c in sorted(companies, key=lambda x: -x.get("score",0))[:8]:
                    priority = c.get("priority","")
                    badge = PRIORITY_LABELS.get(priority,"")
                    st.markdown(f"**{c['company']}** {badge}")

        st.divider()

        # ── Closed ──
        won = [c for c in pipeline if c.get("status") == "closed_won"]
        lost = [c for c in pipeline if c.get("status") == "closed_lost"]
        w_col, l_col = st.columns(2)
        with w_col:
            st.markdown(f"### ✅ Closed Won ({len(won)})")
            for c in won:
                st.markdown(f"**{c['company']}**")
        with l_col:
            st.markdown(f"### ❌ Closed Lost ({len(lost)})")
            for c in lost:
                st.markdown(f"**{c['company']}**")

        st.divider()

        # ── Activity feed ──
        st.subheader("Recent Activity")
        all_activities = []
        for c in pipeline:
            for entry in c.get("activity_log", []):
                all_activities.append({**entry, "_company": c["company"]})
        all_activities.sort(key=lambda x: x.get("date",""), reverse=True)

        if all_activities:
            for entry in all_activities[:20]:
                icons = {"email_sent":"📤","reply_received":"💬","call":"📞","note":"📝","meeting_booked":"📅","contract_sent":"📄","status_change":"🔄"}
                icon = icons.get(entry["type"],"•")
                detail = entry.get("subject") or entry.get("note") or entry.get("preview","")
                st.markdown(f"{icon} **{entry['_company']}** · {entry['type'].replace('_',' ').title()} · {entry.get('date','')}")
                if detail:
                    st.caption(f"  {detail[:100]}")
        else:
            st.info("No activity logged yet. Use the Pipeline tab to log sends, replies, and notes.")

# ════════════════════════════════════════════════════════════════════════════
# TAB 7 — OUTLOOK
# ════════════════════════════════════════════════════════════════════════════
with tab7:
    st.header("📬 Outlook Integration")

    if not outlook.is_configured():
        st.info(
            "**Waiting on Azure App Registration.**\n\n"
            "Once Gabe provides the credentials, add them to your `.env` file on Streamlit Cloud "
            "(Settings → Secrets) and this tab activates automatically.\n\n"
            "```\nAZURE_CLIENT_ID=...\nAZURE_CLIENT_SECRET=...\nAZURE_TENANT_ID=...\n```"
        )
        st.divider()
        st.subheader("What this will do once connected")
        st.markdown(
            "- **Reply detection** — flags when a prospect replies to your outreach\n"
            "- **Sent log** — shows which touches have been sent per company\n"
            "- **Send from here** — send approved sequences directly without going to Outlook\n"
            "- **Hot leads** — surfaces replies at the top so nothing slips through"
        )
        st.stop()

    if not outlook.is_authenticated():
        st.warning("Outlook is configured but needs one-time authorization.")
        auth_url = outlook.get_auth_url()
        st.markdown(f"[**Click here to authorize Outlook access →**]({auth_url})")
        st.caption("You'll be redirected back to the app. Paste the `code=` value from the URL below if it doesn't auto-complete.")
        code = st.text_input("Authorization code (from redirect URL)")
        if code and st.button("Complete Authorization", type="primary"):
            try:
                outlook.exchange_code_for_token(code)
                st.success("✅ Connected!")
                st.rerun()
            except Exception as e:
                st.error(f"Authorization failed: {e}")
        st.stop()

    profile = outlook.get_profile()
    st.success(f"Connected as **{profile.get('displayName', '')}** ({profile.get('mail', '')})")
    st.divider()

    pipeline = load_pipeline()
    prospect_emails = [c.get("contact_email", "") for c in pipeline if c.get("contact_email")]

    col1, col2 = st.columns(2)

    with col1:
        st.subheader(f"📥 Replies from Prospects")
        with st.spinner("Checking inbox..."):
            replies = outlook.get_recent_replies(prospect_emails)
        if replies:
            for msg in replies:
                sender = msg["from"]["emailAddress"]["address"]
                match = next((c for c in pipeline if c.get("contact_email","").lower() == sender.lower()), None)
                company_name = match["company"] if match else sender
                st.markdown(f"**{company_name}** · {msg['receivedDateTime'][:10]}")
                st.caption(f"Re: {msg['subject']}")
                st.caption(msg["bodyPreview"][:150])
                if match and st.button("Log Reply + Update Stage", key=f"reply_{msg['id'][:8]}"):
                    match = log_activity(match, "reply_received",
                                        subject=msg["subject"],
                                        preview=msg["bodyPreview"][:150],
                                        source="outlook")
                    match["status"] = "replied"
                    pipeline = upsert_company(pipeline, match)
                    save_pipeline(pipeline)
                    st.success("Logged and stage updated to Replied!")
                    st.rerun()
                st.divider()
        else:
            st.info("No replies from prospects in recent inbox.")

    with col2:
        st.subheader("📤 Sent to Prospects")
        with st.spinner("Checking sent items..."):
            sent = outlook.get_sent_to_prospects(prospect_emails)
        if sent:
            for msg in sent:
                to_addr = msg["toRecipients"][0]["emailAddress"]["address"] if msg.get("toRecipients") else ""
                match = next((c for c in pipeline if c.get("contact_email","").lower() == to_addr.lower()), None)
                company_name = match["company"] if match else to_addr
                st.markdown(f"**{company_name}**")
                st.caption(f"{msg['subject']} · {msg['sentDateTime'][:10]}")
                st.divider()
        else:
            st.info("No sent emails to prospects found.")

    st.divider()
    st.subheader("✉️ Send an Email")
    contacts_with_email = [c for c in pipeline if c.get("contact_email") and c.get("emails")]
    if not contacts_with_email:
        st.info("No contacts with both an email address and generated sequences yet.")
    else:
        options = {f"{c['company']} — {c.get('contact_name', c['contact_email'])}": c for c in contacts_with_email}
        selected_label = st.selectbox("Select contact", list(options.keys()))
        selected_company = options[selected_label]

        touch_num = st.selectbox("Which touch", ["Touch 1 (Day 1)", "Touch 2 (Day 4)", "Touch 3 (Day 9)"])
        touch_idx = int(touch_num[6]) - 1
        email_data = selected_company["emails"][touch_idx]

        subject = st.text_input("Subject", value=email_data["subject"])
        body = st.text_area("Body", value=email_data["body"], height=220)

        if st.button("📤 Send", type="primary"):
            success = outlook.send_email(selected_company["contact_email"], subject, body)
            if success:
                selected_company = log_activity(selected_company, "email_sent",
                                                touch=touch_idx + 1,
                                                subject=subject,
                                                source="outlook")
                if selected_company.get("status") == "researched":
                    selected_company["status"] = "contacted"
                pipeline = upsert_company(pipeline, selected_company)
                save_pipeline(pipeline)
                st.success(f"✅ Sent to {selected_company['contact_email']}")
                st.rerun()
            else:
                st.error("Send failed — check your Outlook connection.")
