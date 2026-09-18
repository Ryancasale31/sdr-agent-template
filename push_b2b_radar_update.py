"""
One-shot: push the locally-updated B2B Atlanta pipeline + radar finds to GitHub
so the live Streamlit app picks them up. Merges with the GitHub copy first so
nothing already on the data branch is lost.

Run:  python push_b2b_radar_update.py
"""
import radar

EVENT = "b2b-online-atlanta"
PIPE_PATH = f"events/{EVENT}/pipeline.json"
RADAR_PATH = f"{EVENT}_radar_finds.json"


def merge_push(gh_path, local_path):
    local = radar.load_json(local_path, [])
    remote = radar._github_load(gh_path) or []
    merged = {c["company"].lower(): c for c in remote}
    added = 0
    for c in local:
        if c["company"].lower() not in merged:
            merged[c["company"].lower()] = c
            added += 1
    out = sorted(merged.values(), key=lambda x: x.get("company", "").lower())
    ok = radar._github_save(gh_path, out)
    print(f"{gh_path}: {len(out)} entries ({added} new vs GitHub) -> push {'OK' if ok else 'FAILED'}")


def diagnose():
    import requests
    tok = radar.GITHUB_TOKEN
    if not tok:
        print("[!] GITHUB_TOKEN is empty — check .env")
        return False
    print(f"Token loaded: {tok[:15]}... ({len(tok)} chars)")
    r = requests.get("https://api.github.com/user", headers=radar._gh_headers(), timeout=15)
    print(f"Auth check: {r.status_code} — {r.json().get('login') or r.json().get('message')}")
    r2 = requests.get(f"https://api.github.com/repos/{radar.GITHUB_REPO}",
                      headers=radar._gh_headers(), timeout=15)
    print(f"Repo access ({radar.GITHUB_REPO}): {r2.status_code} — {r2.json().get('message', 'OK')}")
    return r.ok and r2.ok


if __name__ == "__main__":
    if diagnose():
        merge_push(PIPE_PATH, PIPE_PATH)
        merge_push(RADAR_PATH, RADAR_PATH)
        print("Done. Reload the app to see the new companies.")
    else:
        print("\nFix the token first:")
        print("  1. github.com -> Settings -> Developer settings -> Fine-grained tokens")
        print("  2. Repository access: Ryancasale31/sdr-agent-template")
        print("  3. Permissions -> Contents: Read and write")
        print("  4. Paste into .env as GITHUB_TOKEN=... (no quotes, no spaces)")
