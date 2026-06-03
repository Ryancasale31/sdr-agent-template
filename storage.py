"""
Persistent storage for the FSE SDR Agent pipeline.

Uses Google Sheets when configured (survives Streamlit Cloud reboots),
falls back to a local JSON file otherwise (local dev + graceful degradation).

To enable Google Sheets, add to Streamlit Secrets:

    [gcp_service_account]
    type = "service_account"
    project_id = "..."
    private_key_id = "..."
    private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    client_email = "...@....iam.gserviceaccount.com"
    client_id = "..."
    token_uri = "https://oauth2.googleapis.com/token"

    [gsheets]
    pipeline_url = "https://docs.google.com/spreadsheets/d/.../edit"
"""
import json
from pathlib import Path

PIPELINE_FILE = Path(__file__).parent / "pipeline.json"
ICP_FILE = Path(__file__).parent / "icp_summary.json"

# Fields holding nested structures (lists/dicts) — JSON-encoded into a single cell.
_NESTED_HINT = ("[", "{")


def gsheets_configured() -> bool:
    try:
        import streamlit as st
        return "gcp_service_account" in st.secrets and "gsheets" in st.secrets
    except Exception:
        return False


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


def load_pipeline() -> list:
    if gsheets_configured():
        try:
            ws = _get_worksheet()
            records = ws.get_all_records()
            pipeline = []
            for rec in records:
                company = {k: _decode(v) for k, v in rec.items() if v != "" and v is not None}
                if company.get("company"):
                    pipeline.append(company)
            return pipeline
        except Exception as e:
            import streamlit as st
            st.warning(f"Could not load from Google Sheets ({e}). Showing local data.")

    if not PIPELINE_FILE.exists():
        return []
    with open(PIPELINE_FILE) as f:
        return json.load(f)


def save_pipeline(pipeline: list):
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
            # Mirror to local file as a backup copy too.
            _save_local(pipeline)
            return
        except Exception as e:
            import streamlit as st
            st.warning(f"Could not save to Google Sheets ({e}). Saved locally instead.")

    _save_local(pipeline)


def _save_local(pipeline: list):
    with open(PIPELINE_FILE, "w") as f:
        json.dump(pipeline, f, indent=2)


# ── ICP persistence ───────────────────────────────────────────────────────────
def load_icp():
    if gsheets_configured():
        try:
            raw = _get_icp_worksheet().acell("A1").value
            if raw:
                return json.loads(raw)
        except Exception as e:
            import streamlit as st
            st.warning(f"Could not load ICP from Google Sheets ({e}). Using local.")
    if ICP_FILE.exists():
        with open(ICP_FILE) as f:
            return json.load(f)
    return None


def save_icp(icp: dict):
    if gsheets_configured():
        try:
            _get_icp_worksheet().update_acell("A1", json.dumps(icp))
        except Exception as e:
            import streamlit as st
            st.warning(f"Could not save ICP to Google Sheets ({e}). Saved locally.")
    with open(ICP_FILE, "w") as f:
        json.dump(icp, f, indent=2)
