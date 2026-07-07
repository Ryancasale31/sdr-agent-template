"""Debug — test search_people_at_company for IFS."""
import os, requests, json
from dotenv import load_dotenv
load_dotenv()

KEY = os.getenv('TIGA_API_KEY')
HEADERS = {'X-Tiga-Auth': KEY, 'Content-Type': 'application/json'}
BASE = 'https://app.tigalabs.com'

resp = requests.get(f'{BASE}/api/v1/people',
    headers={**HEADERS, 'Tiga-Filter': json.dumps({"search_term": "IFS"})})
data = resp.json()
rows = data if isinstance(data, list) else (data.get("rows") or [])
print(f"Total rows: {len(rows)}")

# Show title matches
keywords = ["vp marketing","vice president marketing","director marketing","director of marketing",
    "vp partnerships","head of marketing","chief marketing","cmo","vp sales","vice president sales",
    "director partnerships","marketing director","marketing vp"]

matched = []
for p in rows:
    acct = (p.get("account_name") or "").lower()
    title = (p.get("title") or "").lower()
    name_match = "ifs" in acct
    title_match = any(kw in title for kw in keywords)
    print(f"  acct='{p.get('account_name')}' title='{p.get('title')}' name_match={name_match} title_match={title_match}")
    if name_match and title_match:
        matched.append(p)

print(f"\nMatched: {len(matched)}")
