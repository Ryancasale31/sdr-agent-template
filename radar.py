"""
FSE Prospecting Radar
Searches daily for new sponsor targets and adds them to radar_finds.json for review.
Run manually: python radar.py
Scheduled:    runs via Windows Task Scheduler every morning
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import anthropic
from tavily import TavilyClient

load_dotenv()

PIPELINE_FILE = "pipeline.json"
RADAR_FILE = "radar_finds.json"
ICP_FILE = "icp_summary.json"

# ── Search queries that surface new sponsor targets ───────────────────────────
SEARCH_QUERIES = [
    # Event attendance signals
    "company attending Field Service USA 2025 sponsor exhibitor",
    "company exhibiting Field Service Medical 2025 conference",
    "field service management conference 2025 sponsor exhibitor",
    "WBR field service event 2025 attending sponsor",

    # Product/expansion signals
    "field service management software launch 2025 announcement",
    "field service operations platform new product 2025",
    "predictive maintenance software company expansion 2025",
    "AR remote assistance field service announcement 2025",
    "service parts planning software company 2025",

    # Hiring signals (companies investing in field service)
    "company hiring director field service operations 2025",
    "field service technology company hiring VP service 2025",

    # Competitor discovery
    "competitors ServiceMax IFS field service management software",
    "alternatives Aquant service AI technician intelligence",
    "field service scheduling optimization software vendors 2025",
]

SCORE_PROMPT = """You are a sponsorship analyst for Field Service East (Orlando, Aug 10-12, 2025).

EVENT BUYER PROFILE:
- 133 registered buyers, 61% VP/Director/SVP level
- Industries: Industrial/Manufacturing Equipment (41), Medical/Life Sciences (30), Tech/IT (17), Utilities (13)
- Top companies: Oxford Instruments, Toshiba, MC Dean, BlueCrest, Henny Penny, ABB, Siemens Healthineers, Zimmer Biomet
- Top titles: Director of Field Service, VP Service, SVP Service, Regional Service Manager
- Already sponsoring: Salesforce, PTC, GoFormz, Neuron7, HSO, Baxter Planning, Squint, Circuitry.ai

WEB SEARCH RESULTS:
{search_results}

EXISTING PIPELINE COMPANIES (do not suggest these):
{existing_companies}

From the search results, identify NEW companies that should be added to this sponsorship pipeline.
Only include companies that:
1. Sell technology or services TO field service directors/operations leaders
2. Are NOT already in the existing pipeline
3. Are real, identifiable companies (not generic references)

Return ONLY valid JSON array (empty array if nothing qualifies):
[
  {{
    "company": "Company Name",
    "what_they_do": "1-2 sentence description",
    "category": "FSM Platform / AI for Service / AR Tech / Parts Planning / IoT / Workforce / Training / Other",
    "score": <0-100>,
    "tier": "<A|B|C>",
    "fit_reason": "Why they fit this audience",
    "pitch_angle": "Best angle to sell them a sponsorship",
    "signal": "What triggered this find (e.g. 'attending similar event', 'product launch', 'competitor of X')",
    "source_url": "URL where this was found if available",
    "status": "radar_find"
  }}
]
"""


def load_json(path, default):
    if not Path(path).exists():
        return default
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_existing_companies(pipeline):
    return set(c["company"].lower() for c in pipeline)


def is_duplicate(name: str, known: set) -> bool:
    """Exact match plus fuzzy: catch 'IFS AB' when 'IFS' is known, etc."""
    n = name.lower().strip()
    if n in known:
        return True
    # Check if any known name is contained in this name or vice versa (word-level)
    n_words = set(n.split())
    for k in known:
        k_words = set(k.split())
        # Significant word overlap (ignoring tiny words)
        sig = {w for w in n_words | k_words if len(w) > 3}
        if not sig:
            continue
        overlap = {w for w in n_words if len(w) > 3} & {w for w in k_words if len(w) > 3}
        if overlap and len(overlap) / min(len({w for w in n_words if len(w) > 3} or {" "}), len({w for w in k_words if len(w) > 3} or {" "})) >= 0.6:
            return True
    return False


def run_radar():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] FSE Radar starting...")

    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    pipeline = load_json(PIPELINE_FILE, [])
    existing_finds = load_json(RADAR_FILE, [])
    existing_names = get_existing_companies(pipeline)
    existing_radar = set(c["company"].lower() for c in existing_finds)
    all_known = existing_names | existing_radar

    new_finds = []
    total_searched = 0

    for query in SEARCH_QUERIES:
        try:
            print(f"  Searching: {query[:60]}...")
            results = tavily.search(
                query=query,
                max_results=5,
                search_depth="basic",
            )

            # Combine search snippets
            web_text = "\n\n".join([
                f"URL: {r.get('url','')}\n{r.get('content','')}"
                for r in results.get("results", [])
            ])

            if not web_text.strip():
                continue

            total_searched += 1

            # Ask Claude to extract companies from results
            prompt = SCORE_PROMPT.format(
                search_results=web_text[:3000],
                existing_companies=", ".join(sorted(all_known)),
            )

            message = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )

            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            found = json.loads(raw.strip())

            for company in found:
                name = company.get("company", "")
                if not name:
                    continue
                if is_duplicate(name, all_known):
                    continue
                if company.get("score", 0) < 60:
                    continue

                # Add metadata
                company["found_date"] = datetime.now().strftime("%Y-%m-%d")
                company["search_query"] = query
                company["reviewed"] = False

                new_finds.append(company)
                all_known.add(name.lower())
                print(f"  + Found: {name} (score: {company.get('score')}) — {company.get('signal','')}")

        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(f"  ! Error on query '{query[:40]}': {e}")
            continue

    # Merge with existing radar finds (keep unreviewed ones)
    unreviewed = [c for c in existing_finds if not c.get("reviewed")]
    merged = unreviewed + new_finds

    # Dedupe by company name
    seen = set()
    deduped = []
    for c in merged:
        key = c["company"].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    save_json(RADAR_FILE, deduped)

    print(f"\n[✓] Radar complete — {len(new_finds)} new companies found across {total_searched} searches")
    print(f"[✓] {len(deduped)} total unreviewed finds waiting in radar_finds.json")
    return new_finds


if __name__ == "__main__":
    finds = run_radar()
    if not finds:
        print("\nNo new companies found this run.")
    else:
        print(f"\nNew finds:")
        for f in finds:
            print(f"  [{f.get('tier','?')}] {f['company']} — {f.get('signal','')}")
