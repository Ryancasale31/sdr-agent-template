"""
Persistent storage for the FSE SDR Agent (pipeline + ICP).

Backends, in priority order:
  1. GitHub  — reads/writes JSON files on a separate `data` branch of the repo.
               Survives Streamlit Cloud reboots. Writing to a NON-deployed branch
               avoids the auto-reboot loop that writing to `master` would cause.
  2. Google Sheets — optional alternative (kept for flexibility).
  3. Local file   — dev + graceful fallback; also the committed baseline on first run.

Network backends are cached in st.session_state so the app hits the network once
per session (not on every rerun), and write-through keeps the cache fresh.

── To enable GitHub persistence, add to Streamlit Secrets ──
    [github]
    token  = "github_pat_..."                      # fine-grained PAT, Contents: read+write
    repo   = "Ryancasale31/sdr-agent-template"
    branch = "data"

── (Optional) Google Sheets instead ──
    [gcp_service_account]
    ...service account JSON fields...
    [gsheets]
    pipeline_url = "https://docs.google.com/spreadsheets/d/.../edit"
"""
import json
import base64
from pathlib import Path

PIPELINE_FILE = Path(__file__).parent / "pipeline.json"
ICP_FILE = Path(__file__).parent / "icp_summary.json"
GITHUB_API = "https://api.github.com"


def _gh_pipeline_path(event_id: str) -> str:
    return f"events/{event_id}/pipeline.json"


def _gh_icp_path(event_id: str) -> str:
    return f"events/{event_id}/icp_summary.json"


# Fields holding nested structures (lists/dicts) — JSON-encoded into a single cell (Sheets).
_NESTED_HINT = ("[", "{")


# ══════════════════════════════════════════════════════════════════════════════
# Backend detection
# ══════════════════════════════════════════════════════════════════════════════
def github_configured() -> bool:
    try:
        import streamlit as st
        return "github" in st.secrets and bool(st.secrets["github"].get("token"))
    except Exception:
        return False


def gsheets_configured() -> bool:
    try:
        import streamlit as st
        return "gcp_service_account" in st.secrets and "gsheets" in st.secrets
    except Exception:
        return False


def _network_active() -> bool:
    return github_configured() or gsheets_configured()


def backend_name() -> str:
    if github_configured():
        return "GitHub"
    if gsheets_configured():
        return "Google Sheets"
    return "Local"


# ══════════════════════════════════════════════════════════════════════════════
# GitHub backend (Contents API on the data branch)
# ══════════════════════════════════════════════════════════════════════════════
def _gh_cfg():
    import streamlit as st
    g = st.secrets["github"]
    return g["token"], g.get("repo", "Ryancasale31/sdr-agent-template"), g.get("branch", "data")


def _gh_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _gh_get(path):
    """Return (text_content, sha) or (None, None) if absent."""
    import requests
    token, repo, branch = _gh_cfg()
    r = requests.get(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        params={"ref": branch},
        headers=_gh_headers(token),
        timeout=15,
    )
    if r.status_code == 200:
        data = r.json()
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]
    return None, None


def _gh_put(path, content, message):
    import requests
    token, repo, branch = _gh_cfg()
    _, sha = _gh_get(path)
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    r = requests.put(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        json=body,
        headers=_gh_headers(token),
        timeout=15,
    )
    return r.status_code in (200, 201)


# ══════════════════════════════════════════════════════════════════════════════
# Google Sheets backend
# ══════════════════════════════════════════════════════════════════════════════
def _get_spreadsheet():
    import streamlit as st
    import gspread
    gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    return gc.open_by_url(st.secrets["gsheets"]["pipeline_url"])


def _get_worksheet():
    return _get_spreadsheet().sheet1


def _get_icp_worksheet():
    sh = _get_spreadsheet()
    try:
        return sh.worksheet("icp")
    except Exception:
        return sh.add_worksheet("icp", rows=1, cols=1)


def _encode(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


def _decode(value):
    if isinstance(value, str) and value[:1] in _NESTED_HINT:
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


# ══════════════════════════════════════════════════════════════════════════════
# Local file backend
# ══════════════════════════════════════════════════════════════════════════════
def _load_local_pipeline() -> list:
    if not PIPELINE_FILE.exists():
        return []
    with open(PIPELINE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_local_pipeline(pipeline: list):
    with open(PIPELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(pipeline, f, indent=2, ensure_ascii=False)


def _load_local_icp():
    if ICP_FILE.exists():
        with open(ICP_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_local_icp(icp: dict):
    with open(ICP_FILE, "w", encoding="utf-8") as f:
        json.dump(icp, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# Session cache (only used when a network backend is active)
# ══════════════════════════════════════════════════════════════════════════════
def _cache_get(key):
    try:
        import streamlit as st
        return st.session_state.get(key)
    except Exception:
        return None


def _cache_set(key, value):
    try:
        import streamlit as st
        st.session_state[key] = value
    except Exception:
        pass


def _warn(msg):
    try:
        import streamlit as st
        st.warning(msg)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Public API — pipeline
# ══════════════════════════════════════════════════════════════════════════════
def load_pipeline(event_id: str = "field-service-east") -> list:
    if not _network_active():
        return _load_local_pipeline()

    cache_key = f"pipeline_cache_{event_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _load_pipeline_remote(event_id)
    _cache_set(cache_key, data)
    return data


def save_pipeline(pipeline: list, event_id: str = "field-service-east"):
    _save_local_pipeline(pipeline)  # always keep a local copy
    if not _network_active():
        return
    _cache_set(f"pipeline_cache_{event_id}", pipeline)
    _save_pipeline_remote(pipeline, event_id)


def refresh_cache(event_id: str = None):
    """Drop cached data so the next load re-fetches from the network backend."""
    try:
        import streamlit as st
        if event_id:
            st.session_state.pop(f"pipeline_cache_{event_id}", None)
            st.session_state.pop(f"icp_cache_{event_id}", None)
        else:
            keys_to_remove = [k for k in st.session_state
                              if k.startswith(("pipeline_cache_", "icp_cache_"))]
            for k in keys_to_remove:
                st.session_state.pop(k, None)
    except Exception:
        pass


def _load_pipeline_remote(event_id: str = "field-service-east") -> list:
    if github_configured():
        try:
            content, _ = _gh_get(_gh_pipeline_path(event_id))
            if content:
                return json.loads(content)
            return _load_local_pipeline()
        except Exception as e:
            _warn(f"Could not load pipeline from GitHub ({e}). Showing local baseline.")
            return _load_local_pipeline()
    if gsheets_configured():
        try:
            records = _get_worksheet().get_all_records()
            pipeline = []
            for rec in records:
                company = {k: _decode(v) for k, v in rec.items() if v != "" and v is not None}
                if company.get("company"):
                    pipeline.append(company)
            return pipeline
        except Exception as e:
            _warn(f"Could not load from Google Sheets ({e}). Showing local data.")
    return _load_local_pipeline()


def _save_pipeline_remote(pipeline: list, event_id: str = "field-service-east"):
    if github_configured():
        try:
            content = json.dumps(pipeline, indent=2, ensure_ascii=False)
            if not _gh_put(_gh_pipeline_path(event_id), content,
                           f"Update pipeline [{event_id}] via app"):
                _warn("GitHub save returned an error. Changes are local-only this session.")
        except Exception as e:
            _warn(f"Could not save pipeline to GitHub ({e}). Saved locally instead.")
        return
    if gsheets_configured():
        try:
            ws = _get_worksheet()
            keys = []
            for c in pipeline:
                for k in c.keys():
                    if k not in keys:
                        keys.append(k)
            ws.clear()
            if keys:
                rows = [keys]
                for c in pipeline:
                    rows.append([_encode(c.get(k, "")) for k in keys])
                ws.append_rows(rows, value_input_option="RAW")
        except Exception as e:
            _warn(f"Could not save to Google Sheets ({e}). Saved locally instead.")


# ══════════════════════════════════════════════════════════════════════════════
# Public API — ICP
# ══════════════════════════════════════════════════════════════════════════════
def load_icp(event_id: str = "field-service-east"):
    if not _network_active():
        return _load_local_icp()

    cache_key = f"icp_cache_{event_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _load_icp_remote(event_id)
    if data is not None:
        _cache_set(cache_key, data)
    return data


def save_icp(icp: dict, event_id: str = "field-service-east"):
    _save_local_icp(icp)
    if not _network_active():
        return
    _cache_set(f"icp_cache_{event_id}", icp)
    _save_icp_remote(icp, event_id)


def _load_icp_remote(event_id: str = "field-service-east"):
    if github_configured():
        try:
            content, _ = _gh_get(_gh_icp_path(event_id))
            if content:
                return json.loads(content)
            return _load_local_icp()
        except Exception as e:
            _warn(f"Could not load ICP from GitHub ({e}). Using local baseline.")
            return _load_local_icp()
    if gsheets_configured():
        try:
            raw = _get_icp_worksheet().acell("A1").value
            if raw:
                return json.loads(raw)
        except Exception as e:
            _warn(f"Could not load ICP from Google Sheets ({e}). Using local.")
    return _load_local_icp()


def _save_icp_remote(icp: dict, event_id: str = "field-service-east"):
    if github_configured():
        try:
            content = json.dumps(icp, indent=2, ensure_ascii=False)
            _gh_put(_gh_icp_path(event_id), content,
                    f"Update ICP [{event_id}] via app")
        except Exception as e:
            _warn(f"Could not save ICP to GitHub ({e}). Saved locally instead.")
        return
    if gsheets_configured():
        try:
            _get_icp_worksheet().update_acell("A1", json.dumps(icp))
        except Exception as e:
            _warn(f"Could not save ICP to Google Sheets ({e}). Saved locally.")
