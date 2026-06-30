"""
Seamless.ai helper — search only (no research/reveal).
Imported by app.py for in-app contact discovery.
"""
import os, time, requests

BASE_URL = "https://api.seamless.ai/api/client/v1"

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

def _headers(api_key: str) -> dict:
    return {"Token": api_key, "Content-Type": "application/json"}


def _title_priority(title: str) -> int:
    t = (title or "").lower()
    if any(x in t for x in ["vp marketing", "vice president marketing"]): return 10
    if "director of marketing" in t or "director marketing" in t: return 9
    if "cmo" in t or "chief marketing" in t: return 8
    if "vp partnerships" in t or "director of partnerships" in t: return 7
    if "head of marketing" in t or "head of events" in t: return 6
    if "vp demand" in t or "director demand" in t: return 5
    if "vp sales" in t or "director of sales" in t: return 4
    return 1


def search_contacts(company_name: str, api_key: str, limit: int = 10) -> list[dict]:
    """
    Search Seamless.ai for sponsorship-relevant contacts at a company.
    Returns a list of normalized contact dicts sorted by title relevance.
    Does NOT call the research/reveal endpoint (no credit spend).
    """
    payload = {
        "companyName": [company_name],
        "jobTitle": TARGET_JOB_TITLES,
        "seniority": ["VP", "Director", "C-Level"],
        "contactCountry": ["United States"],
        "limit": limit,
    }
    try:
        r = requests.post(f"{BASE_URL}/search/contacts",
                          headers=_headers(api_key), json=payload, timeout=15)
    except Exception as e:
        return [{"error": str(e)}]

    if r.status_code == 402:
        return [{"error": "Out of Seamless credits"}]
    if not r.ok:
        return [{"error": f"Seamless {r.status_code}: {r.text[:100]}"}]

    candidates = r.json().get("data", [])
    candidates.sort(key=lambda c: _title_priority(c.get("title", "")), reverse=True)

    results = []
    for c in candidates[:limit]:
        results.append({
            "name":     c.get("name") or f"{c.get('firstName','')} {c.get('lastName','')}".strip(),
            "title":    c.get("title", ""),
            "email":    "",   # not available from search — requires research step
            "phone":    "",
            "linkedin": c.get("liUrl") or "",
            "seamless_id": c.get("searchResultId", ""),
            "source":   "seamless",
            "notes":    "",
            "activity_log": [],
        })
    return results


def research_contacts(search_result_ids: list[str], api_key: str) -> list[dict]:
    """
    Submit a research request to reveal email + phone for given searchResultIds.
    Returns enriched contact dicts or empty list on failure.
    Costs Seamless credits — call only when intentionally revealing.
    """
    if not search_result_ids:
        return []

    # Submit research request
    r = requests.post(f"{BASE_URL}/contacts/research",
                      headers=_headers(api_key),
                      json={"searchResultIds": search_result_ids},
                      timeout=15)
    if not r.ok:
        return []

    request_ids = r.json().get("requestIds", [])
    if not request_ids:
        return []

    # Poll for results (max 30s)
    ids_csv = ",".join(request_ids)
    for _ in range(10):
        time.sleep(3)
        poll = requests.get(f"{BASE_URL}/contacts/research",
                            headers=_headers(api_key),
                            params={"requestIds": ids_csv},
                            timeout=15)
        if poll.status_code == 404:
            break  # endpoint unavailable for this account tier
        if not poll.ok:
            continue
        data = poll.json().get("data", [])
        pending = [x for x in data if x.get("status","").lower() in ("pending","running","")]
        if not pending:
            contacts = []
            for item in data:
                ct = item.get("contact", {})
                if ct:
                    contacts.append({
                        "name":     ct.get("fullName") or ct.get("name", ""),
                        "title":    ct.get("title", ""),
                        "email":    ct.get("email") or ct.get("email1") or "",
                        "phone":    ct.get("phone") or ct.get("contactPhone1") or "",
                        "linkedin": ct.get("lIProfileUrl") or "",
                        "source":   "seamless",
                        "notes":    "",
                        "activity_log": [],
                    })
            return contacts
    return []
