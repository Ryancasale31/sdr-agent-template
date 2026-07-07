"""
Run in PowerShell:  python debug_radar_b2b.py
Shows exactly what queries are generated, what Tavily returns, and what Claude scores.
"""
import os, json
from dotenv import load_dotenv
load_dotenv()

import anthropic
from tavily import TavilyClient
from events_registry import EVENTS
import radar as radar_module

event_cfg = EVENTS["b2b-online-atlanta"]
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
tavily  = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

print("=== [1] GENERATING QUERIES ===")
queries = radar_module.build_queries_from_event(event_cfg, None, client)
print(f"Got {len(queries)} queries:")
for i, q in enumerate(queries, 1):
    print(f"  {i}. {q}")

print("\n=== [2] KNOWN COMPANIES ===")
known = radar_module.get_all_known_companies(event_id="b2b-online-atlanta")
print(f"  {len(known)} known (will be skipped as duplicates)")

print("\n=== [3] RUNNING 3 SAMPLE QUERIES ===")
score_tmpl = radar_module.build_score_prompt(event_cfg, None)

for i, query in enumerate(queries[:3], 1):
    print(f"\n--- Query {i}: {query[:80]} ---")
    results = tavily.search(query=query, max_results=8, search_depth="basic")
    web_text = "\n\n".join([f"URL: {r.get('url','')}\n{r.get('content','')}" for r in results.get("results", [])])
    print(f"  Tavily returned {len(results.get('results',[]))} results, {len(web_text)} chars")

    if not web_text.strip():
        print("  -> Empty web results, skipping")
        continue

    prompt = score_tmpl.replace("{search_results}", web_text[:4000]).replace("{{", "{").replace("}}", "}")
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    print(f"  Claude raw response ({len(raw)} chars):")
    print(f"  {raw[:500]}")

    try:
        found = json.loads(raw if not raw.startswith("```") else raw.split("```")[1].lstrip("json").strip())
        print(f"  -> Parsed {len(found)} companies from Claude")
        for c in found:
            name = c.get("company","")
            is_dup = radar_module.is_duplicate(name, known)
            print(f"     {'[DUP]' if is_dup else '[NEW]'} {name} (score {c.get('score','?')})")
    except Exception as e:
        print(f"  -> JSON parse error: {e}")
        print(f"  -> Raw: {raw[:300]}")

print("\n=== DONE ===")
