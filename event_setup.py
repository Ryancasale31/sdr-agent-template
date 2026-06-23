"""
Event Setup Module
Handles first-time configuration for a new event sandbox:
  1. Upload attendee registration CSV  → rebuild ICP
  2. Paste event website URL           → scrape focus + suggest search keywords
  3. Run first radar pass              → seed the pipeline

This module is intentionally standalone — it does not import from app.py.
"""

import json
import os
from pathlib import Path

# ── ICP builder ───────────────────────────────────────────────────────────────
def build_icp_from_csv(csv_path: str) -> dict:
    """
    Build an ICP summary from a WBR attendee registration CSV.
    Uses the same column format as Field Service East:
      Account, Job Title, Price List Type  (Primary = buyer, Vendor = sponsor)
    """
    from icp_profile import build_icp
    return build_icp(csv_path)


# ── Website research ──────────────────────────────────────────────────────────
def research_event_website(url: str, event_name: str) -> dict:
    """
    Use Tavily + Claude to extract sponsorship-relevant info from an event website.
    Returns a dict with: focus, key_topics, attendee_profile,
                         sponsor_categories, suggested_search_keywords
    """
    import anthropic
    from tavily import TavilyClient

    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Web search about the event
    search_results = tavily.search(
        query=f"{event_name} conference agenda speakers sponsors attendees 2026",
        max_results=5,
        search_depth="advanced",
    )

    # Direct page extract
    url_content = ""
    try:
        extract_result = tavily.extract(urls=[url])
        url_content = extract_result.get("results", [{}])[0].get("raw_content", "")[:3000]
    except Exception:
        pass

    web_context = "\n\n".join([
        f"Source: {r['url']}\n{r['content']}"
        for r in search_results.get("results", [])
    ])

    if url_content:
        web_context = f"EVENT WEBSITE (direct):\n{url_content}\n\n---\n\n" + web_context

    prompt = f"""You are analyzing the event "{event_name}" to help a sponsorship sales rep target the right companies.

WEB RESEARCH:
{web_context[:5000]}

Extract the following and return ONLY valid JSON:
{{
  "focus": "<2-3 sentence plain-English description of what this event covers and who attends>",
  "key_topics": ["topic1", "topic2", "topic3", "topic4", "topic5"],
  "attendee_profile": "<job titles and industries that typically attend>",
  "sponsor_categories": [
    "<type of software/tech company that would sponsor>",
    "<type 2>",
    "<type 3>",
    "<type 4>"
  ],
  "suggested_search_keywords": "<10-15 keywords space-separated, describing products/software that sponsors would sell to this audience>",
  "sample_target_companies": ["Company A", "Company B", "Company C"]
}}
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ── Radar seed ────────────────────────────────────────────────────────────────
def get_radar_seed_queries(event_cfg: dict, scraped: dict) -> list:
    """
    Generate specific Seamless/Apollo search queries to seed the pipeline
    for a new event.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""Generate 8 search queries to find sponsor prospects for {event_cfg.get('name')}.

Event focus: {event_cfg.get('focus', '')}
Attendee profile: {scraped.get('attendee_profile', '')}
Sponsor categories: {', '.join(scraped.get('sponsor_categories', []))}
Key topics: {', '.join(scraped.get('key_topics', []))}

Each query should target a SPECIFIC type of software or technology company
that sells products/services to this event's attendee profile.
Make queries concrete, not generic (e.g. "B2B eCommerce platform software" not just "software").

Return ONLY a JSON array of 8 query strings:
["query 1", "query 2", ...]
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
