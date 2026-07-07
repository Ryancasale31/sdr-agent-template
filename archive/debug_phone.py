"""Check what fields Tiga enrichment returns for an IFS contact."""
import os, requests, json, time
from dotenv import load_dotenv
load_dotenv()

KEY = os.getenv('TIGA_API_KEY')
HEADERS = {'X-Tiga-Auth': KEY, 'Content-Type': 'application/json'}
BASE = 'https://app.tigalabs.com'

# Get one IFS contact to enrich
resp = requests.get(f'{BASE}/api/v1/people',
    headers={**HEADERS, 'Tiga-Filter': json.dumps({"search_term": "IFS"})})
data = resp.json()
rows = data if isinstance(data, list) else (data.get("rows") or [])
keywords = ["vp marketing","director marketing","director of marketing","vp partnerships",
    "head of marketing","chief marketing","cmo","vp sales","director partnerships","marketing director"]
matched = [p for p in rows if any(kw in (p.get("title") or "").lower() for kw in keywords)
           and "ifs" in (p.get("account_name") or "").lower()]

if not matched:
    print("No matched contacts"); exit()

person = matched[0]
print(f"Enriching: {person.get('first_name')} {person.get('last_name')} ({person.get('title')})\n")

# Run enrichment
r = requests.post(f'{BASE}/api/v1/people/enrich-person', headers=HEADERS, json={
    "first_name": person.get("first_name", ""),
    "last_name": person.get("last_name", ""),
    "company_name": person.get("account_name", ""),
    "person_linkedin_url": person.get("linkedin_url") or person.get("person_linkedin", ""),
    "title": person.get("title", ""),
})
print(f"Enrich POST: {r.status_code}")
enrich_id = r.json().get("enrich_id")
print(f"enrich_id: {enrich_id}\n")

if not enrich_id:
    print("Full response:", r.json()); exit()

# Poll for result
for i in range(20):
    time.sleep(5)
    poll = requests.get(f'{BASE}/api/v1/enrich/{enrich_id}', headers=HEADERS)
    data = poll.json()
    status = data.get("data_import_status", "Running")
    print(f"  [{i+1}] status: {status}")
    if status != "Running":
        print("\n=== ALL NON-EMPTY FIELDS ===")
        for k, v in sorted(data.items()):
            if v not in (None, "", [], {}):
                print(f"  {k}: {v}")
        print("\n=== PHONE FIELDS (incl empty) ===")
        for k, v in sorted(data.items()):
            if any(x in k.lower() for x in ('phone', 'mobile', 'tel', 'direct')):
                print(f"  {k}: {repr(v)}")
        break
