"""
Push the B2B Online Atlanta "confirmed sponsor" update to GitHub (data branch)
so the live Streamlit app matches your local files.

Unlike push_b2b_radar_update.py (which only ADDS companies missing from GitHub
and therefore silently drops edits to companies that already exist there), this
script OVERWRITES the 17 confirmed-sponsor records, then adds anything else new.

Run:  python push_sponsors_update.py
"""
import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).parent
EVENT = "b2b-online-atlanta"

SPONSORS = [
    "Op5 Solutions", "Threekit", "Coveo", "Cadent Commerce", "Revalgo", "Orium",
    "Luminos Labs", "Optimizely", "Nuvo", "Navu", "Valtech", "HawkSearch",
    "Supplier Solutions", "Pimberly", "commercetools", "inriver", "SAP",
]


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


SPONSOR_KEYS = {_norm(s) for s in SPONSORS}

# ── config ────────────────────────────────────────────────────────────────────
def _load_env():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
TOKEN = os.getenv("GITHUB_TOKEN", "")
REPO = os.getenv("GITHUB_REPO", "Ryancasale31/sdr-agent-template")
BRANCH = os.getenv("GITHUB_BRANCH", "data")
API = "https://api.github.com"
H = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

PIPE_PATH = f"events/{EVENT}/pipeline.json"
ICP_PATH = f"events/{EVENT}/icp_summary.json"
RADAR_PATH = f"{EVENT}_radar_finds.json"


# ── github helpers ────────────────────────────────────────────────────────────
def gh_get(path):
    r = requests.get(f"{API}/repos/{REPO}/contents/{path}",
                     params={"ref": BRANCH}, headers=H, timeout=20)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    j = r.json()
    return json.loads(base64.b64decode(j["content"]).decode("utf-8")), j["sha"]


def gh_put(path, data, message, sha):
    payload = {
        "message": message,
        "content": base64.b64encode(
            json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        ).decode(),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(f"{API}/repos/{REPO}/contents/{path}",
                     headers=H, json=payload, timeout=30)
    if r.status_code == 409:  # sha race — refetch and retry once
        _, sha2 = gh_get(path)
        payload["sha"] = sha2
        r = requests.put(f"{API}/repos/{REPO}/contents/{path}",
                         headers=H, json=payload, timeout=30)
    return r.ok, (r.json().get("message") if not r.ok else "OK")


def local(rel):
    return json.loads((HERE / rel).read_text(encoding="utf-8"))


# ── merges ────────────────────────────────────────────────────────────────────
def push_pipeline():
    loc = local(Path("events") / EVENT / "pipeline.json")
    rem, sha = gh_get(PIPE_PATH)
    rem = rem or []
    merged = {_norm(c.get("company")): c for c in rem}
    overwritten = added = 0
    for c in loc:
        k = _norm(c.get("company"))
        if k in SPONSOR_KEYS:
            merged[k] = c                      # sponsor record wins, always
            overwritten += 1
        elif k not in merged:
            merged[k] = c
            added += 1
    out = sorted(merged.values(), key=lambda x: (x.get("company") or "").lower())
    ok, msg = gh_put(PIPE_PATH, out,
                     f"Mark 17 confirmed B2B Atlanta sponsors as closed_won "
                     f"[{datetime.now():%Y-%m-%d %H:%M}]", sha)
    won = sum(1 for c in out if c.get("status") == "closed_won")
    print(f"{PIPE_PATH}: {len(out)} companies, {won} closed_won "
          f"({overwritten} sponsors written, {added} other new) -> {msg}")
    return ok


def push_icp():
    loc = local(Path("events") / EVENT / "icp_summary.json")
    rem, sha = gh_get(ICP_PATH)
    out = dict(rem) if isinstance(rem, dict) else {}
    out.update(loc)                            # local is authoritative
    ex = list(out.get("existing_sponsors", []))
    seen = {_norm(x) for x in ex}
    for s in SPONSORS:
        if _norm(s) not in seen:
            ex.append(s)
            seen.add(_norm(s))
    out["existing_sponsors"] = ex
    ok, msg = gh_put(ICP_PATH, out,
                     f"Add confirmed sponsors to radar exclusion list "
                     f"[{datetime.now():%Y-%m-%d %H:%M}]", sha)
    print(f"{ICP_PATH}: existing_sponsors = {len(ex)} -> {msg}")
    return ok


def push_radar():
    loc = local(RADAR_PATH)
    rem, sha = gh_get(RADAR_PATH)
    merged = {_norm(c.get("company")): c for c in (rem or [])}
    for c in loc:
        k = _norm(c.get("company"))
        if k in SPONSOR_KEYS or k not in merged:
            merged[k] = c
    for k, c in merged.items():                # belt and braces
        if k in SPONSOR_KEYS:
            c["reviewed"] = True
            c["dismissed"] = True
    out = sorted(merged.values(), key=lambda x: (x.get("company") or "").lower())
    ok, msg = gh_put(RADAR_PATH, out,
                     f"Dismiss confirmed sponsors from radar finds "
                     f"[{datetime.now():%Y-%m-%d %H:%M}]", sha)
    print(f"{RADAR_PATH}: {len(out)} finds -> {msg}")
    return ok


def diagnose():
    if not TOKEN:
        print("[!] GITHUB_TOKEN is empty - check .env next to this script")
        return False
    print(f"Token loaded ({len(TOKEN)} chars), repo {REPO}, branch {BRANCH}")
    r = requests.get(f"{API}/user", headers=H, timeout=20)
    print(f"  auth : {r.status_code} {r.json().get('login') or r.json().get('message')}")
    r2 = requests.get(f"{API}/repos/{REPO}", headers=H, timeout=20)
    print(f"  repo : {r2.status_code} {r2.json().get('message', 'OK')}")
    if r2.ok and r2.json().get("permissions", {}).get("push") is False:
        print("  [!] token has read-only Contents permission")
    return r.ok and r2.ok


if __name__ == "__main__":
    if not diagnose():
        print("\nToken fix:")
        print("  github.com -> Settings -> Developer settings -> Fine-grained tokens")
        print("  Repository access: Ryancasale31/sdr-agent-template")
        print("  Permissions -> Contents: Read and write")
        print("  Paste into .env as GITHUB_TOKEN=... (no quotes)")
        raise SystemExit(1)
    print()
    results = [push_pipeline(), push_icp(), push_radar()]
    print()
    if all(results):
        print("All three pushed. Reload the Streamlit app to confirm.")
        print("Reminder: Streamlit Cloud secrets still hold the OLD token - the")
        print("app's own write features stay broken until you update them there.")
    else:
        print("One or more pushes failed - see messages above.")
        raise SystemExit(1)
