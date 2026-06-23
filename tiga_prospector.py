"""
FSE Prospector
Searches Seamless.ai using the FSE sponsor ICP keywords, then optionally
runs your Tiga signals to score/filter results, and returns qualified
companies ready for pipeline import.

Usage:
    python tiga_prospector.py                  # search + print results
    python tiga_prospector.py --auto-add       # add score >= 70 to pipeline
    python tiga_prospector.py --list-signals   # list your Tiga signals
    python tiga_prospector.py --signals ID1 ID2 --auto-add  # search + score + add

Called from app.py as a module.
"""
import json
import os
import re
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TIGA_API_KEY = os.getenv("TIGA_API_KEY", "")
TIGA_BASE = "https://app.tigalabs.com/api/v1"
SEAMLESS_API_KEY = os.getenv("SEAMLESS_API_KEY", "")
SEAMLESS_BASE = "https://api.seamless.ai/api/client/v1"
PIPELINE_FILE = "pipeline.json"

# ── Seamless.ai: job title batches for FSE company discovery ──────────────────
# Seamless is a contact DB — we search by title, extract unique employers.
# Each inner list is one API call (OR across titles).
SEAMLESS_TITLE_BATCHES = [
    # Field service / operations leadership
    ["VP Field Service", "Vice President Field Service", "Director Field Service",
     "Head of Field Service", "VP Field Operations", "Director Field Operations"],
    # Service management
    ["VP Service", "Director Service Management", "VP Customer Service",
     "Director After Sales", "Head of Service Operations", "Chief Service Officer"],
    # Workforce / scheduling software buyers
    ["VP Workforce Management", "Director Workforce Optimization",
     "Head of Workforce Technology", "VP Operations Technology"],
    # Connected / IoT / digital transformation
    ["VP IoT", "Director Digital Transformation", "VP Connected Products",
     "Director Predictive Maintenance", "Head of Digital Operations"],
    # Marketing / partnerships (sponsorship buyers)
    ["VP Marketing", "Director Marketing", "VP Partnerships",
     "Head of Marketing", "CMO", "Chief Marketing Officer"],
]

# ── FSE Sponsor ICP — pre-configured for Field Service East ──────────────────
# These filters target companies that SELL software/tech to field service ops leaders.
FSE_ICP = {
    # Apollo keyword tags — maps to company industry/category
    "q_organization_keyword_tags": [
        "field service management",
        "workforce management software",
        "enterprise software",
        "industrial iot",
        "predictive maintenance",
        "augmented reality",
        "service management",
        "parts planning",
        "remote monitoring",
        "knowledge management",
    ],
    # SIC/NAICS codes for software/tech companies
    "organization_industry_tag_ids": [],  # filled dynamically or left open
    # US-only
    "organization_locations": ["United States"],
    # 50-5000 employees — small startups to mid-market (enterprise > 5k sells too)
    "organization_num_employees_ranges": ["50,500", "500,5000"],
    # Don't pull massive enterprise companies that would never sponsor a niche event
    # "organization_not_num_employees_ranges": ["5001,999999"],
}

# Keywords that suggest a company sells TO field service (not IS a field service company)
VENDOR_KEYWORDS = [
    "software", "platform", "saas", "ai", "ml", "iot", "technology",
    "solutions", "cloud", "analytics", "automation", "intelligence",
]

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _headers():
    return {"X-Tiga-Auth": TIGA_API_KEY, "Content-Type": "application/json"}


def _get(endpoint: str, params: dict = None) -> dict:
    import requests
    resp = requests.get(f"{TIGA_BASE}{endpoint}", headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(endpoint: str, payload: dict) -> dict:
    import requests
    resp = requests.post(f"{TIGA_BASE}{endpoint}", headers=_headers(), json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ── Pipeline helpers ──────────────────────────────────────────────────────────

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


def get_known_companies() -> set:
    known = set()
    for entry in load_json(PIPELINE_FILE, []):
        name = entry.get("company", "").strip()
        if name:
            known.add(name.lower())
    return known


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


# ── Tiga: list signals ────────────────────────────────────────────────────────

def list_signals(raw: bool = False) -> list:
    """Return all signals from Tiga account."""
    try:
        data = _get("/signals")
        signals = data if isinstance(data, list) else data.get("signals", data.get("data", []))
        if raw and signals:
            print("\n[Raw] First signal object keys:", list(signals[0].keys()))
            print(json.dumps(signals[0], indent=2)[:800])
        return signals
    except Exception as e:
        print(f"[!] Could not fetch signals: {e}")
        return []


def _signal_name(s: dict) -> str:
    """Extract signal name from any known field variant."""
    return (
        s.get("name") or
        s.get("title") or
        s.get("signal_name") or
        s.get("label") or
        s.get("display_name") or
        s.get("prompt", "")[:40] or
        "?"
    )


# ── Seamless.ai company search ───────────────────────────────────────────────

def _seamless_headers():
    return {"Authorization": f"Bearer {SEAMLESS_API_KEY}", "Content-Type": "application/json"}


def _extract_companies_from_contacts(contacts: list) -> list:
    """Pull unique company dicts from a Seamless contact result list."""
    seen: dict[str, dict] = {}
    for c in contacts:
        name = (
            c.get("company_name") or c.get("current_employer") or
            c.get("company") or c.get("organization_name") or ""
        ).strip()
        if not name or name.lower() in seen:
            continue
        seen[name.lower()] = {
            "name": name,
            "website": (
                c.get("company_website") or c.get("website") or
                c.get("company_domain") or ""
            ),
            "industry": c.get("industry") or c.get("company_industry") or "",
            "employee_count": (
                c.get("company_employee_count") or c.get("employee_count") or
                c.get("num_employees") or 0
            ),
            "linkedin_url": (
                c.get("company_linkedin_url") or c.get("linkedin_company_url") or ""
            ),
            "location": (
                c.get("city") or c.get("company_city") or c.get("state") or ""
            ),
        }
    return list(seen.values())


def search_seamless_by_titles(titles: list, page: int = 1, per_page: int = 25) -> list:
    """
    Search Seamless.ai contacts by job titles.
    Seamless is a people DB — valid fields are title, seniority, country,
    company_name, page, page_size.  We omit company_name to search all companies.
    Returns list of company dicts extracted from contact results.
    """
    import requests
    payload = {
        "title": titles,
        "seniority": ["vp", "director", "c_suite", "svp", "evp"],
        "country": ["United States"],
        "page": page,
        "page_size": per_page,
    }
    try:
        resp = requests.post(
            f"{SEAMLESS_BASE}/search/contacts",
            headers=_seamless_headers(),
            json=payload,
            timeout=30,
        )
        if resp.status_code == 402:
            print(f"  [Seamless] Out of credits")
            return []
        if resp.status_code == 401:
            print(f"  [Seamless] Auth error — check SEAMLESS_API_KEY")
            return []
        if not resp.ok:
            print(f"  [Seamless] Error {resp.status_code}: {resp.text[:200]}")
            return []
        data = resp.json()
        contacts = data.get("contacts", data.get("data", data.get("results", [])))
        return _extract_companies_from_contacts(contacts)
    except Exception as e:
        print(f"  [Seamless] Title search failed: {e}")
        return []


# Keep old signature for backward compat
def search_seamless_companies(keyword: str, page: int = 1, per_page: int = 25) -> list:
    """Deprecated — use search_seamless_by_titles directly."""
    return []


def seamless_company_to_prospect(c: dict) -> dict:
    """Normalize a Seamless company result to prospect format."""
    name = (c.get("name") or c.get("company_name") or c.get("companyName") or "").strip()
    employees = (c.get("employee_count") or c.get("employeeCount") or
                 c.get("headcount") or c.get("num_employees") or 0)
    website = c.get("website") or c.get("domain") or c.get("companyWebsite") or ""
    if website and not website.startswith("http"):
        website = f"https://{website}"
    industry = c.get("industry") or c.get("industryName") or ""
    description = c.get("description") or c.get("summary") or ""
    linkedin = c.get("linkedin_url") or c.get("linkedInUrl") or c.get("linkedin") or ""
    location = c.get("location") or c.get("city") or c.get("headquarters") or ""

    return {
        "company": name,
        "website": website,
        "industry": industry,
        "headcount": str(employees),
        "description": description,
        "linkedin_url": linkedin,
        "location": location,
        "source": "seamless",
        "found_date": datetime.now().strftime("%Y-%m-%d"),
    }


def search_seamless_all(known: set, progress_cb=None) -> list:
    """
    Run all SEAMLESS_TITLE_BATCHES, deduplicate against known, return new prospects.
    """
    if not SEAMLESS_API_KEY:
        print("  [Seamless] No API key — skipping")
        return []

    results = []
    seen = set(known)
    total = len(SEAMLESS_TITLE_BATCHES)

    for i, titles in enumerate(SEAMLESS_TITLE_BATCHES):
        label = titles[0]  # use first title as label
        if progress_cb:
            progress_cb(f"Seamless: searching '{label}'...", i, total)
        companies = search_seamless_by_titles(titles)
        new = 0
        for c in companies:
            p = seamless_company_to_prospect(c)
            name = p.get("company", "")
            if not name:
                continue
            if is_duplicate(name, seen):
                continue
            results.append(p)
            seen.add(name.lower())
            new += 1
        print(f"  [Seamless] '{label}...' → {len(companies)} companies, {new} new")
        time.sleep(0.5)

    return results


# ── Tiga: Apollo company search ───────────────────────────────────────────────

def search_apollo(page: int = 1, per_page: int = 25, extra_filters: dict = None) -> list:
    """
    Search Apollo via Tiga for FSE-relevant companies.
    Returns list of raw Apollo org objects.
    """
    payload = {
        **FSE_ICP,
        "page": page,
        "per_page": per_page,
    }
    if extra_filters:
        payload.update(extra_filters)

    data = _post("/apollo-organization-search", payload)
    orgs = data.get("organizations", data.get("accounts", data.get("data", [])))
    return orgs


def apollo_org_to_prospect(org: dict) -> dict:
    """Convert raw Apollo org object to a prospect dict."""
    name = org.get("name", "").strip()
    employees = org.get("num_employees") or org.get("estimated_num_employees") or 0
    keywords = org.get("keywords", []) or []
    industry = org.get("industry", "") or org.get("primary_domain", "")
    website = org.get("website_url", "") or org.get("primary_domain", "")
    if website and not website.startswith("http"):
        website = f"https://{website}"

    return {
        "company": name,
        "website": website,
        "industry": industry,
        "headcount": str(employees),
        "keywords": ", ".join(keywords[:10]) if keywords else "",
        "description": org.get("short_description", "") or "",
        "linkedin_url": org.get("linkedin_url", "") or "",
        "location": org.get("city", "") or org.get("state", "") or "",
        "apollo_id": org.get("id", ""),
        "source": "tiga_apollo",
        "found_date": datetime.now().strftime("%Y-%m-%d"),
    }


# ── Tiga: run signal against a list of companies ─────────────────────────────

def create_tiga_account(company_name: str, website: str = "") -> str | None:
    """Create or find a Tiga account. Returns account ID."""
    payload = {"account": {"name": company_name}}
    if website:
        payload["account"]["website"] = website
    try:
        data = _post("/accounts", payload)
        return str(data.get("id") or data.get("account", {}).get("id", ""))
    except Exception as e:
        print(f"    [!] Could not create account for {company_name}: {e}")
        return None


def run_signal_on_account(signal_id: str, account_id: str) -> dict | None:
    """Run a signal on a single account. Returns result dict or None."""
    try:
        payload = {"signal_id": signal_id, "object_id": account_id, "object_type": "account"}
        data = _post("/signal-runs", payload)
        run_id = str(data.get("id") or data.get("signal_run", {}).get("id", ""))
        if not run_id:
            return None

        # Poll for result
        for _ in range(30):
            time.sleep(3)
            result = _get(f"/signal-runs/{run_id}")
            status = result.get("status", "")
            if status in ("completed", "done", "success"):
                return result
            if status in ("failed", "error"):
                return None

        return None
    except Exception as e:
        print(f"    [!] Signal run error: {e}")
        return None


# ── Main prospecting flow ─────────────────────────────────────────────────────

def run_prospecting(
    signal_ids: list = None,
    pages: int = 3,  # kept for API compat but unused now
    per_page: int = 25,
    min_score: int = 0,
    auto_add: bool = False,
    auto_add_min_score: int = 70,
    progress_cb=None,
) -> list:
    """
    Full prospecting run:
    1. Search Seamless.ai with FSE ICP keywords
    2. Deduplicate against pipeline
    3. Optionally run Tiga signals to score/filter
    4. Return prospect list; optionally auto-add to pipeline

    progress_cb: callable(step_label, current, total)
    Returns list of prospect dicts with optional signal_score added.
    """
    print(f"\n[FSE Prospector] Starting search...")
    print(f"  Seamless: {len(SEAMLESS_TITLE_BATCHES)} title-batch searches")
    if signal_ids:
        print(f"  Signals: {signal_ids}")

    known = get_known_companies()
    print(f"  {len(known)} companies already in pipeline\n")

    # ── Step 1: Seamless.ai search ────────────────────────────────────────────
    if not SEAMLESS_API_KEY:
        print("[!] SEAMLESS_API_KEY not set — cannot search. Add it to .env")
        return []

    def _seamless_cb(label, i, total):
        if progress_cb:
            progress_cb(label, i, total)

    raw_prospects = search_seamless_all(known, progress_cb=_seamless_cb)

    if progress_cb:
        progress_cb(f"Search done — {len(raw_prospects)} new companies found", len(SEAMLESS_SEARCHES), len(SEAMLESS_SEARCHES))
    print(f"\n  {len(raw_prospects)} new companies after dedup")

    if not raw_prospects:
        return []

    # ── Step 2: Run signals (optional) ───────────────────────────────────────
    if signal_ids:
        print(f"\n  Running {len(signal_ids)} signal(s) on {len(raw_prospects)} companies...")
        for pi, prospect in enumerate(raw_prospects):
            if progress_cb:
                progress_cb(
                    f"Scoring {prospect['company']} with signals...",
                    pi, len(raw_prospects)
                )
            account_id = create_tiga_account(prospect["company"], prospect.get("website", ""))
            if not account_id:
                continue
            prospect["tiga_account_id"] = account_id

            scores = []
            for sig_id in signal_ids:
                result = run_signal_on_account(str(sig_id), account_id)
                if result:
                    score = result.get("score") or result.get("signal_run", {}).get("score")
                    label = result.get("label") or result.get("signal_run", {}).get("label", "")
                    reasoning = result.get("reasoning") or result.get("signal_run", {}).get("reasoning", "")
                    if score is not None:
                        scores.append(int(score))
                    if reasoning and not prospect.get("signal_reasoning"):
                        prospect["signal_reasoning"] = reasoning
                    if label and not prospect.get("signal_label"):
                        prospect["signal_label"] = label

            if scores:
                prospect["signal_score"] = round(sum(scores) / len(scores))
                tag = "🟢" if prospect["signal_score"] >= 70 else "🟡" if prospect["signal_score"] >= 40 else "🔴"
                print(f"    {tag} {prospect['company']} — signal score: {prospect['signal_score']}")

        if progress_cb:
            progress_cb("Signal scoring complete", len(raw_prospects), len(raw_prospects))

    # ── Step 3: Filter by min_score ───────────────────────────────────────────
    if min_score > 0 and any("signal_score" in p for p in raw_prospects):
        raw_prospects = [p for p in raw_prospects
                         if p.get("signal_score", 100) >= min_score]
        print(f"\n  {len(raw_prospects)} companies above min_score {min_score}")

    # Sort: signal_score desc, then name
    raw_prospects.sort(
        key=lambda p: (-p.get("signal_score", 0), p.get("company", "").lower())
    )

    # ── Step 4: Auto-add to pipeline ──────────────────────────────────────────
    if auto_add:
        to_add = [p for p in raw_prospects
                  if p.get("signal_score", auto_add_min_score) >= auto_add_min_score]
        if to_add:
            pipeline = load_json(PIPELINE_FILE, [])
            existing = {c["company"].lower() for c in pipeline}
            added = 0
            for p in to_add:
                if p["company"].lower() in existing:
                    continue
                pipeline_entry = {
                    "company": p["company"],
                    "category": p.get("industry", "Other"),
                    "what_they_do": p.get("description", ""),
                    "score": p.get("signal_score", 0),
                    "tier": "A" if p.get("signal_score", 0) >= 80 else "B" if p.get("signal_score", 0) >= 60 else "C",
                    "priority": "hot" if p.get("signal_score", 0) >= 80 else "medium",
                    "status": "researched",
                    "source": "tiga_prospector",
                    "website": p.get("website", ""),
                    "linkedin_url": p.get("linkedin_url", ""),
                    "headcount": p.get("headcount", ""),
                    "fit_reason": p.get("signal_reasoning", "Found via Tiga Apollo + signal scoring"),
                    "pitch_angle": "",
                    "outreach_note": "",
                    "contacts": [],
                    "found_date": p.get("found_date", datetime.now().strftime("%Y-%m-%d")),
                }
                pipeline.append(pipeline_entry)
                existing.add(p["company"].lower())
                added += 1
                p["auto_added"] = True

            if added:
                pipeline.sort(key=lambda x: x.get("company", "").lower())
                save_json(PIPELINE_FILE, pipeline)
                print(f"\n  ✅ Auto-added {added} companies to pipeline")

    print(f"\n[Done] {len(raw_prospects)} prospects returned")
    return raw_prospects


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tiga FSE Prospector")
    parser.add_argument("--list-signals", action="store_true", help="List all Tiga signals and exit")
    parser.add_argument("--raw", action="store_true", help="Dump raw JSON of first signal (helps debug field names)")
    parser.add_argument("--signals", nargs="+", help="Signal IDs to run (e.g. --signals 123 456)")
    parser.add_argument("--pages", type=int, default=3, help="Pages of Apollo results (25 per page)")
    parser.add_argument("--min-score", type=int, default=0, help="Only show companies with signal score >= N")
    parser.add_argument("--auto-add", action="store_true", help="Auto-add score >= 70 to pipeline")
    args = parser.parse_args()

    if args.list_signals:
        signals = list_signals(raw=args.raw)
        if not signals:
            print("No signals found (or API error).")
        else:
            print(f"\n{len(signals)} signals in your Tiga account:\n")
            for s in signals:
                print(f"  ID={s.get('id')} | {_signal_name(s)} | type={s.get('signal_type') or s.get('type','?')}")
        return

    prospects = run_prospecting(
        signal_ids=args.signals,
        pages=args.pages,
        min_score=args.min_score,
        auto_add=args.auto_add,
        auto_add_min_score=70,
    )

    if not prospects:
        print("\nNo new prospects found.")
        return

    print(f"\n{'='*60}")
    print(f"Results ({len(prospects)} prospects):")
    print(f"{'='*60}")
    for p in prospects:
        score_str = f" | signal: {p['signal_score']}" if "signal_score" in p else ""
        print(f"  {'[AUTO-ADDED]' if p.get('auto_added') else '[pending]'} "
              f"{p['company']}{score_str} | {p.get('industry','?')} | {p.get('headcount','?')} employees")


if __name__ == "__main__":
    main()
