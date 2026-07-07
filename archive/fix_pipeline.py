"""
Run this once from the fse_sdr_agent folder to restore the full 90-company pipeline.
Usage: python fix_pipeline.py
"""
import json, base64, requests

# Load lapsed sponsors
with open("events/b2b-online-atlanta/pipeline.json") as f:
    lapsed = json.load(f)
print(f"Lapsed sponsors: {len(lapsed)}")

# Load radar finds
with open("b2b-online-atlanta_radar_finds.json") as f:
    radar = json.load(f)
print(f"Radar finds: {len(radar)}")

# Merge, no dupes
seen = {c["company"].lower() for c in lapsed}
new_finds = []
for c in radar:
    if c["company"].lower() not in seen:
        # tag source properly
        c["source"] = c.get("source") or "radar"
        seen.add(c["company"].lower())
        new_finds.append(c)

combined = lapsed + new_finds
combined.sort(key=lambda x: x.get("company","").lower())
print(f"Combined: {len(combined)}")

# Save locally
with open("events/b2b-online-atlanta/pipeline.json", "w") as f:
    json.dump(combined, f, indent=2)
print("Saved locally.")

# Push to GitHub
TOKEN = open('.env').read().split('GITHUB_TOKEN=')[1].split()[0].strip()
REPO = 'Ryancasale31/sdr-agent-template'
HDR = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
fpath = "events/b2b-online-atlanta/pipeline.json"
branch = "data"

r = requests.get(f'https://api.github.com/repos/{REPO}/contents/{fpath}',
                 params={'ref': branch}, headers=HDR, timeout=15)
sha = r.json().get('sha') if r.status_code == 200 else None

content = json.dumps(combined, indent=2)
body = {'message': f'Restore full pipeline: {len(combined)} companies (lapsed + radar)',
        'content': base64.b64encode(content.encode()).decode(), 'branch': branch}
if sha:
    body['sha'] = sha

r = requests.put(f'https://api.github.com/repos/{REPO}/contents/{fpath}',
                 json=body, headers=HDR, timeout=15)
if r.status_code in (200, 201):
    print(f"✓ Pushed {len(combined)} companies to GitHub successfully!")
else:
    print(f"✗ GitHub push failed: {r.status_code}: {r.text[:200]}")
