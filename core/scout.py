"""
Scout — the new-business engine.

Four ways to find revenue, all returning the same candidate shape so the Find
view can render and add them identically:

  freeform    ask in plain English, search the live web
  rivals      companies exhibiting or sponsoring competitor events
  lapsed      past sponsors and stalled conversations worth reopening
  markets     categories with enough vendors to justify an event that doesn't exist

Everything is deduped against the current pipeline and the event's confirmed
sponsor list before it reaches the screen.
"""
import re
from datetime import date, datetime

from core import ai
from core.data import (
    STATUSES, days_since_last_activity, get_contacts, normalize_status,
)

STOP_WORDS = {
    "the", "and", "inc", "llc", "ltd", "corp", "corporation", "company", "group",
    "technologies", "technology", "solutions", "software", "systems", "digital",
    "labs", "io", "ai", "co", "holdings", "international", "global",
}


# ── Dedupe ────────────────────────────────────────────────────────────────────
def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _words(name: str) -> set:
    return {w for w in re.split(r"[^a-z0-9]+", (name or "").lower())
            if len(w) > 3 and w not in STOP_WORDS}


def is_known(name: str, known: set, known_words: list) -> bool:
    """Match a candidate against names we already have.

    Exact normalised match, then containment, then distinctive-word overlap.
    Containment is only trusted for longer names — 'Pepper' vs 'Pepperi' is
    exactly the false positive that cost a good prospect last time, so short
    names must match exactly.
    """
    n = _norm(name)
    if not n:
        return True
    if n in known:
        return True
    if len(n) >= 8:
        for k in known:
            if len(k) >= 8 and (k in n or n in k):
                return True
    nw = _words(name)
    if nw:
        for kw in known_words:
            if kw and nw == kw:
                return True
    return False


def build_known(pipeline: list, icp: dict) -> tuple:
    names = [c.get("company", "") for c in pipeline]
    names += list(icp.get("existing_sponsors", []) or [])
    known = {_norm(n) for n in names if n}
    known_words = [_words(n) for n in names if n]
    return known, known_words


# ── Web search ────────────────────────────────────────────────────────────────
def _search(queries: list, per_query: int = 5, depth: str = "advanced") -> str:
    """Run several Tavily queries and concatenate the readable results."""
    client = ai.tavily()
    chunks = []
    for q in queries:
        try:
            res = client.search(query=q, max_results=per_query, search_depth=depth)
        except Exception as e:
            chunks.append(f"[search failed for '{q}': {e}]")
            continue
        for r in res.get("results", []):
            chunks.append(f"Source: {r.get('url', '')}\n{r.get('content', '')[:1500]}")
    return "\n\n".join(chunks)


_CANDIDATE_SCHEMA = """[
  {
    "company": "Exact company name",
    "what_they_do": "One clear sentence on their product or service",
    "category": "Short category label",
    "score": <70-100>,
    "tier": "<A|B|C>",
    "fit_reason": "Why they fit THIS audience specifically",
    "pitch_angle": "One-line hook for the sponsorship pitch",
    "signal": "What in the sources suggests they'd buy now",
    "source_url": "URL from the sources above, or empty string"
  }
]"""


def _extract(web_context: str, task: str, icp: dict, cfg: dict,
             exclude: list, max_tokens: int = 3000) -> list:
    """Ask Claude to pull qualifying companies out of search results."""
    excl = ", ".join(sorted(exclude)[:120]) or "none"
    prompt = f"""You are a sponsorship sales analyst for {ai.event_label(cfg)}.

EVENT FOCUS: {cfg.get('focus', '')}

EVENT BUYER PROFILE (the people in the room):
{ai.audience_block(icp)}

{task}

SEARCH RESULTS:
{web_context[:60000]}

Rules:
1. Only companies that SELL TO the audience above. Never the attendees themselves.
2. Real, named companies only. No generic descriptions, no "various vendors".
3. Do not return any of these, they are already known: {excl}
4. Score 70-84 for a solid fit, 85-100 only for an ideal fit. Below 70, leave out.
5. Ground every fit_reason in something from the sources, not general knowledge.

Return ONLY a valid JSON array, [] if nothing qualifies:
{_CANDIDATE_SCHEMA}
"""
    out = ai.ask(prompt, max_tokens=max_tokens)
    return out if isinstance(out, list) else []


def _finish(candidates: list, pipeline: list, icp: dict, source: str) -> list:
    """Dedupe, stamp provenance, sort."""
    known, known_words = build_known(pipeline, icp)
    seen = set()
    out = []
    for c in candidates:
        name = (c.get("company") or "").strip()
        if not name or is_known(name, known, known_words):
            continue
        n = _norm(name)
        if n in seen:
            continue
        seen.add(n)
        c["company"] = name
        c["source"] = source
        c["status"] = "researched"
        c["found_date"] = date.today().isoformat()
        c.setdefault("contacts", [])
        c.setdefault("priority", "hot" if (c.get("score") or 0) >= 85 else "medium")
        out.append(c)
    return sorted(out, key=lambda x: -(x.get("score") or 0))


# ── 1. Freeform plain-English hunt ────────────────────────────────────────────
def plan_query(question: str, icp: dict, cfg: dict) -> dict:
    """Turn a sentence into search queries. Showing the plan before running it
    means a bad interpretation costs one glance instead of four minutes."""
    prompt = f"""You turn a salesperson's plain-English request into web searches.

EVENT: {ai.event_label(cfg)}
EVENT FOCUS: {cfg.get('focus', '')}
AUDIENCE:
{ai.audience_block(icp)}

THEIR REQUEST: "{question}"

Write 4-6 web search queries that would surface companies matching it. Favour
listing pages, funding news, G2/Capterra categories, exhibitor lists and
"top X vendors" roundups over company homepages.

Return ONLY valid JSON:
{{
  "interpretation": "<one sentence: what you understand them to be asking for>",
  "queries": ["...", "..."],
  "must_have": ["<trait a company must have to qualify>"],
  "exclude": ["<kind of company to leave out>"]
}}
"""
    return ai.ask(prompt, max_tokens=900)


def hunt_freeform(question: str, plan: dict, pipeline: list, icp: dict, cfg: dict,
                  progress=None) -> list:
    queries = plan.get("queries") or [question]
    if progress:
        progress(f"Searching {len(queries)} queries...", 0.15)
    web = _search(queries)
    if progress:
        progress("Reading results and scoring fit...", 0.65)

    must = "; ".join(plan.get("must_have", []) or [])
    excl = "; ".join(plan.get("exclude", []) or [])
    task = f"""TASK: Find companies matching this request: "{question}"
Interpretation: {plan.get('interpretation', question)}
Must have: {must or 'no extra constraints'}
Leave out: {excl or 'nothing specific'}"""

    known_names = [c.get("company", "") for c in pipeline]
    raw = _extract(web, task, icp, cfg, known_names)
    return _finish(raw, pipeline, icp, "scout:freeform")


# ── 2. Competitor event exhibitors ────────────────────────────────────────────
def find_rival_events(icp: dict, cfg: dict) -> list:
    """Name the conferences chasing the same buyers."""
    prompt = f"""You know the B2B conference landscape.

OUR EVENT: {ai.event_label(cfg)}
FOCUS: {cfg.get('focus', '')}
AUDIENCE:
{ai.audience_block(icp)}

List 6-10 OTHER conferences, trade shows or summits that target substantially
the same buyers. Include the big trade-association shows, not just direct
competitors.

Return ONLY valid JSON:
[{{"event": "Event name", "organiser": "Who runs it", "why": "Why the audience overlaps"}}]
"""
    out = ai.ask(prompt, max_tokens=1400)
    return out if isinstance(out, list) else []


def hunt_rivals(events: list, pipeline: list, icp: dict, cfg: dict,
                progress=None) -> list:
    """A company already paying to exhibit somewhere has budget and intent. That
    makes rival exhibitor lists the highest-conviction source we have."""
    queries = []
    year = datetime.now().year
    for e in events[:6]:
        name = e.get("event") if isinstance(e, dict) else str(e)
        if not name:
            continue
        queries += [
            f"{name} {year} exhibitor list",
            f"{name} {year} sponsors partners",
        ]
    if progress:
        progress(f"Pulling exhibitor lists for {len(events[:6])} events...", 0.2)
    web = _search(queries, per_query=4)
    if progress:
        progress("Matching exhibitors to your audience...", 0.7)

    names = ", ".join(str(e.get("event", e)) for e in events[:6])
    task = f"""TASK: From exhibitor and sponsor lists for these competitor events
({names}), find companies that would also sponsor OUR event.

For each, set "signal" to which event they exhibit at, e.g. "Exhibits at MDM West".
That is the proof they already spend money to reach these buyers."""

    known_names = [c.get("company", "") for c in pipeline]
    raw = _extract(web, task, icp, cfg, known_names, max_tokens=4000)
    return _finish(raw, pipeline, icp, "scout:rivals")


# ── 3. Lapsed and gone quiet ──────────────────────────────────────────────────
def find_lapsed(pipeline: list, quiet_days: int = 30) -> list:
    """Pure local analysis — no API calls, so this is instant and free.

    Three kinds of dormant revenue:
      lost      explicitly closed_lost
      lapsed    marked as a past sponsor but not currently in play
      quiet     mid-conversation and nothing logged for a while
    """
    out = []
    for c in pipeline:
        status = normalize_status(c.get("status", ""))
        stage = (c.get("stage") or "").lower()
        days = days_since_last_activity(c)
        kind = reason = None

        # A company that has signed for this edition is not dormant revenue,
        # whatever its stage still says. Six of the 2026 B2B Atlanta sponsors
        # kept stage="Lapsed Sponsor" from last year and were being surfaced
        # as re-open targets — the worst possible false positive.
        if status == "closed_won" or c.get("sponsor_confirmed"):
            continue

        if status == "closed_lost":
            kind, reason = "lost", "Marked closed lost"
        elif "lapsed" in stage:
            kind, reason = "lapsed", c.get("stage", "Lapsed sponsor")
        elif status in ("contacted", "replied", "meeting_booked", "contract_out"):
            if days is not None and days >= quiet_days:
                kind = "quiet"
                reason = f"No activity in {days} days, still at {status.replace('_', ' ')}"
            elif days is None:
                kind = "quiet"
                reason = f"At {status.replace('_', ' ')} with nothing logged"

        if not kind:
            continue

        contacts = get_contacts(c)
        out.append({
            **c,
            "_kind": kind,
            "_reason": reason,
            "_days": days,
            "_contact": contacts[0].get("name", "") if contacts else "",
            "_has_email": any(ct.get("email") for ct in contacts),
        })

    rank = {"quiet": 0, "lapsed": 1, "lost": 2}
    return sorted(out, key=lambda x: (rank.get(x["_kind"], 3), -(x.get("score") or 0)))


def reopen_angle(company: dict, icp: dict, cfg: dict) -> dict:
    """A reason to come back that isn't 'just following up'."""
    prompt = f"""You are a sponsorship sales rep for {ai.event_label(cfg)}.

AUDIENCE:
{ai.audience_block(icp)}

DORMANT ACCOUNT:
- Company: {company.get('company', '')}
- What they do: {company.get('what_they_do', '')}
- Why it stalled: {company.get('_reason', '')}
- Last known stage: {company.get('status', '')}
- Previous pitch angle: {company.get('pitch_angle', '')}

Give a reason to re-open that is genuinely new, not "just following up".
Anchor it in something that has changed: the audience, the agenda, remaining
inventory, or who else has signed.

Return ONLY valid JSON:
{{"angle": "<one sentence>", "opener": "<the first line of the email, under 25 words>", "confidence": "<high|medium|low>"}}
"""
    return ai.ask(prompt, max_tokens=500)


# ── 4. New markets ────────────────────────────────────────────────────────────
def hunt_markets(pipeline: list, icp: dict, cfg: dict, progress=None) -> list:
    """Where is there a vendor community big enough to carry an event WBR
    doesn't run yet? Returns market opportunities, not companies."""
    focus = cfg.get("focus", "")
    if progress:
        progress("Scanning adjacent categories...", 0.2)
    web = _search([
        f"fastest growing B2B software categories {datetime.now().year}",
        f"emerging vendor categories adjacent to {focus[:120]}",
        f"B2B conference gaps underserved {focus[:80]} vendors",
        f"venture funding rounds {focus[:80]} {datetime.now().year}",
    ], per_query=5)
    if progress:
        progress("Assessing which could carry an event...", 0.7)

    have = ", ".join(sorted({c.get("category", "") for c in pipeline if c.get("category")}))[:1500]

    prompt = f"""You advise a B2B conference company on which events to launch.

CURRENT EVENT: {ai.event_label(cfg)}
FOCUS: {focus}
BUYERS WE ALREADY REACH:
{ai.audience_block(icp)}
VENDOR CATEGORIES ALREADY IN OUR PIPELINE: {have or 'none recorded'}

SEARCH RESULTS:
{web[:40000]}

Identify 4-6 market opportunities: categories where enough vendors exist, with
budget, chasing buyers we can credibly convene, and no dominant event already
serving them. Favour adjacency to what we run over blue sky.

For vendor_count give a rough count of serious vendors. For confidence, judge
how well the sources support it rather than how attractive it sounds.

Return ONLY valid JSON:
[{{
  "market": "Market or category name",
  "why_now": "What makes this the moment, grounded in the sources",
  "buyers": "Who would attend",
  "vendor_count": "<rough number of vendors who could sponsor>",
  "sample_vendors": ["3-6 named companies"],
  "adjacency": "<how it connects to what we already run>",
  "confidence": "<high|medium|low>"
}}]
"""
    out = ai.ask(prompt, max_tokens=3500)
    return out if isinstance(out, list) else []


# ── Local search over what we already have ────────────────────────────────────
def search_pipeline(pipeline: list, query: str, limit: int = 40) -> list:
    """Instant substring match across the fields worth searching. Runs before
    any live lookup so an account you already own never looks like a new find."""
    q = (query or "").lower().strip()
    if not q:
        return []
    terms = [t for t in q.split() if t]
    fields = ("company", "what_they_do", "category", "fit_reason",
              "pitch_angle", "outreach_note", "signal")

    scored = []
    for c in pipeline:
        hay = " ".join(str(c.get(f, "") or "") for f in fields).lower()
        hay += " " + " ".join(
            f"{ct.get('name', '')} {ct.get('title', '')} {ct.get('email', '')}"
            for ct in get_contacts(c)
        ).lower()
        hits = sum(1 for t in terms if t in hay)
        if not hits:
            continue
        exact = 2 if q in (c.get("company", "") or "").lower() else 0
        scored.append((hits + exact, c))

    scored.sort(key=lambda x: (-x[0], -(x[1].get("score") or 0)))
    return [c for _, c in scored[:limit]]
