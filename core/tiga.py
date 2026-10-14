"""
Tiga as a research engine.

Why this exists: the Anthropic key ran out of credit and took company research
down with it. Tiga signals of `type: "gpt"` are a prompt plus web search, which
is the same primitive research_company() needs — and Ryan already pays for Tiga.

What this can and cannot do:
  CAN   judge a company we can name — research, scoring, a re-open angle.
  CANNOT find companies we cannot name. run-signal is account-scoped, so the
        Scout hunts (freeform, rival events, new markets) still need a real
        model key. Discovery lives in tiga_prospector.py instead.

API contract (Tiga docs, confirmed against the working code in tiga_signals.py):
  auth    X-Tiga-Auth: <key> on every request
  list    GET  /api/v1/signals?is_computed_column=true
  create  POST /api/v1/signal        {label, is_computed_column, type, computed_config}
  update  PUT  /api/v1/signal/:id    (GET first, send the full computed_config)
  run     POST /api/v1/signal/:id/run-signal  {"account": {"domain": "acme.com"}}
          Synchronous — no polling. Find-or-creates the account.
          Result: account.custom_columns[signal_id] = {status, value}
          status 1 SUCCESS · 2 NOT_FOUND · 3 MISSING_DEPENDENCIES
                 4 FAILED · 5 PRECONDITION_FAILED
"""
import json
import os
import re

from core import ai

ROOT = "https://app.tigalabs.com"
BASE = ROOT + "/api/v1"
SIGNAL_VERSION = "v1"          # bump to force every event's signal prompt to be rewritten
RUN_TIMEOUT = 180              # a gpt signal with web search is not fast
WORD_LIMIT = 250


class TigaError(ai.AIError):
    """A Tiga failure, phrased for the person selling. Subclasses AIError so the
    views that already catch AIError show it without changes."""


_STATUS = {
    1: None,                                    # success
    2: "Tiga could not find that company.",
    3: "The signal is missing something it depends on (usually the account has no domain).",
    4: "Tiga ran the signal and it failed.",
    5: "The signal's preconditions were not met for this account.",
}


# ── Plumbing ──────────────────────────────────────────────────────────────────
def _key() -> str:
    key = os.getenv("TIGA_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("TIGA_API_KEY", "")
        except Exception:
            key = ""
    return key


def available() -> bool:
    return bool(_key())


def _headers(extra: dict = None) -> dict:
    h = {"X-Tiga-Auth": _key(), "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _request(method: str, path: str, *, timeout: int = 45, root: bool = False, **kw):
    import requests
    if not available():
        raise TigaError("No Tiga API key is set, so Tiga research is off.")
    try:
        r = requests.request(method, f"{ROOT if root else BASE}{path}", headers=_headers(kw.pop("extra_headers", None)),
                             timeout=timeout, **kw)
    except Exception as e:
        raise TigaError(f"Could not reach Tiga: {e}") from e
    if r.status_code in (401, 403):
        raise TigaError("Tiga rejected the API key. Replace TIGA_API_KEY in the app's secrets.")
    if r.status_code == 429:
        raise TigaError("Tiga is rate-limiting this key. Wait a moment and try again.")
    if not r.ok:
        raise TigaError(f"Tiga returned {r.status_code}: {(r.text or '')[:200]}")
    return r


# ── Domains ───────────────────────────────────────────────────────────────────
# run-signal keys accounts on domain, and the pipeline stores company names. A
# wrong guess silently researches the wrong company, which is worse than not
# researching at all — so guessing is deliberately conservative and the caller
# is expected to let the user correct it.
_SUFFIXES = r"\b(inc|inc\.|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|sa|nv|bv|ag|pvt|technologies|technology|group|holdings|solutions|software|systems)\b"


def guess_domain(company: str) -> str:
    """A cautious .com guess, or "" when the name is too ambiguous to guess from."""
    name = re.sub(r"\(.*?\)", " ", company or "")          # drop parentheticals
    name = re.sub(_SUFFIXES, " ", name, flags=re.I)
    name = re.sub(r"[^A-Za-z0-9 ]", " ", name).strip()
    words = name.split()
    if not words or len(words) > 2:
        # "Medical Equipment Repair Associates" is a description, not a domain.
        return ""
    return "".join(words).lower() + ".com"


def find_account(company: str) -> dict:
    """Look the company up in Tiga so we can use its real domain. {} if absent."""
    r = _request("GET", "/accounts",
                 extra_headers={"Tiga-Filter": json.dumps({"search_term": company})})
    try:
        rows = r.json()
    except Exception:
        return {}
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return {}


def resolve_domain(company: str, record: dict = None) -> str:
    """Domain already on the record > Tiga's own > a cautious guess > ""."""
    if record and record.get("domain"):
        return record["domain"]
    try:
        acct = find_account(company)
    except TigaError:
        acct = {}
    for k in ("domain", "website", "url"):
        v = (acct.get(k) or "").strip()
        if v:
            return re.sub(r"^https?://(www\.)?|/.*$", "", v)
    return guess_domain(company)


# ── Signals ───────────────────────────────────────────────────────────────────
def _signal_label(event_id: str) -> str:
    return f"SDR Agent - Sponsor Fit - {event_id} ({SIGNAL_VERSION})"


def _research_prompt(icp: dict, cfg: dict) -> str:
    return (
        f"You are a sponsorship sales analyst for {ai.event_label(cfg)}.\n\n"
        f"EVENT BUYER PROFILE:\n{ai.audience_block(icp)}\n\n"
        "Assess {{.AccountName}} ({{.AccountWebsite}}) as a potential sponsor of this "
        "event. Judge them on whether the people in that buyer profile are the people "
        "they sell to.\n\n"
        "Return ONLY valid JSON and nothing else:\n"
        '{"what_they_do":"1-2 plain sentences","who_they_sell_to":"their buyer persona",'
        '"score":<0-100>,"tier":"<A|B|C>","fit_reason":"2-3 sentences on fit with THIS audience",'
        '"pitch_angle":"the single strongest reason to sponsor","risk":"the likeliest objection"}'
    )


def ensure_research_signal(event_id: str, icp: dict, cfg: dict) -> str:
    """Get-or-create this event's research signal, updating it when the ICP moved.

    One signal per event on purpose: the prompt carries that event's audience, and
    scoring a medical prospect against the B2B audience is how the old app produced
    confidently wrong numbers.
    """
    label = _signal_label(event_id)
    prompt = _research_prompt(icp, cfg)
    config = {
        "type": "gpt",
        "prompt": prompt,
        "is_account_insight": True,
        "can_use_web_search": True,
        "expiration_in_days": 30,
        "temperature": 0.2,
        "word_limit": WORD_LIMIT,
    }

    existing = None
    r = _request("GET", "/signals?is_computed_column=true")
    try:
        for s in r.json():
            if isinstance(s, dict) and s.get("label") == label:
                existing = s
                break
    except Exception:
        pass

    if existing:
        sig_id = existing.get("id")
        if ((existing.get("computed_config") or {}).get("prompt") or "") != prompt:
            # The ICP changed under it. Silently scoring against a stale audience
            # would be the same bug as sharing one signal across events.
            _request("PUT", f"/signal/{sig_id}", json={
                "label": label, "is_computed_column": True,
                "type": "text", "computed_config": config,
            })
        return sig_id

    r = _request("POST", "/signal", json={
        "label": label, "is_computed_column": True,
        "type": "text", "computed_config": config,
    })
    sig_id = (r.json() or {}).get("id")
    if not sig_id:
        raise TigaError("Tiga accepted the signal but returned no id.")
    return sig_id


def run_on_account(signal_id: str, domain: str) -> str:
    """Run the signal and return its text value. Synchronous."""
    r = _request("POST", f"/signal/{signal_id}/run-signal", timeout=RUN_TIMEOUT,
                 json={"account": {"domain": domain}})
    try:
        data = r.json()
    except Exception as e:
        raise TigaError(f"Tiga returned something that was not JSON: {e}") from e

    col = ((data.get("account") or {}).get("custom_columns") or {}).get(signal_id) or {}
    status = col.get("status")
    if status == 1:
        return col.get("value") or ""

    # Tiga's own explanation matters more than our label for it. Without this,
    # "ran the signal and it failed" is a dead end — you cannot tell a bad prompt
    # from a bad account from a rejected config.
    detail = ""
    for k in ("error", "error_message", "message", "reason", "value"):
        v = col.get(k)
        if v:
            detail = f" Tiga said: {str(v)[:400]}"
            break
    if not detail and col:
        detail = f" Response fields: {sorted(col.keys())}"
    if not col:
        detail = (f" No column came back for this signal at all. Top-level keys: "
                  f"{sorted(data.keys())}")

    raise TigaError(
        (_STATUS.get(status) or f"Tiga returned status {status!r}.") + detail
        + f" [signal {signal_id}]"
    )


def list_gpt_signals(limit: int = 5) -> list:
    """Existing gpt signals and their configs — the reference for what Tiga accepts.

    Comparing a signal Tiga runs happily against one it rejects is the fastest way
    to find the field that is wrong.
    """
    r = _request("GET", "/signals?is_computed_column=true")
    try:
        rows = r.json()
    except Exception:
        return []
    out = []
    for sig in rows if isinstance(rows, list) else []:
        cfg = (sig.get("computed_config") or {}) if isinstance(sig, dict) else {}
        if cfg.get("type") != "gpt":
            continue
        out.append({
            "label": sig.get("label"),
            "id": sig.get("id"),
            "type": sig.get("type"),
            "config": {k: (v if k != "prompt" else str(v)[:300])
                       for k, v in cfg.items()},
        })
        if len(out) >= limit:
            break
    return out


# ── The job ───────────────────────────────────────────────────────────────────
def research_company(company_name: str, icp: dict, cfg: dict,
                     event_id: str = "default", record: dict = None) -> dict:
    """Same contract as ai.research_company, answered by Tiga instead of Claude."""
    domain = resolve_domain(company_name, record)
    if not domain:
        raise TigaError(
            f"No website for {company_name}, and the name is too ambiguous to guess one. "
            "Add a domain to the record and try again."
        )

    sig_id = ensure_research_signal(event_id, icp, cfg)
    raw = run_on_account(sig_id, domain)
    if not raw.strip():
        raise TigaError(f"Tiga ran the signal on {domain} but returned nothing.")

    try:
        out = ai._parse_json(raw)
        if not isinstance(out, dict):
            raise ValueError("not an object")
    except Exception:
        # A gpt signal is free text; it may ignore "JSON only". Keep what it said
        # rather than throwing away a paid call, and make the degradation visible.
        out = {
            "what_they_do": raw.strip()[:600],
            "who_they_sell_to": "",
            "score": None,
            "tier": "",
            "fit_reason": "",
            "pitch_angle": "",
            "risk": "",
            "needs_review": "Tiga answered in prose rather than JSON — score it yourself.",
        }

    out["company"] = company_name
    out["domain"] = domain
    out["status"] = "researched"
    out["research_engine"] = "tiga"
    return out


def check_tiga() -> tuple:
    """(ok, detail) for Setup -> Connections."""
    if not available():
        return False, "No API key set."
    try:
        r = _request("GET", "/signals?is_computed_column=true")
        rows = r.json()
        n = len(rows) if isinstance(rows, list) else 0
        gpt = sum(1 for s in rows if isinstance(s, dict)
                  and (s.get("computed_config") or {}).get("type") == "gpt") if isinstance(rows, list) else 0
        return True, f"Connected — {n} signals, {gpt} of them AI prompts."
    except TigaError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# Contacts and discovery — no Claude needed
# ══════════════════════════════════════════════════════════════════════════════
# Shapes below come from tiga_contacts.py, which ran in production in July and
# produced real contacts (tiga_contacts.csv): people rows carry first_name,
# last_name, title, account_name, email_address, linkedin_url / person_linkedin.
import time as _time


def _rows(resp) -> list:
    try:
        d = resp.json()
    except Exception:
        return []
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("rows", "data", "people", "accounts", "organizations", "results"):
            if isinstance(d.get(k), list):
                return d[k]
    return []


def person_to_contact(p: dict) -> dict:
    name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or p.get("name", "")
    return {
        "name": name,
        "first_name": p.get("first_name", ""),
        "last_name": p.get("last_name", ""),
        "title": p.get("title", ""),
        "email": p.get("email_address") or p.get("email") or "",
        "phone": p.get("phone") or "",
        "linkedin": p.get("linkedin_url") or p.get("person_linkedin") or "",
        "company_name": p.get("account_name", ""),
        "domain": p.get("account_domain", ""),
        "tiga_person_id": p.get("id", ""),
        "source": "tiga",
    }


def search_people(company: str) -> list:
    """People Tiga already has at a company (its own DB — instant, free)."""
    r = _request("GET", "/people",
                 extra_headers={"Tiga-Filter": json.dumps({"search_term": company})})
    want = re.sub(r"[^a-z0-9]", "", company.lower())
    out = []
    for p in _rows(r):
        if not isinstance(p, dict):
            continue
        acct = re.sub(r"[^a-z0-9]", "", (p.get("account_name") or "").lower())
        if acct and want and (want in acct or acct in want):
            out.append(person_to_contact(p))
    return out


def find_people_agent(description: str, timeout_s: int = 300, progress=None) -> int:
    """Tiga's Find People agent — its Sales-Navigator-style search. Async: it
    populates Tiga's people DB, so call search_people() afterwards. Returns how
    many records it created (0 on timeout)."""
    r = _request("POST", "/agent/find-people", timeout=60,
                 json={"contact_description": description, "model": "gpt-5.4-2026-03-05"})
    body = r.json() or {}
    job = body.get("id") or body.get("status_id")
    if not job:
        raise TigaError(f"Find People agent returned no job id: {str(body)[:200]}")
    t0 = _time.time()
    while _time.time() - t0 < timeout_s:
        _time.sleep(7)
        if progress:
            progress(int(_time.time() - t0))
        try:
            p = _request("GET", f"/api/agent/find-people/{job}/status", root=True, timeout=30)
        except TigaError:
            continue
        d = p.json() or {}
        st_ = d.get("status", "")
        if st_ == "Complete":
            return len(d.get("created_flux_ids") or d.get("created_ids") or [])
        if st_.startswith("Error"):
            raise TigaError(f"Find People agent: {st_}")
    return 0


def enrich(contact: dict, timeout_s: int = 120) -> dict:
    """Waterfall enrichment for an email/phone. Mutates and returns contact."""
    first = contact.get("first_name") or (contact.get("name") or "").split(" ")[0]
    last = contact.get("last_name") or " ".join((contact.get("name") or "").split(" ")[1:])
    r = _request("POST", "/people/enrich-person", timeout=60, json={
        "first_name": first, "last_name": last,
        "company_name": contact.get("company_name", ""),
        "domain": contact.get("domain", ""),
        "person_linkedin_url": contact.get("linkedin", ""),
        "title": contact.get("title", ""),
    })
    eid = (r.json() or {}).get("enrich_id")
    if not eid:
        return contact
    t0 = _time.time()
    while _time.time() - t0 < timeout_s:
        _time.sleep(5)
        try:
            d = _request("GET", f"/enrich/{eid}", timeout=30).json() or {}
        except TigaError:
            continue
        if d.get("data_import_status", "Running") != "Running":
            contact["email"] = contact.get("email") or d.get("email_address") or ""
            contact["phone"] = contact.get("phone") or d.get("phone") or ""
            break
    return contact


def search_companies(keywords: str, per_page: int = 25, page: int = 1) -> list:
    """Company discovery through Tiga's Apollo search. Plain keywords in,
    companies out — the no-Claude replacement for the Ask hunt."""
    words = [w.strip() for w in re.split(r"[,;\n]", keywords or "") if w.strip()] or [keywords]
    body = {
        "q_organization_keyword_tags": words,
        "organization_locations": ["United States"],
        "page": page, "per_page": per_page,
    }
    r = _request("POST", "/apollo-organization-search", timeout=60, json=body)
    orgs = _rows(r)
    out = []
    for o in orgs:
        if not isinstance(o, dict) or not o.get("name"):
            continue
        dom = o.get("primary_domain") or o.get("domain") or \
            re.sub(r"^https?://(www\.)?|/.*$", "", o.get("website_url") or "")
        emp = o.get("estimated_num_employees")
        kw = o.get("keywords") or []
        out.append({
            "company": o["name"],
            "domain": dom,
            "what_they_do": (o.get("short_description") or "")[:300],
            "category": o.get("industry") or (kw[0] if kw else ""),
            "employees": emp,
            "signal": f"Apollo match: {', '.join(words)[:80]}"
                      + (f" · ~{emp} staff" if emp else ""),
            "source_url": o.get("website_url") or (f"https://{dom}" if dom else ""),
            "score": None,
        })
    return out


# ── Rival exhibitors via a signal ─────────────────────────────────────────────
# run-signal is account-scoped, but the account can be the rival EVENT's own
# website: the signal reads that site plus the web and lists who exhibits.
def _rival_label() -> str:
    return f"SDR Agent - Event Exhibitors ({SIGNAL_VERSION})"


def ensure_rival_signal() -> str:
    label = _rival_label()
    prompt = (
        "{{.AccountName}} ({{.AccountWebsite}}) runs a conference or trade show. "
        "Search the web and this website for its most recent sponsor and exhibitor "
        "list. Return ONLY a JSON array of company names, e.g. "
        '["Acme Corp","Globex"]. Up to 60 names. No commentary.'
    )
    config = {"type": "gpt", "prompt": prompt, "is_account_insight": True,
              "can_use_web_search": True, "expiration_in_days": 30,
              "temperature": 0.1, "word_limit": 300}
    r = _request("GET", "/signals?is_computed_column=true")
    for s in _rows(r):
        if isinstance(s, dict) and s.get("label") == label:
            return s.get("id")
    r = _request("POST", "/signal", json={"label": label, "is_computed_column": True,
                                          "type": "text", "computed_config": config})
    sid = (r.json() or {}).get("id")
    if not sid:
        raise TigaError("Tiga accepted the exhibitor signal but returned no id.")
    return sid


def rival_exhibitors(event_domain: str) -> list:
    sid = ensure_rival_signal()
    raw = run_on_account(sid, event_domain)
    try:
        names = ai._parse_json(raw)
    except Exception:
        names = [n.strip(" -•*\"'") for n in re.split(r"[\n,]", raw) if n.strip()]
    return [n for n in names if isinstance(n, str) and 1 < len(n) < 80]
