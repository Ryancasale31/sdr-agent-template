"""Test Seamless.ai API with correct auth and payload format per docs."""
import os, requests
from dotenv import load_dotenv
load_dotenv()

KEY = os.getenv("SEAMLESS_API_KEY")
print(f"Key length: {len(KEY)}\n")

ENDPOINT = "https://api.seamless.ai/api/client/v1/search/contacts"

# Per Seamless docs: header is literally "Token: API_KEY"
HEADERS = {
    "Token": KEY,
    "Content-Type": "application/json",
}

# Per Seamless docs: companyName is array, jobTitle is array, seniority uses specific values
PAYLOAD = {
    "companyName": ["Salesforce"],
    "jobTitle": ["VP Marketing", "Director of Marketing", "CMO"],
    "seniority": ["VP", "Director", "C-Level"],
    "contactCountry": ["United States"],
    "limit": 5,
}

print(f"POST {ENDPOINT}")
print(f"Headers: Token: {KEY[:20]}...")
print(f"Payload: {PAYLOAD}\n")

r = requests.post(ENDPOINT, headers=HEADERS, json=PAYLOAD, timeout=15)
print(f"Status: {r.status_code}")
print(f"Response: {r.text[:500]}")
