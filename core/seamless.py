"""
Seamless.ai — contacts at a named company, and companies behind a set of titles.

Two calls matter:
  search   POST /search/contacts      free. Names, titles, LinkedIn. No email.
  reveal   POST /contacts/research    costs one credit per person. Async: returns
           GET  /contacts/research    requestIds, then poll until not pending.

Auth has been written two ways across the old scripts (a `Token:` header and
`Authorization: Bearer`). Seamless documents the Token header; we try it first,
fall back to Bearer on a 401, and remember whichever worked for the session.
"""
import os
import time

BASE = "https://api.seamless.ai/api/client/v1"

# Who buys a sponsorship at a vendor. Marketing and events own the budget;
# partnerships and sales leadership sign off on the ones that drive pipeline.
DEFAULT_TITLES = [
    "VP Marketing", "Vice President of Marketing", "CMO", "Chief Marketing Officer",
    "Director of Marketing", "Head of Marketing", "Head of Events",
    "Director of Events", "Field Marketing Director", "VP Demand Generation",
    "Director of Demand Generation", "VP Partnerships", "Director of Partnerships",
    "VP Sales", "Chief Revenue Officer",
]


class SeamlessError(RuntimeError):
    """A Seamless failure in words a seller can act on."""


def _key() -> str:
    key = os.getenv("SEAMLESS_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("SEAMLESS_API_KEY", "")
        except Exception:
            key = ""
    return key.strip()


def available() -> bool:
    return bool(_key())


_AUTH_STYLE = {"style": None}       # "token" | "bearer", learnt on first success


def _auth_headers(style: str) -> dict:
    k = _key()
    h = {"Token": k} if style == "token" else {"Authorization": f"Bearer {k}"}
    h["Content-Type"] = "application/json"
    h["Accept"] = "application/json"
    return h


def _request(method: str, path: str, *, timeout: int = 30, **kw):
    import requests
    if not available():
        raise SeamlessError("No Seamless API key is set (SEAMLESS_API_KEY).")
    styles = [_AUTH_STYLE["style"]] if _AUTH_STYLE["style"] else ["token", "bearer"]
    last = None
    for style in styles:
        try:
            r = requests.request(method, f"{BASE}{path}", headers=_auth_headers(style),
                                 timeout=timeout, **kw)
        except Exception as e:
            raise SeamlessError(f"Could not reach Seamless: {e}") from e
        if r.status_code == 401:
            last = r
            continue
        _AUTH_STYLE["style"] = style
        if r.status_code == 402:
            raise SeamlessError("Seamless is out of credits.")
        if r.status_code == 429:
            raise SeamlessError("Seamless is rate-limiting this key. Wait a minute and retry.")
        if not r.ok:
            raise SeamlessError(f"Seamless returned {r.status_code}: {(r.text or '')[:200]}")
        return r
    raise SeamlessError("Seamless rejected the API key (401). Generate a new one in "
                        "Seamless → Settings → API and update SEAMLESS_API_KEY. "
                        f"{(last.text or '')[:150] if last is not None else ''}")


# ── Ranking ───────────────────────────────────────────────────────────────────
def title_rank(title: str) -> int:
    """Higher = closer to whoever signs a sponsorship."""
    t = (title or "").lower()
    if any(x in t for x in ("intern", "assistant", "coordinator", "specialist", "associate")):
        return 0
    if "event" in t:
        return 10
    if ("marketing" in t or "cmo" in t) and any(x in t for x in ("vp", "vice president", "chief", "cmo", "head")):
        return 9
    if "marketing" in t and "director" in t:
        return 8
    if "demand" in t or "field marketing" in t:
        return 7
    if "partner" in t or "alliances" in t:
        return 6
    if any(x in t for x in ("revenue", "cro", "vp sales", "vice president sales", "vice president of sales")):
        return 5
    if "marketing" in t:
        return 4
    if any(x in t for x in ("ceo", "founder", "president", "general manager")):
        return 3
    return 1


def _first(d: dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return default


def _normalise(c: dict) -> dict:
    name = _first(c, "name", "fullName") or \
        f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
    return {
        "name": name,
        "title": _first(c, "title", "jobTitle"),
        "email": _first(c, "email", "email1", "contactEmail"),
        "phone": _first(c, "phone", "contactPhone1", "phone1"),
        "linkedin": _first(c, "liUrl", "lIProfileUrl", "linkedinUrl", "linkedin"),
        "company_name": _first(c, "company", "companyName"),
        "domain": _first(c, "domain", "companyDomain", "website"),
        "seamless_id": _first(c, "searchResultId", "id"),
        "source": "seamless",
    }


# ── Search (free) ─────────────────────────────────────────────────────────────
def search_contacts(company: str, titles: list = None, limit: int = 15,
                    domain: str = "") -> list:
    """Sponsorship-relevant people at one company, best titles first. No emails."""
    payload = {
        "companyName": [company],
        "jobTitle": titles or DEFAULT_TITLES,
        "seniority": ["VP", "Director", "C-Level"],
        "contactCountry": ["United States"],
        "limit": max(limit, 10),
    }
    if domain:
        payload["companyDomain"] = [domain]
    r = _request("POST", "/search/contacts", json=payload)
    rows = (r.json() or {}).get("data") or []
    out = [_normalise(c) for c in rows if isinstance(c, dict)]
    # Seamless matches company names loosely; drop people at a different firm.
    want = _simple(company)
    if want:
        kept = [c for c in out if not c["company_name"]
                or want in _simple(c["company_name"]) or _simple(c["company_name"]) in want]
        out = kept or out
    out.sort(key=lambda c: -title_rank(c["title"]))
    return out[:limit]


def _simple(s: str) -> str:
    import re
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|gmbh|plc)\b\.?", "", (s or "").lower())
    return re.sub(r"[^a-z0-9]", "", s)


def companies_by_titles(titles: list, keywords: list = None, pages: int = 2) -> list:
    """Discovery: who employs people with these titles (optionally in these
    industries/keywords)? Returns unique employers — a company list."""
    seen, out = set(), []
    for page in range(1, pages + 1):
        payload = {
            "jobTitle": titles,
            "seniority": ["VP", "Director", "C-Level"],
            "contactCountry": ["United States"],
            "limit": 50,
            "page": page,
        }
        if keywords:
            payload["keywords"] = keywords
        r = _request("POST", "/search/contacts", json=payload)
        rows = (r.json() or {}).get("data") or []
        for c in rows:
            n = _normalise(c)
            co = n["company_name"]
            if co and _simple(co) not in seen:
                seen.add(_simple(co))
                out.append({"company": co, "domain": n["domain"],
                            "signal": f"Has a {n['title']} on Seamless"})
        if len(rows) < 50:
            break
    return out


# ── Reveal (costs credits) ────────────────────────────────────────────────────
def reveal(contacts: list, timeout_s: int = 60) -> list:
    """Fill email/phone on contacts that carry a seamless_id. One credit each.
    Returns the same list, enriched where Seamless answered in time."""
    ids = [c["seamless_id"] for c in contacts if c.get("seamless_id") and not c.get("email")]
    if not ids:
        return contacts
    r = _request("POST", "/contacts/research", json={"searchResultIds": ids})
    req_ids = (r.json() or {}).get("requestIds") or []
    if not req_ids:
        return contacts

    found = {}
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(3)
        try:
            p = _request("GET", "/contacts/research", params={"requestIds": ",".join(req_ids)})
        except SeamlessError:
            continue
        data = (p.json() or {}).get("data") or []
        pending = [x for x in data if (x.get("status") or "").lower() in ("pending", "running", "")]
        for item in data:
            ct = item.get("contact") or {}
            if ct:
                n = _normalise(ct)
                key = item.get("searchResultId") or n["linkedin"] or n["name"].lower()
                found[key] = n
        if data and not pending:
            break

    by_li = {v["linkedin"]: v for v in found.values() if v.get("linkedin")}
    by_name = {v["name"].lower(): v for v in found.values() if v.get("name")}
    for c in contacts:
        hit = found.get(c.get("seamless_id")) or by_li.get(c.get("linkedin")) \
            or by_name.get((c.get("name") or "").lower())
        if hit:
            c["email"] = c.get("email") or hit.get("email", "")
            c["phone"] = c.get("phone") or hit.get("phone", "")
            c["linkedin"] = c.get("linkedin") or hit.get("linkedin", "")
    return contacts


def check_seamless() -> tuple:
    """(ok, detail) for Setup → Connections. Free — search only."""
    if not available():
        return False, "No API key set."
    try:
        rows = search_contacts("Salesforce", limit=3)
        return True, (f"Connected ({_AUTH_STYLE['style']} auth) — "
                      f"{len(rows)} contacts back for a test search.")
    except Exception as e:
        return False, str(e)
