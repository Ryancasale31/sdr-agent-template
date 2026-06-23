"""
FSE Prospecting Radar
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


def get_all_known_companies() -> set:
    known = set()
    for entry in load_json(PIPELINE_FILE, []):
        name = entry.get("company", "").strip()
        if name:
            known.add(name.lower())
    for entry in load_json(SCORED_FILE, []):
        name = entry.get("company", "").strip()
        if name:
            known.add(name.lower())
    for entry in load_json(RADAR_FILE, []):
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


def add_to_pipeline(finds: list, min_score: int = 60) -> int:
    pipeline = _github_load("pipeline.json") or load_json(PIPELINE_FILE, [])
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
        save_json(PIPELINE_FILE, pipeline)
        if GITHUB_TOKEN:
            ok = _github_save("pipeline.json", pipeline)
            print(f"  -> GitHub sync: {'OK' if ok else 'failed (saved locally)'}")
    return added


# ── Main radar logic ──────────────────────────────────────────────────────────

def run_radar(auto_add: bool = False, auto_add_min_score: int = 60):
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        print("[!] TAVILY_API_KEY not set in .env")
        sys.exit(1)

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] FSE Radar starting...")
    print(f"  {len(SEARCH_QUERIES)} queries | search_depth=advanced | max_results=8 per query")
    if auto_add:
        print(f"  Auto-add ON — score >= {auto_add_min_score} goes straight to pipeline")

    tavily = TavilyClient(api_key=tavily_key)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    all_known = get_all_known_companies()
    print(f"  {len(all_known)} known companies loaded (pipeline + scored + prior radar)\n")

    existing_finds = load_json(RADAR_FILE, [])
    new_finds = []
    total_searched = 0

    for i, query in enumerate(SEARCH_QUERIES, 1):
        try:
            print(f"  [{i}/{len(SEARCH_QUERIES)}] {query[:70]}...")
            results = tavily.search(
                query=query,
                max_results=8,           # up from 5
                search_depth="advanced", # up from basic — richer content
            )
            web_text = "\n\n".join([
                f"URL: {r.get('url','')}\n{r.get('content','')}"
                for r in results.get("results", [])
            ])
            if not web_text.strip():
                continue

            total_searched += 1
            prompt = SCORE_PROMPT.format(
                search_results=web_text[:4000],
            )
            message = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=2000,          # up from 1000 — room for more finds
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
                print(f"    + {name} (score {company.get('score')}, Tier {company.get('tier','?')}) — {company.get('signal','')[:60]}")

        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(f"    ! Error on query {i}: {e}")
            continue

    # ── Auto-add to pipeline ──────────────────────────────────────────────────
    if auto_add and new_finds:
        to_add = [f for f in new_finds if f.get("score", 0) >= auto_add_min_score]
        if to_add:
            print(f"\n  Adding {len(to_add)} finds to pipeline...")
            n = add_to_pipeline(to_add, min_score=auto_add_min_score)
            for f in new_finds:
                if f.get("score", 0) >= auto_add_min_score:
                    f["reviewed"] = True
                    f["auto_added"] = True
            print(f"  {n} companies added")

    # ── Persist radar_finds.json (permanent log) ──────────────────────────────
    existing_map = {c["company"].lower(): c for c in existing_finds}
    for f in new_finds:
        key = f["company"].lower()
        if key not in existing_map:
            existing_map[key] = f
        else:
            existing_map[key].update(f)

    all_finds = list(existing_map.values())
    all_finds.sort(key=lambda x: x.get("score", 0), reverse=True)
    save_json(RADAR_FILE, all_finds)

    if GITHUB_TOKEN:
        _github_save("radar_finds.json", all_finds)

    unreviewed = [c for c in all_finds if not c.get("reviewed")]
    print(f"\n[OK] Done — {len(new_finds)} new companies found across {total_searched} queries")
    print(f"[OK] {len(unreviewed)} unreviewed finds in radar_finds.json")
    if auto_add:
        print(f"[OK] {len([f for f in new_finds if f.get('auto_added')])} auto-added to pipeline")
    return new_finds


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FSE Prospecting Radar")
    parser.add_argument("--auto-add", action="store_true",
                        help="Auto-add finds (score >= min-score)