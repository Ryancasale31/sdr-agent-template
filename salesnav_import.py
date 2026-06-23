"""
Sales Navigator Import
Reads a Sales Nav accounts or leads/contacts CSV export, deduplicates against
pipeline using fuzzy matching, and enriches contacts via Tiga waterfall enrichment.

Usage (standalone):
    python salesnav_import.py accounts.csv           # account list → pipeline
    python salesnav_import.py leads.csv              # contacts → contacts.csv + Tiga enrich
    python salesnav_import.py leads.csv --no-enrich  # skip Tiga enrichment

Called from app.py as a module.
"""
import json
import csv
import os
import re
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

PIPELINE_FILE = "pipeline.json"
CONTACTS_FILE = "contacts.csv"
TIGA_API_KEY = os.getenv("TIGA_API_KEY", "")
TIGA_BASE = "https://app.tigalabs.com/api/v1"

# ── Sales Navigator column aliases ───────────────────────────────────────────
# Maps canonical field → possible Sales Nav column names (in priority order)
ACCOUNT_COL_MAP = {
    "company":     ["Account Name", "Company Name", "Company", "Name", "Organization Name"],
    "website":     ["Website", "Company Website", "Domain", "URL"],
    "industry":    ["Industry", "Company Industry", "Vertical"],
    "headcount":   ["Company Headcount", "Headcount", "Employees", "Employee Count", "Number of Employees", "# Employees"],
    "description": ["Description", "Summary", "About", "What they do"],
    "linkedin":    ["LinkedIn Company Profile URL", "LinkedIn URL", "Company LinkedIn URL"],
    "location":    ["Headquarters", "Location", "HQ", "City"],
}

CONTACT_COL_MAP = {
    "first_name":  ["First Name", "FirstName"],
    "last_name":   ["Last Name", "LastName"],
    "title":       ["Job Title", "Title", "Position", "Role"],
    "company":     ["Company", "Company Name", "Account Name", "Organization"],
    "email":       ["Email Address", "Email", "Work Email"],
    "phone":       ["Phone", "Phone Number", "Work Phone", "Mobile"],
    "linkedin":    ["LinkedIn Member Profile URL", "LinkedIn URL", "Profile URL"],
    "location":    ["Location", "City", "Geography"],
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path, default):
    if not Path(path).exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _normalize(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r'\b(inc|llc|ltd|corp|co|plc|gmbh|ag|bv|sa|sas|pty|pte)\b\.?', '', n)
    n = re.sub(r'\(.*?\)', '', n)
    n = re.sub(r'[^a-z0-9 ]', ' ', n)
    return re.sub(r'\s+', ' ', n).strip()


def is_duplicate(name: str, known: set) -> bool:
    STOP_WORDS = {"the", "a", "an", "of", "and", "for", "in", "at", "by", "to",
                  "inc", "llc", "ltd", "corp", "group", "co", "ai", "platform",
                  "solutions", "services", "systems", "technologies", "software"}
    n_raw = name.lower().strip()
    n = _normalize(name)
    if n_raw in known:
        return True
    if n in {_normalize(k) for k in known}:
        return True
    n_words = {w for w in n.split() if len(w) > 3 and w not in STOP_WORDS}
    for k in known:
        k_norm = _normalize(k)
        if len(k_norm) >= 6 and len(n) >= 6:
            if k_norm in n or n in k_norm:
                return True
        k_words = {w for w in k_norm.split() if len(w) > 3 and w not in STOP_WORDS}
        if len(n_words) >= 1 and len(k_words) >= 1:
            overlap = n_words & k_words
            smaller = min(len(n_words), len(k_words))
            if smaller > 0 and len(overlap) / smaller >= 0.7:
                return True
    return False


def get_pipeline_companies() -> set:
    pipeline = load_json(PIPELINE_FILE, [])
    return {c.get("company", "").lower() for c in pipeline if c.get("company")}


def resolve_col(headers: list, candidates: list) -> str | None:
    """Return first matching column name from candidates (case-insensitive)."""
    lower_headers = {h.lower(): h for h in headers}
    for candidate in candidates:
        if candidate.lower() in lower_headers:
            return lower_headers[candidate.lower()]
    return None


def detect_csv_type(headers: list) -> str:
    """Return 'accounts', 'contacts', or 'unknown'."""
    lower = [h.lower() for h in headers]
    contact_signals = {"first name", "firstname", "last name", "lastname",
                       "linkedin member profile url", "job title"}
    account_signals = {"account name", "company headcount", "linkedin company profile url",
                       "headquarters"}
    if any(s in lower for s in contact_signals):
        return "contacts"
    if any(s in lower for s in account_signals):
        return "accounts"
    # Fallback: if there's a "company" column but no name split, treat as accounts
    if "company" in lower or "company name" in lower:
        return "accounts"
    return "unknown"


def auto_map_columns(headers: list, col_map: dict) -> dict:
    """Return {canonical_field: actual_column_name} for all resolvable fields."""
    mapping = {}
    for field, candidates in col_map.items():
        col = resolve_col(headers, candidates)
        if col:
            mapping[field] = col
    return mapping


# ── Account import ────────────────────────────────────────────────────────────

def parse_accounts_csv(filepath: str, col_override: dict = None) -> tuple[list, list, int]:
    """
    Parse a Sales Nav accounts CSV.
    Returns (new_entries, skipped_names, total_rows).
    col_override: {canonical_field: actual_column_name} — overrides auto-detect.
    """
    with open(filepath, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return [], [], 0

    headers = list(rows[0].keys())
    mapping = auto_map_columns(headers, ACCOUNT_COL_MAP)
    if col_override:
        mapping.update(col_override)

    if "company" not in mapping:
        raise ValueError(f"Could not find a company name column. Columns found: {headers}")

    known = get_pipeline_companies()
    new_entries = []
    skipped = []

    for row in rows:
        name = row.get(mapping["company"], "").strip()
        if not name or name.lower() == "nan":
            continue

        if is_duplicate(name, known):
            skipped.append(name)
            continue

        website = row.get(mapping.get("website", ""), "").strip() if mapping.get("website") else ""
        industry = row.get(mapping.get("industry", ""), "").strip() if mapping.get("industry") else ""
        headcount = row.get(mapping.get("headcount", ""), "").strip() if mapping.get("headcount") else ""
        description = row.get(mapping.get("description", ""), "").strip() if mapping.get("description") else ""
        location = row.get(mapping.get("location", ""), "").strip() if mapping.get("location") else ""
        linkedin = row.get(mapping.get("linkedin", ""), "").strip() if mapping.get("linkedin") else ""

        entry = {
            "company": name,
            "category": industry or "Other",
            "what_they_do": description,
            "score": 0,
            "tier": "?",
            "priority": "medium",
            "status": "researched",
            "source": "salesnav_import",
            "import_date": datetime.now().strftime("%Y-%m-%d"),
            "website": website,
            "headcount": headcount,
            "location": location,
            "linkedin_url": linkedin,
            "fit_reason": "Imported from Sales Navigator — score with Research tab",
            "pitch_angle": "",
            "outreach_note": "",
            "contacts": [],
        }
        new_entries.append(entry)
        known.add(name.lower())

    return new_entries, skipped, len(rows)


def add_accounts_to_pipeline(entries: list) -> int:
    pipeline = load_json(PIPELINE_FILE, [])
    existing = {c["company"].lower() for c in pipeline}
    added = 0
    for entry in entries:
        if entry["company"].lower() not in existing:
            pipeline.append(entry)
            existing.add(entry["company"].lower())
            added += 1
    if added:
        pipeline.sort(key=lambda x: x.get("company", "").lower())
        save_json(PIPELINE_FILE, pipeline)
    return added


# ── Contact import ────────────────────────────────────────────────────────────

def parse_contacts_csv(filepath: str, col_override: dict = None) -> tuple[list, int]:
    """
    Parse a Sales Nav leads/contacts CSV.
    Returns (contacts, total_rows).
    """
    with open(filepath, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return [], 0

    headers = list(rows[0].keys())
    mapping = auto_map_columns(headers, CONTACT_COL_MAP)
    if col_override:
        mapping.update(col_override)

    contacts = []
    seen_emails = set()
    seen_names = set()

    for row in rows:
        first = row.get(mapping.get("first_name", ""), "").strip() if mapping.get("first_name") else ""
        last = row.get(mapping.get("last_name", ""), "").strip() if mapping.get("last_name") else ""
        name = f"{first} {last}".strip()
        if not name or name.lower() == "nan":
            continue

        company = row.get(mapping.get("company", ""), "").strip() if mapping.get("company") else ""
        title = row.get(mapping.get("title", ""), "").strip() if mapping.get("title") else ""
        email = row.get(mapping.get("email", ""), "").strip() if mapping.get("email") else ""
        phone = row.get(mapping.get("phone", ""), "").strip() if mapping.get("phone") else ""
        linkedin = row.get(mapping.get("linkedin", ""), "").strip() if mapping.get("linkedin") else ""
        location = row.get(mapping.get("location", ""), "").strip() if mapping.get("location") else ""

        # Dedup by email or name+company
        dedup_key = email.lower() if email and email.lower() not in ("", "nan") else f"{name.lower()}|{company.lower()}"
        if dedup_key in seen_emails or dedup_key in seen_names:
            continue
        if email:
            seen_emails.add(email.lower())
        seen_names.add(f"{name.lower()}|{company.lower()}")

        contacts.append({
            "name": name,
            "first_name": first,
            "last_name": last,
            "title": title,
            "company": company,
            "email": email if email.lower() not in ("", "nan") else "",
            "phone": phone if phone.lower() not in ("", "nan") else "",
            "linkedin_url": linkedin,
            "location": location,
            "source": "salesnav_import",
            "import_date": datetime.now().strftime("%Y-%m-%d"),
        })

    return contacts, len(rows)


def save_contacts_csv(contacts: list, filepath: str = CONTACTS_FILE, append: bool = True):
    """Save/append contacts to contacts.csv."""
    fieldnames = ["name", "first_name", "last_name", "title", "company",
                  "email", "phone", "linkedin_url", "location", "source", "import_date"]
    file_exists = Path(filepath).exists()
    mode = "a" if append and file_exists else "w"

    # If appending, avoid duplicate rows
    existing_keys = set()
    if mode == "a" and file_exists:
        with open(filepath, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = row.get("email", "").lower() or f"{row.get('name','').lower()}|{row.get('company','').lower()}"
                existing_keys.add(key)

    new_contacts = []
    for c in contacts:
        key = c.get("email", "").lower() or f"{c.get('name','').lower()}|{c.get('company','').lower()}"
        if key not in existing_keys:
            new_contacts.append(c)
            existing_keys.add(key)

    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if mode == "w":
            writer.writeheader()
        writer.writerows(new_contacts)

    return len(new_contacts)


# ── Tiga waterfall enrichment ─────────────────────────────────────────────────

def _tiga_headers():
    return {"X-Tiga-Auth": TIGA_API_KEY, "Content-Type": "application/json"}


def _tiga_post(endpoint: str, payload: dict) -> dict:
    import requests
    resp = requests.post(f"{TIGA_BASE}{endpoint}", headers=_tiga_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _tiga_get(endpoint: str) -> dict:
    import requests
    resp = requests.get(f"{TIGA_BASE}{endpoint}", headers=_tiga_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def enrich_contact_tiga(contact: dict) -> dict:
    """
    Run Tiga waterfall enrichment on a single contact.
    Returns the contact dict with email/phone filled in if found.
    """
    if not TIGA_API_KEY:
        return contact

    if contact.get("email"):
        return contact  # Already has email

    payload = {
        "people": [{
            "first_name": contact.get("first_name", ""),
            "last_name": contact.get("last_name", ""),
            "company_name": contact.get("company", ""),
            "title": contact.get("title", ""),
            "linkedin_url": contact.get("linkedin_url", ""),
        }]
    }

    try:
        result = _tiga_post("/waterfall-enrich", payload)
        enriched = result.get("people", [{}])[0] if result.get("people") else {}
        if enriched.get("email"):
            contact["email"] = enriched["email"]
        if enriched.get("phone") and not contact.get("phone"):
            contact["phone"] = enriched["phone"]
        contact["enriched"] = True
    except Exception as e:
        contact["enrich_error"] = str(e)

    return contact


def enrich_contacts_batch(contacts: list, progress_cb=None) -> tuple[list, int]:
    """
    Enrich a list of contacts missing email via Tiga.
    progress_cb: optional callable(i, total, name) for progress updates.
    Returns (enriched_contacts, n_enriched).
    """
    needs_enrich = [c for c in contacts if not c.get("email")]
    n_enriched = 0

    for i, contact in enumerate(needs_enrich):
        if progress_cb:
            progress_cb(i, len(needs_enrich), contact.get("name", ""))
        enriched = enrich_contact_tiga(contact)
        if enriched.get("email"):
            n_enriched += 1
        # Be gentle with the API
        time.sleep(0.5)

    return contacts, n_enriched


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import Sales Navigator CSV into FSE pipeline")
    parser.add_argument("file", help="Path to Sales Nav CSV export")
    parser.add_argument("--type", choices=["accounts", "contacts", "auto"],
                        default="auto", help="CSV type (default: auto-detect)")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip Tiga waterfall enrichment for contacts")
    parser.add_argument("--out", default=CONTACTS_FILE,
                        help=f"Output contacts CSV (default: {CONTACTS_FILE})")
    args = parser.parse_args()

    filepath = args.file
    if not Path(filepath).exists():
        print(f"[!] File not found: {filepath}")
        sys.exit(1)

    # Detect type
    with open(filepath, encoding="utf-8-sig", errors="replace") as f:
        headers = list(csv.DictReader(f).fieldnames or [])
    csv_type = args.type if args.type != "auto" else detect_csv_type(headers)
    print(f"\n[Sales Nav Import] Detected type: {csv_type}")
    print(f"  File: {filepath}")

    if csv_type == "accounts":
        entries, skipped, total = parse_accounts_csv(filepath)
        print(f"  {total} rows → {len(entries)} new, {len(skipped)} already in pipeline")
        if entries:
            n = add_accounts_to_pipeline(entries)
            print(f"  ✅ Added {n} companies to pipeline.json")
            for e in entries:
                print(f"    + {e['company']}")
        else:
            print("  Nothing new to add.")

    elif csv_type == "contacts":
        contacts, total = parse_contacts_csv(filepath)
        print(f"  {total} rows → {len(contacts)} contacts parsed")
        missing_email = len([c for c in contacts if not c.get("email")])
        print(f"  {len(contacts) - missing_email} have email · {missing_email} need enrichment")

        if missing_email and not args.no_enrich:
            print(f"\n  Running Tiga waterfall enrichment on {missing_email} contacts...")
            def progress(i, total, name):
                print(f"    [{i+1}/{total}] {name}")
            contacts, n_enriched = enrich_contacts_batch(contacts, progress_cb=progress)
            print(f"  ✅ Enriched {n_enriched} contacts")

        n_saved = save_contacts_csv(contacts, filepath=args.out)
        print(f"\n  ✅ Saved {n_saved} contacts → {args.out}")

    else:
        print("[!] Could not auto-detect CSV type. Use --type accounts or --type contacts")
        print(f"    Columns found: {headers}")
        sys.exit(1)


if __name__ == "__main__":
    main()
