"""
Tiga connection self-check.

Run this on YOUR machine (Claude's sandbox can't reach app.tigalabs.com, so this
is the only way to confirm the API shape before the app depends on it).

    cd "C:\\Users\\Ryan.Casale\\OneDrive - IQPC WBR\\Field service East\\fse_sdr_agent"
    python test_tiga_connection.py

It is read-mostly: it lists your signals and reads one account. It creates a
signal and runs it ONLY if you pass --full, and it tells you before it does.
No key is ever printed.

Paste the whole output back into the chat.
"""
import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("requests is not installed. Run:  pip install requests python-dotenv")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

KEY = os.getenv("TIGA_API_KEY", "")
BASE = "https://app.tigalabs.com/api/v1"
HEADERS = {"X-Tiga-Auth": KEY, "Content-Type": "application/json"}

# The signal the SDR agent would use to replace Claude for company research.
PROBE_LABEL = "SDR Agent - Sponsor Fit (test)"
PROBE_CONFIG = {
    "type": "gpt",
    "prompt": (
        "You are assessing {{.AccountName}} ({{.AccountWebsite}}) as a potential "
        "sponsor for a field service industry conference whose audience is VP and "
        "Director level service leaders at medical device and industrial equipment "
        "manufacturers.\n"
        "Return ONLY JSON, no other text: "
        '{"what_they_do":"one sentence","who_they_sell_to":"their buyer",'
        '"score":0-100,"fit_reason":"two sentences","pitch_angle":"one line"}'
    ),
    "is_account_insight": True,
    "can_use_web_search": True,
    "expiration_in_days": 30,
    "word_limit": 200,
}


def show(label, resp, body_chars=700):
    print(f"\n--- {label}")
    print(f"    HTTP {resp.status_code}")
    text = resp.text or ""
    print(f"    body: {text[:body_chars]}")
    if len(text) > body_chars:
        print(f"    ...(+{len(text) - body_chars} more chars)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="also create a test signal and run it on one account (uses Tiga credit)")
    ap.add_argument("--company", default="ServiceMax",
                    help="company to test the research signal against")
    args = ap.parse_args()

    print("=" * 70)
    print("TIGA CONNECTION SELF-CHECK")
    print("=" * 70)

    if not KEY:
        sys.exit("TIGA_API_KEY is not set. Is .env in this folder, and is python-dotenv installed?")
    print(f"Key found: {len(KEY)} characters, starts '{KEY[:4]}...'  (not printing the rest)")

    # 1. Can we authenticate at all?
    try:
        r = requests.get(f"{BASE}/signals", headers=HEADERS, timeout=30)
    except Exception as e:
        sys.exit(f"\nCould not reach {BASE} at all: {e}\n"
                 "If this is a network/proxy error, the app will hit the same wall.")
    show("1. GET /signals  (does the key work?)", r, 400)
    if r.status_code in (401, 403):
        sys.exit("\nThe key was rejected. Everything below would fail too - stop here.")

    signals = []
    if r.ok:
        try:
            signals = r.json()
        except Exception:
            pass
    if isinstance(signals, list):
        print(f"\n    You have {len(signals)} signals. First few:")
        for s in signals[:8]:
            if isinstance(s, dict):
                cfg = s.get("computed_config") or {}
                print(f"      - {s.get('label')!r}  id={s.get('id')}  type={cfg.get('type')}")
        print("\n    KEY QUESTION: is there a 'type': 'gpt' signal above? That is the one")
        print("    that can replace Claude for research - it is a free-text prompt with web search.")

    # 2. Account lookup shape
    r = requests.get(f"{BASE}/accounts", headers={**HEADERS,
                     "Tiga-Filter": json.dumps({"search_term": args.company})}, timeout=30)
    show(f"2. GET /accounts  (search for {args.company!r} - what does an account look like?)", r)

    if not args.full:
        print("\n" + "=" * 70)
        print("Read-only checks done. Nothing was created.")
        print("To test the actual research call (creates one signal, uses Tiga credit):")
        print("    python test_tiga_connection.py --full")
        print("=" * 70)
        return

    # 3. Create the probe signal
    print("\n>>> --full given: creating a test signal and running it. This uses Tiga credit.")
    existing = None
    if isinstance(signals, list):
        for s in signals:
            if isinstance(s, dict) and s.get("label") == PROBE_LABEL:
                existing = s.get("id")
    if existing:
        sig_id = existing
        print(f"\n--- 3. Reusing existing test signal id={sig_id}")
    else:
        r = requests.post(f"{BASE}/signal", headers=HEADERS, timeout=60, json={
            "label": PROBE_LABEL,
            "is_computed_column": True,
            "type": "text",
            "computed_config": PROBE_CONFIG,
        })
        show("3. POST /signal  (create the research signal)", r)
        if not r.ok:
            sys.exit("Could not create the signal - the app cannot use this route.")
        sig_id = r.json().get("id")

    # 4. Run it
    domain = args.company.lower().replace(" ", "") + ".com"
    r = requests.post(f"{BASE}/signal/{sig_id}/run-signal", headers=HEADERS, timeout=180,
                      json={"account": {"domain": domain}})
    show(f"4. POST /signal/{{id}}/run-signal  (run it on {domain})", r, 2000)

    print("\n" + "=" * 70)
    print("WHAT MATTERS IN STEP 4:")
    print("  - did it return a value, or a 'pending/queued' status?")
    print("  - is the value the JSON the prompt asked for, or prose?")
    print("  - how long did it take?")
    print("That decides whether research can run live in the app or has to be a batch job.")
    print("=" * 70)


if __name__ == "__main__":
    main()
