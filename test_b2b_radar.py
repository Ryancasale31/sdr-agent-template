"""
Run this in PowerShell to test the B2B Atlanta radar step-by-step:
  python test_b2b_radar.py
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()

print("=== B2B Atlanta Radar Diagnostic ===\n")

print(f"TAVILY_API_KEY:   {'SET' if os.getenv('TAVILY_API_KEY') else '*** MISSING ***'}")
print(f"ANTHROPIC_API_KEY:{'SET' if os.getenv('ANTHROPIC_API_KEY') else '*** MISSING ***'}")
print(f"GITHUB_TOKEN:     {'SET' if os.getenv('GITHUB_TOKEN') else '*** MISSING ***'}")
print()

from events_registry import EVENTS
event_cfg = EVENTS["b2b-online-atlanta"]
print(f"Event config loaded: {event_cfg['name']}")

import anthropic
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
print("Anthropic client created")

import radar as radar_module
print("radar.py imported OK")

print("\n[1] Building search queries via Claude...")
try:
    queries = radar_module.build_queries_from_event(event_cfg, None, client)
    print(f"    Got {len(queries)} queries. First: {queries[0][:60]}")
except Exception as e:
    print(f"    FAILED: {e}")
    sys.exit(1)

print("\n[2] Building score prompt...")
try:
    score_tmpl = radar_module.build_score_prompt(event_cfg, None)
    print(f"    Prompt built OK ({len(score_tmpl)} chars)")
    # Test the replace works
    test = score_tmpl.replace("{search_results}", "TEST_RESULTS").replace("{{", "{").replace("}}", "}")
    print(f"    Replace test OK")
except Exception as e:
    print(f"    FAILED: {e}")
    sys.exit(1)

print("\n[3] Loading known companies from GitHub...")
try:
    known = radar_module.get_all_known_companies(event_id="b2b-online-atlanta")
    print(f"    Loaded {len(known)} known companies")
except Exception as e:
    print(f"    FAILED: {e}")
    sys.exit(1)

print("\n[4] Test Tavily search (1 query)...")
try:
    from tavily import TavilyClient
    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    results = tavily.search(query=queries[0], max_results=3, search_depth="basic")
    print(f"    Got {len(results.get('results', []))} results")
except Exception as e:
    print(f"    FAILED: {e}")
    sys.exit(1)

print("\n=== All checks passed! Radar should work. ===")
