"""
Outlook / Microsoft Graph API integration.
Dormant until Azure App Registration is complete.
Set AZURE_CLIENT_ID and AZURE_CLIENT_SECRET in .env to activate.
"""
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.getenv("AZURE_TENANT_ID", "common")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "https://fse-sdr-agent.streamlit.app")
TOKEN_FILE = Path(__file__).parent / ".outlook_token.json"

SCOPES = "Mail.Read Mail.Send offline_access User.Read"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def is_configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


def get_auth_url() -> str:
    return (
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={SCOPES.replace(' ', '%20')}"
        f"&response_mode=query"
    )


def exchange_code_for_token(code: str) -> dict:
    resp = requests.post(
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )
    resp.raise_for_status()
    token = resp.json()
    _save_token(token)
    return token


def _save_token(token: dict):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f)


def _load_token() -> dict | None:
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return None


def _refresh_token(refresh_token: str) -> dict:
    resp = requests.post(
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": SCOPES,
        },
    )
    resp.raise_for_status()
    token = resp.json()
    _save_token(token)
    return token


def _get_access_token() -> str | None:
    token = _load_token()
    if not token:
        return None
    # Try refresh if we have a refresh_token
    if "refresh_token" in token:
        try:
            token = _refresh_token(token["refresh_token"])
        except Exception:
            return None
    return token.get("access_token")


def is_authenticated() -> bool:
    return _get_access_token() is not None


def get_profile() -> dict | None:
    access_token = _get_access_token()
    if not access_token:
        return None
    resp = requests.get(
        f"{GRAPH_BASE}/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return resp.json() if resp.ok else None


def get_recent_replies(prospect_emails: list[str], top: int = 50) -> list[dict]:
    """
    Fetch recent inbox messages and return those from known prospect email addresses.
    prospect_emails: list of email addresses to watch for replies.
    """
    access_token = _get_access_token()
    if not access_token:
        return []

    resp = requests.get(
        f"{GRAPH_BASE}/me/mailFolders/inbox/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "$top": top,
            "$select": "subject,from,receivedDateTime,bodyPreview,conversationId",
            "$orderby": "receivedDateTime desc",
        },
    )
    if not resp.ok:
        return []

    messages = resp.json().get("value", [])
    prospect_set = {e.lower() for e in prospect_emails}
    return [
        m for m in messages
        if m.get("from", {}).get("emailAddress", {}).get("address", "").lower()
        in prospect_set
    ]


def send_email(to_email: str, subject: str, body: str) -> bool:
    access_token = _get_access_token()
    if not access_token:
        return False

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        },
        "saveToSentItems": True,
    }
    resp = requests.post(
        f"{GRAPH_BASE}/me/sendMail",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    return resp.status_code == 202


def get_sent_to_prospects(prospect_emails: list[str], top: int = 100) -> list[dict]:
    """Return sent emails addressed to known prospect emails."""
    access_token = _get_access_token()
    if not access_token:
        return []

    resp = requests.get(
        f"{GRAPH_BASE}/me/mailFolders/sentItems/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "$top": top,
            "$select": "subject,toRecipients,sentDateTime,bodyPreview,conversationId",
            "$orderby": "sentDateTime desc",
        },
    )
    if not resp.ok:
        return []

    messages = resp.json().get("value", [])
    prospect_set = {e.lower() for e in prospect_emails}
    return [
        m for m in messages
        if any(
            r["emailAddress"]["address"].lower() in prospect_set
            for r in m.get("toRecipients", [])
        )
    ]
