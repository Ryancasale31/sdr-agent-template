"""
Claude and Tavily calls. Prompts live here so tone and rules are edited in one
place rather than scattered through the views.
"""
import json
import os

import streamlit as st

AI_MODEL = "claude-opus-4-5"


# ── Clients ───────────────────────────────────────────────────────────────────
def _secret(name: str, default: str = "") -> str:
    val = os.getenv(name, "")
    if not val:
        try:
            val = st.secrets.get(name, "")
        except Exception:
            val = ""
    return val or default


def claude():
    import anthropic
    return anthropic.Anthropic(api_key=_secret("ANTHROPIC_API_KEY"))


def tavily():
    from tavily import TavilyClient
    return TavilyClient(api_key=_secret("TAVILY_API_KEY"))


def ai_available() -> bool:
    return bool(_secret("ANTHROPIC_API_KEY"))


def search_available() -> bool:
    return bool(_secret("TAVILY_API_KEY"))


# ── Errors ─────────────────────────────────────────────────────────────
class AIError(RuntimeError):
    """A Claude or Tavily failure, phrased for the person selling rather than
    the person who wrote the code."""


# Matched against the lower-cased exception text, first hit wins.
_ERROR_HINTS = (
    ("credit balance is too low",
     "The Anthropic account is out of credit, so every AI feature is off. "
     "Add credit at console.anthropic.com → Plans & Billing."),
    ("invalid x-api-key",
     "Anthropic rejected the API key. Replace ANTHROPIC_API_KEY in the app's secrets."),
    ("authentication_error",
     "Anthropic rejected the API key. Replace ANTHROPIC_API_KEY in the app's secrets."),
    ("permission_error",
     "This Anthropic key is not allowed to use that model."),
    ("not_found_error",
     "Anthropic does not recognise the model name in AI_MODEL (core/ai.py)."),
    ("rate_limit",
     "Anthropic is rate-limiting this key. Give it a minute and try again."),
    ("overloaded",
     "Anthropic is overloaded. Try again in a moment."),
    ("unauthorized",
     "Tavily rejected the API key. Replace TAVILY_API_KEY in the app's secrets."),
    ("usage limit",
     "The Tavily plan is out of search credits."),
    ("timed out",
     "The request timed out before anything came back. Try again."),
)


def explain(e: Exception) -> str:
    """Plain English where we recognise the failure, the raw text where we don't."""
    text = str(e)
    low = text.lower()
    for needle, message in _ERROR_HINTS:
        if needle in low:
            return message
    return text


# ── Response parsing ──────────────────────────────────────────────────────────
def _parse_json(raw: str):
    """Claude occasionally wraps JSON in a fence or adds a sentence either side.
    Strip the fence, then fall back to the outermost bracket pair."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = raw.find(opener), raw.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse a JSON response from the model:\n{raw[:400]}")


def ask(prompt: str, max_tokens: int = 1200):
    if not ai_available():
        raise AIError("No Anthropic API key is set, so the AI features are off. "
                      "Add ANTHROPIC_API_KEY to the app's secrets.")
    try:
        msg = claude().messages.create(
            model=AI_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise AIError(explain(e)) from e
    return _parse_json(msg.content[0].text)


# ── Connection checks ─────────────────────────────────────────────────────────
# Setup shows these. A dead key used to look exactly like "nothing found", which
# is how a hunt can return an empty screen for weeks without anyone noticing.
def check_anthropic() -> tuple:
    """(ok, detail). Costs one negligible API call."""
    if not ai_available():
        return False, "No API key set."
    try:
        claude().messages.create(
            model=AI_MODEL, max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, f"Answering on {AI_MODEL}."
    except Exception as e:
        return False, explain(e)


def check_tavily() -> tuple:
    """(ok, detail). Costs one search credit."""
    if not search_available():
        return False, "No API key set."
    try:
        res = tavily().search(query="field service management software", max_results=1)
        return True, f"Returning results ({len(res.get('results', []))} for a test query)."
    except Exception as e:
        return False, explain(e)


# ── Shared prompt fragments ───────────────────────────────────────────────────
def audience_block(icp: dict) -> str:
    """The EVENT AUDIENCE section, always built from the active event's ICP.

    Never hardcode audience numbers here — doing that is how B2B companies
    once got scored against field-service buyers.
    """
    icp = icp or {}
    lines = []
    buyer_count = icp.get("buyer_count", "several hundred")
    senior_pct = icp.get("senior_buyer_pct")
    seniority = f", {senior_pct}% VP/Director/SVP level" if senior_pct else ""
    lines.append(f"- {buyer_count} registered buyers{seniority}")

    industries = icp.get("industry_breakdown") or icp.get("industries")
    if isinstance(industries, dict) and industries:
        top = sorted(industries.items(), key=lambda kv: -kv[1])[:6]
        lines.append("- Industries: " + ", ".join(f"{k} ({v})" for k, v in top))
    if icp.get("top_companies"):
        lines.append("- Top companies attending: " + ", ".join(icp["top_companies"][:10]))
    if icp.get("top_titles"):
        lines.append("- Top titles: " + ", ".join(icp["top_titles"][:8]))
    if icp.get("existing_sponsors"):
        lines.append("- Already sponsoring (never pitch these): "
                     + ", ".join(sorted(set(icp["existing_sponsors"]))))
    return "\n".join(lines)


def event_label(cfg: dict) -> str:
    return f"{cfg.get('name', 'the event')} ({cfg.get('location', '')}, {cfg.get('dates', '')})"


# ── Company research ──────────────────────────────────────────────────────────
def research_company(company_name: str, icp: dict, cfg: dict) -> dict:
    search_kw = cfg.get("search_keywords", "software products customers target market")
    results = tavily().search(
        query=f"{company_name} {search_kw}",
        max_results=5,
        search_depth="advanced",
    )
    web_context = "\n\n".join(
        f"Source: {r['url']}\n{r['content']}" for r in results.get("results", [])
    )

    prompt = f"""You are a sponsorship sales analyst for {event_label(cfg)}.

EVENT BUYER PROFILE:
{audience_block(icp)}

WEB RESEARCH ON {company_name}:
{web_context}

Analyse {company_name} as a potential sponsor.

Return ONLY valid JSON:
{{
  "company": "{company_name}",
  "what_they_do": "<1-2 sentence plain English description>",
  "who_they_sell_to": "<their target buyer persona>",
  "score": <0-100>,
  "tier": "<A|B|C>",
  "fit_reason": "<2-3 sentences on why they fit this audience>",
  "pitch_angle": "<the ONE strongest reason they should sponsor, specific to our attendee list>",
  "risk": "<one sentence on the likeliest objection>",
  "status": "researched"
}}
"""
    return ask(prompt, max_tokens=900)


# ── Outreach ──────────────────────────────────────────────────────────────────
_BANNED = ('"I hope this email finds you well", "synergy", "leverage", '
           '"cutting-edge", "robust", "game-changing", "circle back"')


def generate_meeting_email(company: dict, contact_name: str, contact_title: str,
                           icp: dict, cfg: dict) -> dict:
    pitch = (company.get("pitch_angle") or company.get("outreach_note")
             or company.get("fit_reason") or "")
    vs_sponsor = company.get("vs_sponsor", "")
    competitor_line = (f"Their competitors already sponsoring: {vs_sponsor}."
                       if vs_sponsor else "")
    sender = cfg.get("sender_name", "Ryan Casale")

    prompt = f"""You are {sender}, selling sponsorship for {event_label(cfg)}.

EVENT AUDIENCE:
{audience_block(icp)}

TARGET:
- Company: {company.get('company', '')}
- Contact: {contact_name}, {contact_title}
- What they do: {company.get('what_they_do', '')}
- Who they sell to: {company.get('who_they_sell_to', '')}
- Why they fit: {pitch}
{competitor_line}

Write ONE short, direct email asking for a 15-minute call about sponsorship.
- Lead with the single most relevant reason their buyers are in the room
- Be specific: name real attendee titles or companies where it strengthens the case
- Ask for one low-friction action: "15 minutes this week or next?"
- Under 120 words
- Peer-to-peer and confident, warm but not polished. No filler, no double dashes.
- Never use: {_BANNED}
- Sign off as: {sender}

Return ONLY valid JSON: {{"subject": "...", "body": "..."}}
"""
    return ask(prompt, max_tokens=700)


def generate_sequence(company: dict, contact_name: str, contact_title: str,
                      icp: dict, cfg: dict) -> list:
    vs_sponsor = company.get("vs_sponsor", "")
    sender = cfg.get("sender_name", "Ryan Casale")
    brand = cfg.get("event_brand", cfg.get("name", "the event"))

    extras = "\n".join(filter(None, [
        f"- Competitors already sponsoring: {vs_sponsor}" if vs_sponsor else "",
        f"- Internal note: {company.get('outreach_note')}" if company.get("outreach_note") else "",
        f"- Category: {company.get('category')}" if company.get("category") else "",
    ]))

    prompt = f"""You are a senior sponsorship sales rep for {event_label(cfg)}.

EVENT AUDIENCE:
{audience_block(icp)}

TARGET COMPANY:
- Name: {company.get('company', '')}
- What they do: {company.get('what_they_do', '')}
- Who they sell to: {company.get('who_they_sell_to', company.get('what_they_do', ''))}
- Best pitch angle: {company.get('pitch_angle', company.get('outreach_note', ''))}
{extras}

CONTACT: {contact_name}, {contact_title}

Write a 3-touch cold email sequence selling a sponsorship.
- Email 1: one specific audience insight. Under 150 words. Curiosity, no hard pitch.
- Email 2 (Day 4): connect their product to specific buyer titles or companies
  attending. If competitors sponsor, use it as social proof, never a threat.
  Under 175 words.
- Email 3 (Day 9): soft close, limited inventory, existing sponsors as validation.
  Under 100 words.
- Direct, peer-to-peer, confident. No filler, no corporate speak, no double dashes.
- Never use: {_BANNED}
- Sign off: {sender}, {brand}

Return ONLY valid JSON:
[
 {{"touch": 1, "send_day": "Day 1", "subject": "...", "body": "..."}},
 {{"touch": 2, "send_day": "Day 4", "subject": "...", "body": "..."}},
 {{"touch": 3, "send_day": "Day 9", "subject": "...", "body": "..."}}
]
"""
    return ask(prompt, max_tokens=1800)
