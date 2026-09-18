"""
Pipeline data access and the vocabulary the whole app shares.

Everything that reads or writes a company record goes through here, so the
stage model stays consistent and no view invents its own status strings.
"""
import json
from datetime import date
from pathlib import Path

import streamlit as st

import storage

ROOT = Path(__file__).resolve().parent.parent

# ── Sales stages ──────────────────────────────────────────────────────────────
STATUSES = [
    "researched", "contacted", "replied",
    "meeting_booked", "contract_out", "closed_won", "closed_lost",
]
ACTIVE_STATUSES = [s for s in STATUSES if s not in ("closed_won", "closed_lost")]

STATUS_LABELS = {
    "researched": "Researched",
    "contacted": "Contacted",
    "replied": "Replied",
    "meeting_booked": "Meeting Booked",
    "contract_out": "Contract Out",
    "closed_won": "Closed Won",
    "closed_lost": "Closed Lost",
    # legacy values still present in older records
    "contact_found": "Contacted",
    "approved": "Contacted",
    "sent": "Contacted",
    "skipped": "Researched",
    "radar_find": "Researched",
}

LEGACY_STATUS_MAP = {
    "contact_found": "contacted",
    "approved": "contacted",
    "sent": "contacted",
    "skipped": "researched",
    "radar_find": "researched",
}

PRIORITIES = ["hot", "medium", "cold"]
PRIORITY_LABELS = {"hot": "Hot", "medium": "Medium", "cold": "Cold"}


def normalize_status(status: str) -> str:
    """Map legacy/odd status values onto the canonical stage list."""
    if status in STATUSES:
        return status
    return LEGACY_STATUS_MAP.get(status, "researched")


# ── Event context ─────────────────────────────────────────────────────────────
def event_id() -> str:
    return st.session_state.get("event_id", "field-service-east")


def event_cfg() -> dict:
    return st.session_state.get("event_cfg", {})


# ── Load / save ───────────────────────────────────────────────────────────────
def load_pipeline() -> list:
    return storage.load_pipeline(event_id=event_id())


def save_pipeline(pipeline: list):
    storage.save_pipeline(pipeline, event_id=event_id())


def load_icp() -> dict:
    return storage.load_icp(event_id=event_id()) or {}


def load_json(path, default):
    p = ROOT / path if not Path(path).is_absolute() else Path(path)
    if not p.exists():
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    p = ROOT / path if not Path(path).is_absolute() else Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(p)


def radar_file() -> str:
    """Radar finds are per event. The old sidebar read the bare
    radar_finds.json for every event, which showed FSE's finds while you were
    working B2B."""
    return f"{event_id()}_radar_finds.json"


def load_radar_finds() -> list:
    return load_json(radar_file(), [])


def save_radar_finds(finds: list):
    save_json(radar_file(), finds)


# ── Company helpers ───────────────────────────────────────────────────────────
def get_company(pipeline: list, name: str):
    return next(
        (c for c in pipeline if (c.get("company") or "").lower() == (name or "").lower()),
        None,
    )


def upsert_company(pipeline: list, company_data: dict) -> list:
    name = (company_data.get("company") or "").lower()
    for i, c in enumerate(pipeline):
        if (c.get("company") or "").lower() == name:
            pipeline[i] = {**c, **company_data}
            return pipeline
    pipeline.append(company_data)
    return pipeline


def remove_company(pipeline: list, name: str) -> list:
    return [c for c in pipeline if (c.get("company") or "") != name]


def get_contacts(company: dict) -> list:
    """Contacts list, migrating the legacy single-contact fields in memory."""
    contacts = company.get("contacts") or []
    if not contacts and (company.get("contact_name") or company.get("contact_email")):
        contacts = [{
            "name": company.get("contact_name", ""),
            "title": company.get("contact_title", ""),
            "email": company.get("contact_email", ""),
            "phone": "",
            "notes": "",
            "activity_log": [],
        }]
    return contacts


def primary_email(company: dict) -> str:
    """First usable email for a company, new structure or legacy field."""
    for c in get_contacts(company):
        if c.get("email"):
            return c["email"]
    return company.get("contact_email", "") or ""


def is_active(company: dict) -> bool:
    return normalize_status(company.get("status", "")) not in ("closed_won", "closed_lost")


def active_companies(pipeline: list) -> list:
    return [c for c in pipeline if is_active(c)]


def stage_counts(pipeline: list) -> dict:
    counts = {s: 0 for s in STATUSES}
    for c in pipeline:
        counts[normalize_status(c.get("status", ""))] += 1
    return counts


# ── Activity ──────────────────────────────────────────────────────────────────
ACTIVITY_LABELS = {
    "email_sent": "Email sent",
    "reply_received": "Reply received",
    "call": "Call",
    "note": "Note",
    "meeting_booked": "Meeting booked",
    "meeting": "Meeting",
    "contract_sent": "Contract sent",
    "status_change": "Stage change",
    "task": "Task",
}


def log_activity(company: dict, activity_type: str, **kwargs) -> dict:
    company.setdefault("activity_log", [])
    company["activity_log"].append({
        "type": activity_type,
        "date": date.today().isoformat(),
        "source": "manual",
        **kwargs,
    })
    return company


def log_contact_activity(contact: dict, atype: str, **kw):
    contact.setdefault("activity_log", [])
    contact["activity_log"].append({
        "type": atype,
        "date": date.today().isoformat(),
        "source": "manual",
        **kw,
    })


def days_since_last_activity(company: dict):
    log = company.get("activity_log", [])
    if not log:
        return None
    last = max(log, key=lambda x: x.get("date", ""))
    try:
        return (date.today() - date.fromisoformat(last["date"])).days
    except Exception:
        return None


def recent_activity(pipeline: list, limit: int = 20) -> list:
    out = []
    for c in pipeline:
        for entry in c.get("activity_log", []):
            out.append({**entry, "_company": c.get("company", "")})
    out.sort(key=lambda x: x.get("date", ""), reverse=True)
    return out[:limit]


# ── Persist a single company in one call ──────────────────────────────────────
def persist(company: dict):
    """Load fresh, upsert, save. Views should use this rather than juggling
    their own pipeline copies — that is how stale writes crept in before."""
    pipeline = load_pipeline()
    pipeline = upsert_company(pipeline, company)
    save_pipeline(pipeline)


def set_stage(company: dict, new_status: str, new_priority: str = None):
    old = company.get("status", "")
    if new_priority:
        company["priority"] = new_priority
    company["status"] = new_status
    if old != new_status:
        log_activity(company, "status_change", note=f"{old or 'new'} -> {new_status}")
    persist(company)
    return company


# ── Navigation ────────────────────────────────────────────────────────────────
def open_account(company_name: str):
    st.session_state["account_view"] = company_name
    st.rerun()


def close_account():
    st.session_state.pop("account_view", None)
    st.rerun()
