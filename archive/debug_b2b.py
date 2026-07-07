"""
Quick diagnostic — run from the fse_sdr_agent folder:
  python debug_b2b.py
"""
import sys, json
from pathlib import Path

print("=== B2B Atlanta Debug ===\n")

# 1. Check files exist
pipeline_path = Path(__file__).parent / "events" / "b2b-online-atlanta" / "pipeline.json"
icp_path      = Path(__file__).parent / "events" / "b2b-online-atlanta" / "icp_summary.json"
print(f"pipeline.json exists: {pipeline_path.exists()}  ({pipeline_path})")
print(f"icp_summary.json exists: {icp_path.exists()}  ({icp_path})")

if pipeline_path.exists():
    with open(pipeline_path) as f:
        p = json.load(f)
    print(f"Pipeline companies: {len(p)}")
    print(f"First 3: {[c['company'] for c in p[:3]]}")
else:
    print("ERROR: pipeline.json not found!")

# 2. Check storage module loads correctly
print("\n--- storage module ---")
try:
    import storage
    print(f"storage imported OK")
    pipe = storage._load_local_pipeline("b2b-online-atlanta")
    print(f"_load_local_pipeline result: {len(pipe)} companies")
except Exception as e:
    print(f"ERROR: {e}")

# 3. Check events registry
print("\n--- events registry ---")
try:
    from events_registry import EVENTS
    print(f"Events: {list(EVENTS.keys())}")
    print(f"B2B Atlanta in registry: {'b2b-online-atlanta' in EVENTS}")
except Exception as e:
    print(f"ERROR: {e}")

print("\nDone.")
