"""
One-click check of every data source the SDR agent can use instead of Claude.
Writes everything to connection_test_results.txt (no API keys are written).

Costs: at most 1 Seamless reveal credit and 1 Tiga enrichment, plus one Tiga
signal run. Run with --free to skip anything that spends credits.
"""
import json, os, sys, time, traceback
try:
    import requests
except ImportError:
    sys.exit("pip install requests python-dotenv")
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

FREE = "--free" in sys.argv
OUT = open("connection_test_results.txt", "w", encoding="utf-8")
def log(*a):
    s = " ".join(str(x) for x in a)
    print(s); OUT.write(s + "\n"); OUT.flush()

def shape(obj, depth=0):
    """Field names and types only, so we learn the response format."""
    if isinstance(obj, dict):
        return {k: shape(v, depth+1) if depth < 2 else type(v).__name__ for k, v in list(obj.items())[:40]}
    if isinstance(obj, list):
        return [shape(obj[0], depth+1)] if obj else []
    return type(obj).__name__

def section(name):
    log("\n" + "=" * 70 + f"\n{name}\n" + "=" * 70)

def run(name, fn):
    log(f"\n--- {name}")
    try:
        fn()
    except Exception as e:
        log("EXCEPTION:", repr(e)); log(traceback.format_exc()[-800:])

TIGA = os.getenv("TIGA_API_KEY", ""); SEAM = os.getenv("SEAMLESS_API_KEY", ""); ANT = os.getenv("ANTHROPIC_API_KEY", "")
TB = "https://app.tigalabs.com"
TH = {"X-Tiga-Auth": TIGA, "Content-Type": "application/json"}
log(f"Run at {time.ctime()}  free_mode={FREE}")
log(f"keys present: tiga={bool(TIGA)} seamless={bool(SEAM)} (len {len(SEAM)}) anthropic={bool(ANT)}")

# ---------------------------------------------------------------- Anthropic
section("ANTHROPIC")
def t_ant():
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=30,
        headers={"x-api-key": ANT, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-haiku-4-5", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]})
    log("status", r.status_code, r.text[:200])
run("tiny message", t_ant)

# ---------------------------------------------------------------- Tiga
section("TIGA")
state = {}
def t_signals():
    r = requests.get(f"{TB}/api/v1/signals?is_computed_column=true", headers=TH, timeout=30)
    log("status", r.status_code)
    rows = r.json() if r.ok else []
    log("count", len(rows) if isinstance(rows, list) else rows)
    for s in (rows or [])[:60]:
        cfg = s.get("computed_config") or {}
        log(f"  [{cfg.get('type')}] {s.get('label')}  id={s.get('id')} words={cfg.get('word_limit')} web={cfg.get('can_use_web_search')}")
        if (s.get("label") or "").startswith("SDR Agent - Sponsor Fit"):
            state["sig"] = s.get("id")
run("list signals", t_signals)

def t_people():
    r = requests.get(f"{TB}/api/v1/people", timeout=30,
                     headers={**TH, "Tiga-Filter": json.dumps({"search_term": "ServiceTitan"})})
    log("status", r.status_code)
    d = r.json() if r.ok else r.text[:300]
    rows = d if isinstance(d, list) else (d.get("rows") if isinstance(d, dict) else [])
    log("rows", len(rows or []))
    if rows:
        log("shape", json.dumps(shape(rows[0]))[:1500])
        for p in rows[:5]:
            log(f"  {p.get('first_name')} {p.get('last_name')} | {p.get('title')} | {p.get('account_name')} | email={bool(p.get('email_address'))}")
        state["person"] = rows[0]
run("people DB search (ServiceTitan)", t_people)

def t_apollo():
    for body in ({"q_organization_keyword_tags": ["field service management"], "organization_locations": ["United States"], "page": 1, "per_page": 10},
                 {"q_keywords": "field service management software", "page": 1, "per_page": 10}):
        r = requests.post(f"{TB}/api/v1/apollo-organization-search", headers=TH, json=body, timeout=60)
        log("body", list(body), "-> status", r.status_code)
        if not r.ok:
            log(r.text[:300]); continue
        d = r.json()
        log("shape", json.dumps(shape(d))[:1500])
        orgs = d.get("organizations") or d.get("accounts") or (d if isinstance(d, list) else [])
        for o in orgs[:10]:
            log(f"  {o.get('name')} | {o.get('primary_domain') or o.get('website_url')} | emp={o.get('estimated_num_employees')}")
run("apollo org search (field service management)", t_apollo)

def t_find_people():
    desc = "VP Marketing, Director of Marketing, Head of Events or CMO at ServiceTitan, based in the United States"
    r = requests.post(f"{TB}/api/v1/agent/find-people", headers=TH, timeout=60,
                      json={"contact_description": desc, "model": "gpt-5.4-2026-03-05"})
    log("submit status", r.status_code, r.text[:300])
    if not r.ok: return
    jid = r.json().get("id") or r.json().get("status_id")
    t0 = time.time()
    while time.time() - t0 < 300:
        time.sleep(8)
        p = requests.get(f"{TB}/api/agent/find-people/{jid}/status", headers=TH, timeout=30)
        d = p.json() if p.ok else {}
        st = d.get("status", "")
        if st and st != "Running":
            log(f"finished in {int(time.time()-t0)}s status={st}")
            log("shape", json.dumps(shape(d))[:1500])
            return
    log("timed out after 300s")
run("find-people agent (async)", t_find_people)

def t_enrich():
    if FREE: log("skipped (free mode)"); return
    p = state.get("person")
    if not p: log("no person from DB search to enrich"); return
    r = requests.post(f"{TB}/api/v1/people/enrich-person", headers=TH, timeout=60, json={
        "first_name": p.get("first_name", ""), "last_name": p.get("last_name", ""),
        "company_name": p.get("account_name", ""), "title": p.get("title", ""),
        "person_linkedin_url": p.get("linkedin_url") or p.get("person_linkedin", "")})
    log("submit", r.status_code, r.text[:200])
    eid = r.json().get("enrich_id") if r.ok else None
    t0 = time.time()
    while eid and time.time() - t0 < 180:
        time.sleep(5)
        q = requests.get(f"{TB}/api/v1/enrich/{eid}", headers=TH, timeout=30)
        d = q.json() if q.ok else {}
        if d.get("data_import_status", "Running") != "Running":
            log(f"done in {int(time.time()-t0)}s status={d.get('data_import_status')} email={bool(d.get('email_address'))} phone={bool(d.get('phone'))}")
            log("shape", json.dumps(shape(d))[:1200]); return
    log("enrich timed out / no id")
run("waterfall enrich 1 person", t_enrich)

def t_signal():
    sid = state.get("sig")
    if not sid: log("no SDR Agent research signal exists yet (the app creates it on first research)"); return
    if FREE: log("skipped (free mode)"); return
    t0 = time.time()
    r = requests.post(f"{TB}/api/v1/signal/{sid}/run-signal", headers=TH, timeout=200,
                      json={"account": {"domain": "servicetitan.com"}})
    log("status", r.status_code, f"{int(time.time()-t0)}s")
    d = r.json() if r.ok else {}
    col = ((d.get("account") or {}).get("custom_columns") or {}).get(sid) or {}
    log("col status", col.get("status")); log("value:", str(col.get("value"))[:1500])
run("run research signal on servicetitan.com", t_signal)

# ---------------------------------------------------------------- Seamless
section("SEAMLESS")
SB = "https://api.seamless.ai/api/client/v1"
payload = {"companyName": ["ServiceTitan"], "jobTitle": ["VP Marketing", "Director of Marketing", "CMO", "Head of Events"],
           "seniority": ["VP", "Director", "C-Level"], "contactCountry": ["United States"], "limit": 5}
def t_seam():
    for label, h in (("Token header", {"Token": SEAM}), ("Bearer", {"Authorization": f"Bearer {SEAM}"})):
        r = requests.post(f"{SB}/search/contacts", headers={**h, "Content-Type": "application/json"}, json=payload, timeout=30)
        log(f"{label}: status {r.status_code}")
        if r.ok:
            state["seam_h"] = h
            d = r.json(); log("shape", json.dumps(shape(d))[:1500])
            rows = d.get("data") or []
            for c in rows[:5]:
                log(f"  {c.get('name') or c.get('firstName')} | {c.get('title')} | {c.get('company') or c.get('companyName')} | li={bool(c.get('liUrl'))}")
            state["seam_rows"] = rows
            return
        log("  ", r.text[:300])
run("contact search (ServiceTitan)", t_seam)

def t_seam_co():
    h = state.get("seam_h")
    if not h: log("skipped, search auth failed"); return
    r = requests.post(f"{SB}/search/companies", headers={**h, "Content-Type": "application/json"}, timeout=30,
                      json={"keywords": ["field service management"], "limit": 10})
    log("status", r.status_code, r.text[:200] if not r.ok else "")
    if r.ok:
        d = r.json(); log("shape", json.dumps(shape(d))[:1200])
        for c in (d.get("data") or [])[:10]:
            log(f"  {c.get('name') or c.get('companyName')} | {c.get('domain') or c.get('website')}")
run("company search (field service management)", t_seam_co)

def t_seam_reveal():
    if FREE: log("skipped (free mode)"); return
    rows = state.get("seam_rows") or []; h = state.get("seam_h")
    if not rows: log("nothing to reveal"); return
    sid = rows[0].get("searchResultId")
    r = requests.post(f"{SB}/contacts/research", headers={**h, "Content-Type": "application/json"}, json={"searchResultIds": [sid]}, timeout=30)
    log("submit", r.status_code, r.text[:300])
    if not r.ok: return
    ids = r.json().get("requestIds") or []
    t0 = time.time()
    while ids and time.time() - t0 < 90:
        time.sleep(4)
        p = requests.get(f"{SB}/contacts/research", headers=h, params={"requestIds": ",".join(ids)}, timeout=30)
        if not p.ok: log("poll", p.status_code, p.text[:200]); continue
        d = p.json(); data = d.get("data") or []
        if data and all((x.get("status") or "").lower() not in ("pending", "running", "") for x in data):
            log(f"done in {int(time.time()-t0)}s"); log("shape", json.dumps(shape(d))[:1500])
            ct = data[0].get("contact") or {}
            log("email found:", bool(ct.get("email") or ct.get("email1")))
            return
    log("reveal did not finish in 90s")
run("reveal 1 contact (1 credit)", t_seam_reveal)

log("\nALL DONE. Tell Claude it finished.")
OUT.close()
