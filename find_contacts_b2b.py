"""
B2B Atlanta — Seamless.ai Contact Finder
=========================================
Loads the B2B Atlanta pipeline from GitHub, finds VP/Director Marketing/
Partnerships contacts at each company via Seamless.ai, and saves them
back into the pipeline on GitHub so they appear in the Streamlit app.

Flow per company:
  1. POST /search/contacts  → list of candidates with searchResultId
  2. POST /contacts/research → request email/phone reveal (costs credits)
  3. GET  /contacts/research → poll until complete, get email + phone

Usage:
    python find_contacts_b2b.py                    # all companies without contacts
    python find_contacts_b2b.py --all              # re-run even if contacts exist
    python find_contacts_b2b.py --company Akeneo   # single company
    python find_contacts_b2b.py --limit 10         # first N companies only
    python find_contacts_b2b.py --dry-run          # search only, no reveal/save
    python find_contacts_b2b.py --max-contacts 3   # contacts per company (default 2)
"""

import os, json, time, base64, argparse, requests
from dotenv import load_dotenv

load_dotenv()

SEAMLESS_KEY  = os.getenv("SEAMLESS_API_KEY")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
GITHUB_REPO   = os.getenv("GITHUB_REPO", "Ryancasale31/sdr-agent-template")
PIPELINE_PATH = "events/b2b-online-atlanta/pipeline.json"
BRANCH        = "data"
BASE_URL      = "https://api.seamless.ai/api/client/v1"

SL_HDR = {"Token": SEAMLESS_KEY, "Content-Type": "application/json"}
GH_HDR = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

TARGET_JOB_TITLES = [
    "VP Marketing",
    "Director of Marketing",
    "CMO",
    "VP Partnerships",
    "Director of Partnerships",
    "Head of Marketing",
    "Head of Events",
    "VP Demand Generation",
    "VP Sales",
    "Field Marketing Director",
]
TARGET_SENIORITY = ["VP", "Director", "C-Level"]


# ── GitHub ────────────────────────────────────────────────────────────────────

def gh_load():
    r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{PIPELINE_PATH}",
                     params={"ref": BRANCH}, headers=GH_HDR, timeout=15)
    if r.status_code != 200:
        print(f"[ERROR] GitHub load {r.status_code}: {r.text[:200]}")
        return [], None
    j = r.json()
    return json.loads(base64.b64decode(j["content"]).decode()), j.get("sha")


def gh_save(pipeline, sha, message):
    body = {"message": message,
            "content": base64.b64encode(json.dumps(pipeline, indent=2).encode()).decode(),
            "branch": BRANCH}
    if sha:
        body["sha"] = sha
    r = requests.put(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{PIPELINE_PATH}",
                     json=body, headers=GH_HDR, timeout=15)
    if r.status_code in (200, 201):
        print(f"  ✓ Pushed to GitHub")
        return r.json()["content"]["sha"]
    print(f"  ✗ GitHub push failed: {r.status_code}: {r.text[:200]}")
    return sha


# ── Seamless search ───────────────────────────────────────────────────────────

def sl_search(company_name: str, limit: int = 10) -> list:
    payload = {
        "companyName": [company_name],
        "jobTitle": TARGET_JOB_TITLES,
        "seniority": TARGET_SENIORITY,
        "contactCountry": ["United States"],
        "limit": limit,
    }
    r = requests.post(f"{BASE_URL}/search/contacts", headers=SL_HDR, json=payload, timeout=20)
    if r.status_code == 402:
        raise RuntimeError("Seamless: out of credits (402)")
    if not r.ok:
        print(f"  [warn] Search {r.status_code}: {r.text[:150]}")
        return []
    return r.json().get("data", [])


def title_priority(title: str) -> int:
    t = (title or "").lower()
    if any(x in t for x in ["vp marketing", "vice president marketing"]): return 10
    if any(x in t for x in ["director of marketing", "director marketing"]): return 9
    if any(x in t for x in ["cmo", "chief marketing"]): return 8
    if any(x in t for x in ["vp partnerships", "director of partnerships"]): return 7
    if any(x in t for x in ["head of marketing", "head of events"]): return 6
    if any(x in t for x in ["vp demand", "director demand"]): return 5
    if any(x in t for x in ["field marketing"]): return 4
    if any(x in t for x in ["vp sales", "director of sales"]): return 3
    return 1


# ── Seamless research (email/phone reveal) ────────────────────────────────────

def sl_research(search_result_ids: list) -> list:
    """Submit a research request for a list of searchResultIds. Returns requestIds."""
    r = requests.post(f"{BASE_URL}/contacts/research",
                      headers=SL_HDR,
                      json={"searchResultIds": search_result_ids},
                      timeout=20)
    if not r.ok:
        print(f"  [warn] Research request {r.status_code}: {r.text[:150]}")
        return []
    return r.json().get("requestIds", [])


def sl_poll(request_ids: list, max_wait: int = 30) -> list:
    """Poll research results until complete or timeout. Returns list of contact dicts."""
    for attempt in range(max_wait // 3):
        time.sleep(3)
        # Try comma-separated and individual param formats
        r = requests.get(f"{BASE_URL}/contacts/research",
                         headers=SL_HDR,
                         params=[("requestIds", rid) for rid in request_ids],
                         timeout=20)
        if r.status_code == 404:
            # Endpoint not available — bail immediately, fall back to search data
            return []
        if not r.ok:
            print(f"  [warn] Poll {r.status_code}: {r.text[:100]}")
            continue
        results = r.json().get("data", [])
        pending = [x for x in results if x.get("status", "").lower() in ("pending", "running", "")]
        if not pending:
            return [x.get("contact", {}) for x in results if x.get("contact")]
    print(f"  [warn] Research timed out after {max_wait}s")
    return []


def normalize(raw: dict, company_name: str) -> dict:
    email = (raw.get("email") or raw.get("email1") or raw.get("personalEmail") or "")
    phone = (raw.get("phone") or raw.get("contactPhone1") or "")
    name  = (raw.get("fullName") or raw.get("name") or
             f"{raw.get('firstName','')} {raw.get('lastName','')}".strip())
    linkedin = raw.get("lIProfileUrl") or raw.get("liUrl") or raw.get("lISalesNavUrl") or ""
    return {
        "name":     name,
        "title":    raw.get("title", ""),
        "email":    email,
        "phone":    phone,
        "linkedin": linkedin,
        "source":   "seamless",
        "notes":    "",
        "activity_log": [],
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def find_contacts(company_name: str, max_contacts: int = 2, dry_run: bool = False) -> list:
    print(f"  Searching Seamless: {company_name}")
    candidates = sl_search(company_name, limit=max_contacts * 5)

    if not candidates:
        print(f"    → 0 results")
        return []

    # Sort by title priority, pick top N
    candidates.sort(key=lambda c: title_priority(c.get("title", "")), reverse=True)
    top = candidates[:max_contacts]
    print(f"    → {len(candidates)} found, using: {[c.get('title','?') for c in top]}")

    contacts = [normalize(c, company_name) for c in top]
    for c in contacts:
        print(f"    ✓ {c['name']} | {c['title']}")
    return contacts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", help="Single company name")
    parser.add_argument("--all", action="store_true", help="Re-run even if contacts exist")
    parser.add_argument("--limit", type=int, help="Max companies to process")
    parser.add_argument("--max-contacts", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true", help="Search only, no reveal or save")
    args = parser.parse_args()

    if not SEAMLESS_KEY:
        print("ERROR: SEAMLESS_API_KEY not set"); return
    if not GITHUB_TOKEN:
        print("ERROR: GITHUB_TOKEN not set"); return

    print("Loading pipeline from GitHub...")
    pipeline, sha = gh_load()
    if not pipeline:
        print("ERROR: Could not load pipeline"); return
    print(f"Loaded {len(pipeline)} companies.\n")

    if args.company:
        targets = [c for c in pipeline if c["company"].lower() == args.company.lower()]
        if not targets:
            print(f"'{args.company}' not found. Companies: {[c['company'] for c in pipeline]}")
            return
    elif args.all:
        targets = pipeline
    else:
        targets = [c for c in pipeline if not c.get("contacts")]

    if args.limit:
        targets = targets[:args.limit]

    mode = "[DRY RUN] " if args.dry_run else ""
    print(f"{mode}Processing {len(targets)} companies ({args.max_contacts} contacts each)\n")

    total = 0
    updated = False

    for company in targets:
        name = company["company"]
        print(f"\n→ {name}")
        try:
            contacts = find_contacts(name, max_contacts=args.max_contacts, dry_run=args.dry_run)
        except RuntimeError as e:
            print(f"  FATAL: {e}")
            break

        if contacts:
            company["contacts"] = contacts
            total += len(contacts)
            updated = True

        time.sleep(1)

    print(f"\n{'='*50}")
    print(f"Found {total} contacts across {len(targets)} companies.")

    if updated and not args.dry_run:
        n_with = sum(1 for c in pipeline if c.get("contacts"))
        sha = gh_save(pipeline, sha, f"Seamless contacts: {n_with} companies enriched")
        print("✓ Done — refresh your Streamlit app.")
    elif args.dry_run:
        print("[DRY RUN] No changes saved.")
    else:
        print("No new contacts found.")


if __name__ == "__main__":
    main()
