"""
WBR SDR Prospecting Radar — multi-event aware
Searches for new sponsor targets, auto-adds high-confidence finds to pipeline.json,
and syncs to GitHub so the app updates in real time.

Run manually:          python radar.py
Run with auto-add:     python radar.py --auto-add
Scheduled:             runs via Windows Task Scheduler every morning
"""
import json
import os
import sys
import base64
import argparse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import anthropic
import requests as http_requests
from tavily import TavilyClient

load_dotenv()


# ── Event-aware query + prompt builders ──────────────────────────────────────

def build_queries_from_event(event_cfg: dict, agenda_sessions: list = None, client=None) -> list:
    """
    Use Claude to generate 20-30 targeted search queries for this specific event,
    informed by the event focus, agenda session titles, and known sponsor categories.
    Falls back to keyword-based queries if Claude is unavailable.
    """
    event_name     = event_cfg.get("name", "the event")
    event_focus    = event_cfg.get("focus", "")
    search_keywords = event_cfg.get("search_keywords", "")

    # Pull session titles from agenda (first 40 to stay in token budget)
    session_titles = ""
    if agenda_sessions:
        titles = [s.get("session", "") for s in agenda_sessions[:40] if s.get("session")]
        session_titles = "\n".join(f"- {t}" for t in titles)

    if client and (session_titles or event_focus):
        # Build known-company exclusion hint
        known_big = event_cfg.get("_known_sponsors_hint", "")

        prompt = f"""You are a B2B sponsorship sales researcher. Generate 30 targeted web search queries to find EMERGING and NICHE companies that would want to sponsor {event_name}.

EVENT FOCUS: {event_focus}
SEARCH KEYWORDS: {search_keywords}

AGENDA SESSIONS (sample):
{session_titles or "(no agenda uploaded yet)"}

IMPORTANT: Skip the obvious household names (Shopify, SAP, Salesforce, Adobe, BigCommerce, Akeneo, Algolia, Coveo, Commercetools, PayPal, ServiceNow etc.) — focus on finding vendors that are less well-known but highly relevant.

Generate queries that specifically surface:
1. Funded STARTUPS and newer vendors (Series A/B/C) in B2B eCommerce, PIM, CPQ, AI commerce, payments, OMS
2. Niche specialists: B2B marketplace tech, guided selling, catalog AI, B2B personalization engines, D2C-to-B2B platforms
3. Emerging vendors at similar events: B2B Online Chicago, B2B Online Europe, CommerceNext, Shoptalk, IRCE exhibitors
4. Vendors hiring "Director of Sales - B2B" or "VP eCommerce Partnerships" — signals they sell to this audience
5. Competitors and alternatives to the big names above
6. Implementation partners and SIs with their own tech IP
7. G2, Capterra, and analyst lists for lesser-known B2B commerce sub-categories

Return ONLY a JSON array of 30 search query strings. No explanation.
["query 1", "query 2", ...]"""

        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            queries = json.loads(raw.strip())
            if isinstance(queries, list) and queries:
                return queries
        except Exception as e:
            print(f"  [Radar] Query generation failed, using fallback: {e}")

    # Fallback: build keyword-based queries from event config
    kw = search_keywords or event_focus
    return [
        f"{kw} software companies 2026",
        f"{kw} vendors sponsors conference 2026",
        f"best {kw} platforms list 2026",
        f"{event_name} exhibitors sponsors 2026",
        f"top companies selling to {event_name} audience",
        f"{kw} startup funding raised 2026",
        f"{kw} software alternatives comparison 2026",
        f"G2 {kw} top rated 2026",
        f"{kw} company hiring marketing director 2026",
        f"{kw} conference sponsor exhibitor list 2026",
    ]


def build_score_prompt(event_cfg: dict, icp: dict = None) -> str:
    event_name  = event_cfg.get("name", "the event")
    event_loc   = event_cfg.get("location", "")
    event_dates = event_cfg.get("dates", "2026")
    event_focus = event_cfg.get("focus", "")

    buyer_count  = icp.get("buyer_count", "hundreds of")     if icp else "hundreds of"
    senior_pct   = icp.get("senior_buyer_pct", "60")         if icp else "60"
    top_cos      = ", ".join(icp.get("top_companies", [])[:8]) if icp else "leading companies in this space"
    top_titles   = ", ".join(icp.get("top_titles", [])[:6])   if icp else "VP, Director, SVP level leaders"
    existing_sp  = ", ".join(set(icp.get("existing_sponsors", []))) if icp else "various sponsors"

    return f"""You are a sponsorship sales analyst for {event_name} ({event_loc}, {event_dates}), a premium B2B conference.

EVENT FOCUS: {event_focus}

EVENT BUYER PROFILE (the people attending):
- {buyer_count} registered buyers, {senior_pct}% VP/Director/SVP level
- Top attending companies: {top_cos}
- Key buyer titles: {top_titles}
- Already confirmed sponsors (do NOT suggest): {existing_sp}

IDEAL SPONSOR PROFILE:
A company that sells software, technology, or services TO the leaders attending this event.
They want access to buyers who make purchasing decisions in: {event_focus}.

WEB SEARCH RESULTS:
{{search_results}}

TASK: From the search results, extract ALL companies that:
1. Sell tech/services TO the audience at this event (not the attendees themselves)
2. Are real, named companies (not generic descriptions)
3. Would genuinely benefit from sponsoring this event

Score 70-85 for solid fits, 85-100 for ideal fits only.

Return ONLY a valid JSON array ([] if nothing qualifies):
[
  {{
    "company": "Exact Company Name",
    "what_they_do": "One clear sentence describing their product/service",
    "category": "Platform / AI / Analytics / Commerce / Marketing / Other",
    "score": <70-100>,
    "tier": "<A|B|C>",
    "fit_reason": "Why they fit this specific audience",
    "pitch_angle": "One-line hook for the sponsorship pitch",
    "signal": "What triggered this find",
    "source_url": "Source URL if available",
    "status": "radar_find"
  }}
]
"""

PIPELINE_FILE = "pipeline.json"
SCORED_FILE = "scored_companies.json"
RADAR_FILE = "radar_finds.json"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Ryancasale31/sdr-agent-template")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "data")
GITHUB_API = "https://api.github.com"

# ── Search queries ─────────────────────────────────────────────────────────────
# Grouped by signal type for broad coverage
SEARCH_QUERIES = [
    # ── Event / conference signals ──
    "company sponsoring Field Service USA 2026 exhibitor list",
    "company exhibiting Field Service Medical 2026 sponsor",
    "field service management conference 2026 exhibitors sponsors",
    "WBR field service east 2026 sponsor partner",
    "Copperberg field service forum 2026 sponsors",
    "Field Service Connect 2026 exhibitors sponsors",

    # ── Competitor / category discovery ──
    "top field service management software companies 2026",
    "best FSM software alternatives to ServiceMax IFS 2026",
    "competitors to Salesforce Field Service Lightning 2026",
    "alternatives to Aquant service AI 2026",
    "competitors to PTC ServiceMax field service software",
    "field service scheduling optimization software vendors 2026",
    "predictive maintenance software companies list 2026",
    "AR remote assistance field service tools 2026",
    "AI-powered field service management platforms 2026",

    # ── Review sites / analyst lists ──
    "G2 field service management software top rated 2026",
    "Capterra best field service management software 2026",
    "Gartner field service management vendors 2026",
    "Forrester field service technology vendors 2026",
    "best service parts planning optimization software 2026",

    # ── Funding / growth signals ──
    "field service software company funding raised 2026",
    "field service technology startup series funding 2026",
    "workforce management field service company investment 2026",

    # ── Hiring signals ──
    "company hiring VP field service marketing 2026",
    "field service software company hiring sales director 2026",

    # ── Vertical-specific ──
    "medical device field service software companies 2026",
    "utilities field workforce management software vendors 2026",
    "industrial equipment service management platform 2026",
    "knowledge management field technician software 2026",
    "technician scheduling route optimization software 2026",

    # ── Adjacent / expansion signals ──
    "IoT predictive maintenance platform field service 2026",
    "digital twin field service management software 2026",
    "remote monitoring field service software company 2026",
]

SCORE_PROMPT = """You are a sponsorship sales analyst for Field Service Next East (Orlando, FL, 2026), a premium B2B conference.

EVENT BUYER PROFILE (the people attending):
- 133 registered buyers, 61% VP/Director/SVP level
- Industries: Industrial/Manufacturing Equipment (41 buyers), Medical/Life Sciences (30), Tech/IT (17), Utilities (13)
- Top attending companies: Oxford Instruments, Toshiba, MC Dean, BlueCrest, Henny Penny, ABB, Siemens Healthineers, Zimmer Biomet
- Key buyer titles: Director of Field Service, VP Service Operations, SVP Service, Regional Service Manager, Director of Technical Services
- Already confirmed sponsors (do NOT suggest): Salesforce, PTC, GoFormz, Neuron7, HSO, Baxter Planning, Squint, Circuitry.ai

IDEAL SPONSOR PROFILE:
A company that sells software, technology, or services TO the field service leaders attending. Think:
- FSM platforms (scheduling, dispatch, work orders)
- AI/ML for service operations (knowledge, diagnostics, predictions)
- Parts planning and inventory optimization
- AR/remote assistance for technicians
- IoT and predictive maintenance
- Workforce management and technician scheduling
- Training and knowledge management for field teams
- Service analytics and reporting

WEB SEARCH RESULTS:
{search_results}

TASK: From the search results above, extract ALL companies that:
1. Sell tech/services TO field service operations leaders (not the field service companies themselves)
2. Are real, named companies (not generic descriptions)
3. Would genuinely benefit from sponsoring this event

Be aggressive — include anything relevant. Do NOT try to filter against any existing list; that is handled separately.
Score 70-85 for solid fits, 85-100 for ideal fits only.

Return ONLY a valid JSON array ([] if nothing qualifies):
[
  {{
    "company": "Exact Company Name",
    "what_they_do": "One clear sentence describing their product/service",
    "category": "FSM Platform / AI for Service / AR Tech / Parts Planning / IoT / Workforce / Training / Analytics / Other",
    "score": <70-100>,
    "tier": "<A|B|C>",
    "fit_reason": "Specific reason they fit this audience — mention which buyer titles or industries would want them",
    "pitch_angle": "One-line hook for the sponsorship pitch",
    "signal": "What triggered this find",
    "source_url": "Source URL if available",
    "status": "radar_find"
  }}
]
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path, default):
    if not Path(path).exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_all_known_companies(event_id: str = None) -> set:
    known = set()
    # Load event-specific pipeline from GitHub if event_id provided
    if event_id and event_id != "field-service-east":
        gh_pipeline = _github_load(f"events/{event_id}/pipeline.json")
        source = gh_pipeline if gh_pipeline is not None else []
    else:
        gh_pipeline = _github_load("pipeline.json")
        source = gh_pipeline if gh_pipeline is not None else load_json(PIPELINE_FILE, [])
    for entry in source:
        name = entry.get("company", "").strip()
        if name:
            known.add(name.lower())
    # Always also include FSE scored + radar finds to avoid cross-event noise
    for entry in load_json(SCORED_FILE, []):
        name = entry.get("company", "").strip()
        if name:
            known.add(name.lower())
    radar_file = f"{event_id}_radar_finds.json" if event_id else RADAR_FILE
    for entry in load_json(radar_file, []):
        name = entry.get("company", "").strip()
        if name:
            known.add(name.lower())
    return known


def _normalize(name: str) -> str:
    """Lowercase, strip punctuation/suffixes for comparison."""
    import re
    n = name.lower().strip()
    # Remove common suffixes
    n = re.sub(r'\b(inc|llc|ltd|corp|co|plc|gmbh|ag|bv|sa|sas|pty|pte)\b\.?', '', n)
    # Remove parenthetical alternate names like "(now Salesforce)"
    n = re.sub(r'\(.*?\)', '', n)
    # Strip punctuation except spaces
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
        # Substring check — only when both normalized names are 6+ chars
        if len(k_norm) >= 6 and len(n) >= 6:
            if k_norm in n or n in k_norm:
                return True
        # Word-level overlap — ≥70% of the shorter name's words match
        k_words = {w for w in k_norm.split() if len(w) > 3 and w not in STOP_WORDS}
        if len(n_words) >= 1 and len(k_words) >= 1:
            overlap = n_words & k_words
            smaller = min(len(n_words), len(k_words))
            if smaller > 0 and len(overlap) / smaller >= 0.7:
                return True
    return False


# ── GitHub sync ───────────────────────────────────────────────────────────────

def _gh_headers():
    return {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}


def _github_save(filename: str, data: list) -> bool:
    if not GITHUB_TOKEN:
        return False
    try:
        resp = http_requests.get(
            f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{filename}",
            params={"ref": GITHUB_BRANCH},
            headers=_gh_headers(),
            timeout=15,
        )
        sha = resp.json().get("sha") if resp.ok else None
        content = base64.b64encode(json.dumps(data, indent=2, ensure_ascii=False).encode()).decode()
        payload = {
            "message": f"Radar update: {filename} [{datetime.now().strftime('%Y-%m-%d %H:%M')}]",
            "content": content,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        put = http_requests.put(
            f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{filename}",
            headers=_gh_headers(),
            json=payload,
            timeout=15,
        )
        return put.ok
    except Exception as e:
        print(f"  [GitHub] Save failed: {e}")
        return False


def _github_load(filename: str):
    if not GITHUB_TOKEN:
        return None
    try:
        resp = http_requests.get(
            f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{filename}",
            params={"ref": GITHUB_BRANCH},
            headers=_gh_headers(),
            timeout=15,
        )
        if resp.ok:
            return json.loads(base64.b64decode(resp.json()["content"]).decode())
    except Exception:
        pass
    return None


# ── Pipeline helpers ──────────────────────────────────────────────────────────

def tier_str_to_int(tier: str) -> int:
    return {"A": 1, "B": 2, "C": 3}.get(str(tier).upper(), 2)


def radar_find_to_pipeline_entry(find: dict) -> dict:
    score = find.get("score", 70)
    return {
        "company": find["company"],
        "category": find.get("category", "Other"),
        "what_they_do": find.get("what_they_do", ""),
        "tier": tier_str_to_int(find.get("tier", "B")),
        "score": score,
        "priority": "hot" if score >= 80 else "medium" if score >= 60 else "low",
        "status": "researched",
        "source": "radar",
        "fit_reason": find.get("fit_reason", ""),
        "pitch_angle": find.get("pitch_angle", ""),
        "signal": find.get("signal", ""),
        "source_url": find.get("source_url", ""),
        "found_date": find.get("found_date", datetime.now().strftime("%Y-%m-%d")),
        "outreach_note": "",
        "contacts": [],
    }


def add_to_pipeline(finds: list, min_score: int = 60, event_id: str = None) -> int:
    gh_path = f"events/{event_id}/pipeline.json" if (event_id and event_id != "field-service-east") else "pipeline.json"
    local_path = PIPELINE_FILE
    pipeline = _github_load(gh_path) or load_json(local_path, [])
    existing = {e["company"].lower() for e in pipeline}
    added = 0
    for find in finds:
        name = find.get("company", "")
        if not name or name.lower() in existing:
            continue
        if find.get("score", 0) < min_score:
            continue
        pipeline.append(radar_find_to_pipeline_entry(find))
        existing.add(name.lower())
        added += 1
        print(f"  -> Pipeline: {name} (score {find.get('score')})")

    if added:
        pipeline.sort(key=lambda x: x.get("company", "").lower())
        save_json(local_path, pipeline)
        if GITHUB_TOKEN:
            ok = _github_save(gh_path, pipeline)
            print(f"  -> GitHub sync: {'OK' if ok else 'failed (saved locally)'}")
    return added


# ── Main radar logic ──────────────────────────────────────────────────────────

def run_radar(auto_add: bool = False, auto_add_min_score: int = 60,
              event_cfg: dict = None, agenda_sessions: list = None, icp: dict = None,
              event_id: str = None):
    """
    Run the prospecting radar.

    When called without event_cfg (e.g. from the FS
    When called without event_cfg (e.g. from the FSE scheduler), the original
    hardcoded FSE queries and prompt are used — no change to FSE behaviour.

    When called with event_cfg (e.g. from the B2B Atlanta app tab), event-aware
    queries and a dynamic scoring prompt are generated from the agenda + ICP.
    """
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        print("[!] TAVILY_API_KEY not set in .env")
        raise RuntimeError("TAVILY_API_KEY is not set in Streamlit secrets")

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if event_cfg:
        event_name = event_cfg.get("name", "the event")
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Radar starting for: {event_name}")
        queries    = build_queries_from_event(event_cfg, agenda_sessions, client)
        score_tmpl = build_score_prompt(event_cfg, icp)
    else:
        event_name = "Field Service East"
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] FSE Radar starting...")
        queries    = SEARCH_QUERIES
        score_tmpl = SCORE_PROMPT

    print(f"  {len(queries)} queries | search_depth=basic | max_results=8 per query")
    if auto_add:
        print(f"  Auto-add ON — score >= {auto_add_min_score} goes straight to pipeline")

    tavily = TavilyClient(api_key=tavily_key)
    all_known = get_all_known_companies(event_id=event_id)
    print(f"  {len(all_known)} known companies loaded\n")

    radar_file = f"{event_id}_radar_finds.json" if event_id else RADAR_FILE
    existing_finds = load_json(radar_file, [])
    new_finds = []
    total_searched = 0

    for i, query in enumerate(queries, 1):
        try:
            print(f"  [{i}/{len(queries)}] {query[:70]}...")
            results = tavily.search(query=query, max_results=8, search_depth="basic")
            web_text = "\n\n".join([f"URL: {r.get('url','')}\n{r.get('content','')}" for r in results.get("results", [])])
            if not web_text.strip():
                continue
            total_searched += 1
            prompt = score_tmpl.replace("{search_results}", web_text[:4000]).replace("{{", "{").replace("}}", "}")
            message = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            found = json.loads(raw.strip())
            for company in found:
                name = company.get("company", "").strip()
                if not name:
                    continue
                if is_duplicate(name, all_known):
                    print(f"    ~ Duplicate: {name}")
                    continue
                company["found_date"] = datetime.now().strftime("%Y-%m-%d")
                company["search_query"] = query
                company["reviewed"] = False
                new_finds.append(company)
                all_known.add(name.lower())
                print(f"    + {name} (score {company.get('score')}, Tier {company.get('tier','?')})")
        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(f"    ! Error on query {i}: {e}")
            continue

    if auto_add and new_finds:
        to_add = [f for f in new_finds if f.get("score", 0) >= auto_add_min_score]
        if to_add:
            print(f"\n  Adding {len(to_add)} finds to pipeline...")
            n = add_to_pipeline(to_add, min_score=auto_add_min_score, event_id=event_id)
            for f in new_finds:
                if f.get("score", 0) >= auto_add_min_score:
                    f["reviewed"] = True
                    f["auto_added"] = True
            print(f"  {n} companies added")

    existing_map = {c["company"].lower(): c for c in existing_finds}
    for f in new_finds:
        key = f["company"].lower()
        if key not in existing_map:
            existing_map[key] = f
        else:
            existing_map[key].update(f)

    all_finds = list(existing_map.values())
    all_finds.sort(key=lambda x: x.get("score", 0), reverse=True)
    save_json(radar_file, all_finds)
    if GITHUB_TOKEN:
        _github_save(radar_file, all_finds)

    unreviewed = [c for c in all_finds if not c.get("reviewed")]
    print(f"\n[OK] Done — {len(new_finds)} new companies found across {total_searched} queries")
    print(f"[OK] {len(unreviewed)} unreviewed finds in radar_finds.json")
    if auto_add:
        print(f"[OK] {len([f for f in new_finds if f.get('auto_added')])} auto-added to pipeline")
    return new_finds


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WBR Prospecting Radar")
    parser.add_argument("--auto-add", action="store_true")
    parser.add_argument("--min-score", type=int, default=60)
    args = parser.parse_args()
    finds = run_radar(auto_add=args.auto_add, auto_add_min_score=args.min_score)
    if not finds:
        print("\nNo new companies found this run.")
    else:
        print(f"\nNew finds ({len(finds)}):")
        for f in finds:
            tag = "[AUTO-ADDED]" if f.get("auto_added") else "[pending review]"
            print(f"  [{f.get('tier','?')}] {f['company']} ({f.get('score','?')}) {tag}")
        if not args.auto_add:
            print("\nTip: run with --auto-add to send finds straight to pipeline")
