"""
Tiga as a research engine.

Why this exists: the Anthropic key ran out of credit and took company research
down with it. Tiga signals of `type: "gpt"` are a prompt plus web search, which
is the same primitive research_company() needs — and Ryan already pays for Tiga.

What this can and cannot do:
  CAN   judge a company we can name — research, scoring, a re-open angle.
  CANNOT find companies we cannot name. run-signal is account-scoped, so the
        Scout hunts (freeform, rival events, new markets) still need a real
        model key. Discovery lives in tiga_prospector.py instead.

API contract (Tiga docs, confirmed against the working code in tiga_signals.py):
  auth    X-Tiga-Auth: <key> on every request
  list    GET  /api/v1/signals?is_computed_column=true
  create  POST /api/v1/signal        {label, is_computed_column, type, computed_config}
  update  PUT  /api/v1/signal/:id    (GET first, send the full computed_config)
  run     POST /api/v1/signal/:id/run-signal  {"account": {"domain": "acme.com"}}
          Synchronous — no polling. Find-or-creates the account.
          Result: account.custom_columns[signal_id] = {status, value}
          status 1 SUCCESS · 2 NOT_FOUND · 3 MISSING_DEPENDENCIES
                 4 FAILED · 5 PRECONDITION_FAILED
"""
import json
import os
import re

from core import ai

BASE = "https://app.tigalabs.com/api/v1"
SIGNAL_VERSION = "v1"          # bump to force every event's signal prompt to be rewritten
RUN_TIMEOUT = 180              # a gpt signal with web search is not fast
WORD_LIMIT = 250


class TigaError(ai.AIError):
    """A Tiga failure, phrased for the person selling. Subclasses AIError so the
    views that already catch AIError show it without changes."""


_STATUS = {
    1: None,                                    # success
    2: "Tiga could not find that company.",
    3: "The signal is missing something it depends on (usually the account has no domain).",
    4: "Tiga ran the signal and it failed.",
    5: "The signal's preconditions were not met for this account.",
}


# ── Plumbing ──────────────────────────────────────────────────────────────────
def _key() -> str:
    key = os.getenv("TIGA_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("TIGA_API_KEY", "")
        except Exception:
            key = ""
    return key


def available() -> bool:
    return bool(_key())


def _headers(extra: dict = None) -> dict:
    h = {"X-Tiga-Auth": _key(), "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _request(method: str, path: str, *, timeout: int = 45, **kw):
    import requests
    if not available():
        raise TigaError("No Tiga API key is set, so Tiga research is off.")
    try:
        r = requests.request(method, f"{BASE}{path}", headers=_headers(kw.pop("extra_headers", None)),
                             timeout=timeout, **kw)
    except Exception as e:
        raise TigaError(f"Could not reach Tiga: {e}") from e
    if r.status_code in (401, 403):
        raise TigaError("Tiga rejected the API key. Replace TIGA_API_KEY in the app's secrets.")
    if r.status_code == 429:
        raise TigaError("Tiga is rate-limiting this key. Wait a moment and try again.")
    if not r.ok:
        raise TigaError(f"Tiga returned {r.status_code}: {(r.text or '')[:200]}")
    return r


# ── Domains ───────────────────────────────────────────────────────────────────
# run-signal keys accounts on domain, and the pipeline stores company names. A
# wrong guess silently researches the wrong company, which is worse than not
# researching at all — so guessing is deliberately conservative and the caller
# is expected to let the user correct it.
_SUFFIXES = r"\b(inc|inc\.|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|sa|nv|bv|ag|pvt|technologies|technology|group|holdings|solutions|software|systems)\b"


def guess_domain(company: str) -> str:
    """A cautious .com guess, or "" when the name is too ambiguous to guess from."""
    name = re.sub(r"\(.*?\)", " ", company or "")          # drop parentheticals
    name = re.sub(_SUFFIXES, " ", name, flags=re.I)
    name = re.sub(r"[^A-Za-z0-9 ]", " ", name).strip()
    words = name.split()
    if not words or len(words) > 2:
        # "Medical Equipment Repair Associates" is a description, not a domain.
        return ""
    return "".join(words).lower() + ".com"


def find_account(company: str) -> dict:
    """Look the company up in Tiga so we can use its real domain. {} if absent."""
    r = _request("GET", "/accounts",
                 extra_headers={"Tiga-Filter": json.dumps({"search_term": company})})
    try:
        rows = r.json()
    except Exception:
        return {}
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return {}


def resolve_domain(company: str, record: dict = None) -> str:
    """Domain already on the record > Tiga's own > a cautious guess > ""."""
    if record and record.get("domain"):
        return record["domain"]
    try:
        acct = find_account(company)
    except TigaError:
        acct = {}
    for k in ("domain", "website", "url"):
        v = (acct.get(k) or "").strip()
        if v:
            return re.sub(r"^https?://(www\.)?|/.*$", "", v)
    return guess_domain(company)


# ── Signals ───────────────────────────────────────────────────────────────────
def _signal_label(event_id: str) -> str:
    return f"SDR Agent - Sponsor Fit - {event_id} ({SIGNAL_VERSION})"


def _research_prompt(icp: dict, cfg: dict) -> str:
    return (
        f"You are a sponsorship sales analyst for {ai.event_label(cfg)}.\n\n"
        f"EVENT BUYER PROFILE:\n{ai.audience_block(icp)}\n\n"
        "Assess {{.AccountName}} ({{.AccountWebsite}}) as a potential sponsor of this "
        "event. Judge them on whether the people in that buyer profile are the people "
        "they sell to.\n\n"
        "Return ONLY valid JSON and nothing else:\n"
        '{"what_they_do":"1-2 plain sentences","who_they_sell_to":"their buyer persona",'
        '"score":<0-100>,"tier":"<A|B|C>","fit_reason":"2-3 sentences on fit with THIS audience",'
        '"pitch_angle":"the single strongest reason to sponsor","risk":"the likeliest objection"}'
    )


def ensure_research_signal(event_id: str, icp: dict, cfg: dict) -> str:
    """Get-or-create this event's research signal, updating it when the ICP moved.

    One signal per event on purpose: the prompt carries that event's audience, and
    scoring a medical prospect against the B2B audience is how the old app produced
    confidently wrong numbers.
    """
    label = _signal_label(event_id)
    prompt = _research_prompt(icp, cfg)
    config = {
        "type": "gpt",
        "prompt": prompt,
        "is_account_insight": True,
        "can_use_web_search": True,
        "expiration_in_days": 30,
        "temperature": 0.2,
        "word_limit": WORD_LIMIT,
    }

    existing = None
    r = _request("GET", "/signals?is_computed_column=true")
    try:
        for s in r.json():
            if isinstance(s, dict) and s.get("label") == label:
                existing = s
                break
    except Exception:
        pass

    if existing:
        sig_id = existing.get("id")
        if ((existing.get("computed_config") or {}).get("prompt") or "") != prompt:
            # The ICP changed under it. Silently scoring against a stale audience
            # would be the same bug as sharing one signal across events.
            _request("PUT", f"/signal/{sig_id}", json={
                "label": label, "is_computed_column": True,
                "type": "text", "computed_config": config,
            })
        return sig_id

    r = _request("POST", "/signal", json={
        "label": label, "is_computed_column": True,
        "type": "text", "computed_config": config,
    })
    sig_id = (r.json() or {}).get("id")
    if not sig_id:
        raise TigaError("Tiga accepted the signal but returned no id.")
    return sig_id


def run_on_account(signal_id: str, domain: str) -> str:
    """Run the signal and return its text value. Synchronous."""
    r = _request("POST", f"/signal/{signal_id}/run-signal", timeout=RUN_TIMEOUT,
                 json={"account": {"domain": domain}})
    try:
        data = r.json()
    except Exception as e:
        raise TigaError(f"Tiga returned something that was not JSON: {e}") from e

    col = ((data.get("account") or {}).get("custom_columns") or {}).get(signal_id) or {}
    status = col.get("status")
    if status == 1:
        return col.get("value") or ""

    # Tiga's own explanation matters more than our label for it. Without this,
    # "ran the signal and it failed" is a dead end — you cannot tell a bad prompt
    # from a bad account from a rejected config.
    detail = ""
    for k in ("error", "error_message", "message", "reason", "value"):
        v = col.get(k)
        if v:
            detail = f" Tiga said: {str(v)[:400]}"
            break
    if not detail and col:
        detail = f" Response fields: {sorted(col.keys())}"
    if not col:
        detail = (f" No column came back for this signal at all. Top-level keys: "
                  f"{sorted(data.keys())}")

    raise TigaError(
        (_STATUS.get(status) or f"Tiga returned status {status!r}.") + detail
        + f" [signal {signal_id}]"
    )


def list_gpt_signals(limit: int = 5) -> list:
    """Existing gpt signals and their configs — the reference for what Tiga accepts.

    Comparing a signal Tiga runs happily against one it rejects is the fastest way
    to find the field that is wrong.
    """
    r = _request("GET", "/signals?is_computed_column=true")
    try:
        rows = r.json()
    except Exception:
        return []
    out = []
    for sig in rows if isinstance(rows, list) else []:
        cfg = (sig.get("computed_config") or {}) if isinstance(sig, dict) else {}
        if cfg.get("type") != "gpt":
            continue
        out.append({
            "label": sig.get("label"),
            "id": sig.get("id"),
            "type": sig.get("type"),
            "config": {k: (v if k != "prompt" else str(v)[:300])
                       for k, v in cfg.items()},
        })
        if len(out) >= limit:
            break
    return out


# ── The job ───────────────────────────────────────────────────────────────────
def research_company(company_name: str, icp: dict, cfg: dict,
                     event_id: str = "default", record: dict = None) -> dict:
    """Same contract as ai.research_company, answered by Tiga instead of Claude."""
    domain = resolve_domain(company_name, record)
    if not domain:
        raise TigaError(
            f"No website for {company_name}, and the name is too ambiguous to guess one. "
            "Add a domain to the record and try again."
        )

    sig_id = ensure_research_signal(event_id, icp, cfg)
    raw = run_on_account(sig_id, domain)
    if not raw.strip():
        raise TigaError(f"Tiga ran the signal on {domain} but returned nothing.")

    try:
        out = ai._parse_json(raw)
        if not isinstance(out, dict):
            raise ValueError("not an object")
    except Exception:
        # A gpt signal is free text; it may ignore "JSON only". Keep what it said
        # rather than throwing away a paid call, and make the degradation visible.
        out = {
            "what_they_do": raw.strip()[:600],
            "who_they_sell_to": "",
            "score": None,
            "tier": "",
            "fit_reason": "",
            "pitch_angle": "",
            "risk": "",
            "needs_review": "Tiga answered in prose rather than JSON — score it yourself.",
        }

    out["company"] = company_name
    out["domain"] = domain
    out["status"] = "researched"
    out["research_engine"] = "tiga"
    return out


def check_tiga() -> tuple:
    """(ok, detail) for Setup -> Connections."""
    if not available():
        return False, "No API key set."
    try:
        r = _request("GET", "/signals?is_computed_column=true")
        rows = r.json()
        n = len(rows) if isinstance(rows, list) else 0
        gpt = sum(1 for s in rows if isinstance(s, dict)
                  and (s.get("computed_config") or {}).get("type") == "gpt") if isinstance(rows, list) else 0
        return True, f"Connected — {n} signals, {gpt} of them AI prompts."
    except TigaError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)
