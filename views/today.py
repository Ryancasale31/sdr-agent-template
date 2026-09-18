"""
Today — what needs you, in priority order.

This is the landing screen because the old app opened on a research box, which
answers a question you rarely have first thing. The question you actually have
is "what should I do now", so the page is ordered by urgency: things that have
gone cold, then replies waiting, then hot accounts with no contact, then new
finds. Everything here is a link into the work, not a report to read.
"""
from datetime import date

import streamlit as st

from core import data as D
from ui import components as C
from ui import theme as T

QUIET_DAYS = 14


def _days_to_event(cfg: dict):
    """Rough countdown from the event's date string. Returns None if unparseable
    rather than guessing, since a wrong countdown is worse than none."""
    raw = (cfg.get("dates") or "")
    import re
    m = re.search(r"([A-Z][a-z]{2})\w*\s+(\d{1,2})[^,]*,?\s*(\d{4})", raw)
    if not m:
        return None
    months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
              "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
    try:
        target = date(int(m.group(3)), months[m.group(1)], int(m.group(2)))
        return (target - date.today()).days
    except Exception:
        return None


def _action_list(companies, empty_msg, key_prefix, meta_fn=None, limit=6):
    if not companies:
        st.caption(empty_msg)
        return
    for i, c in enumerate(companies[:limit]):
        row, btn = st.columns([6, 1])
        with row:
            st.markdown(
                C.company_row_html(c, meta_fn(c) if meta_fn else ""),
                unsafe_allow_html=True,
            )
        with btn:
            st.write("")
            if st.button("Open", key=f"{key_prefix}_{i}", use_container_width=True):
                D.open_account(c["company"])
    if len(companies) > limit:
        st.caption(f"+ {len(companies) - limit} more")


def render():
    cfg = D.event_cfg()
    pipeline = D.load_pipeline()

    countdown = _days_to_event(cfg)
    sub = cfg.get("name", "")
    if countdown is not None and countdown > 0:
        sub += f" · {countdown} days out"

    C.page_head("Today", sub, eyebrow="Priority")

    if not pipeline:
        C.empty("Nothing in the pipeline yet",
                "Head to Find and run a hunt, or add a company by name.")
        return

    active = D.active_companies(pipeline)
    won = [c for c in pipeline if D.normalize_status(c.get("status", "")) == "closed_won"]
    replied = [c for c in active if c.get("status") == "replied"]
    no_contact = [c for c in active if not D.get_contacts(c)]
    new_finds = [c for c in D.load_radar_finds() if not c.get("reviewed")]

    # Gone quiet: mid-conversation, nothing logged recently.
    quiet = []
    for c in active:
        if D.normalize_status(c.get("status", "")) in ("contacted", "replied",
                                                       "meeting_booked", "contract_out"):
            days = D.days_since_last_activity(c)
            if days is None or days >= QUIET_DAYS:
                quiet.append((days if days is not None else 999, c))
    quiet.sort(key=lambda x: -x[0])
    quiet_companies = [c for _, c in quiet]

    # ── Top line ──────────────────────────────────────────────────────────────
    C.tile_row([
        ("Needs action", len(replied) + len(quiet_companies), "replies and stalls", True),
        ("Active prospects", len(active), f"{len(pipeline)} total"),
        ("Signed", len(won), "closed won"),
        ("New finds", len(new_finds), "waiting in Find"),
    ])

    st.write("")

    # ── Funnel ────────────────────────────────────────────────────────────────
    # Raw <div class="card"> can't wrap Streamlit elements — the opening and
    # closing tags land in separate containers and render an empty box. Use a
    # real Streamlit container instead.
    with st.container(border=True):
        st.markdown("**Where everything sits**")
        C.funnel_bar(D.stage_counts(pipeline), D.STATUSES)

    st.write("")
    left, right = st.columns([3, 2], gap="large")

    with left:
        if replied:
            C.section(f"Replied — answer these first ({len(replied)})",
                      "Someone wrote back and is waiting on you.")
            _action_list(replied, "", "rep")
            st.write("")

        if quiet_companies:
            C.section(f"Gone quiet ({len(quiet_companies)})",
                      f"In play but nothing logged for {QUIET_DAYS}+ days.")
            _action_list(
                quiet_companies, "", "qt",
                meta_fn=lambda c: (
                    f"{D.days_since_last_activity(c)}d since last touch"
                    if D.days_since_last_activity(c) is not None
                    else "never touched"
                ),
            )
            st.write("")

        hot_uncontacted = [
            c for c in no_contact
            if c.get("priority") == "hot" or (c.get("score") or 0) >= 85
        ]
        if hot_uncontacted:
            C.section(f"Strong fit, no contact yet ({len(hot_uncontacted)})",
                      "High scores with nobody to email. Find people for these.")
            _action_list(hot_uncontacted, "", "hu")

        if not (replied or quiet_companies or hot_uncontacted):
            C.empty("You're clear",
                    "Nothing stalled and no replies outstanding. Good time to hunt.")

    with right:
        C.section("Recent activity")
        activity = D.recent_activity(pipeline, limit=8)
        if activity:
            for entry in activity:
                label = D.ACTIVITY_LABELS.get(entry["type"],
                                              entry["type"].replace("_", " ").title())
                detail = (entry.get("subject") or entry.get("note")
                          or entry.get("preview") or "")
                st.markdown(
                    f'<div class="card card-tight" style="margin-bottom:7px;">'
                    f'<div style="font-size:.86rem;font-weight:600;">'
                    f'{entry["_company"]}</div>'
                    f'<div style="font-size:.78rem;color:{T.INK_MUTED};">'
                    f'{label} · {entry.get("date", "")}</div>'
                    + (f'<div style="font-size:.78rem;color:{T.INK_FAINT};'
                       f'margin-top:3px;">{detail[:90]}</div>' if detail else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Nothing logged yet. Activity appears here as you work accounts.")

        st.write("")
        C.section("Top unworked")
        unworked = sorted(
            [c for c in active
             if D.normalize_status(c.get("status", "")) == "researched"],
            key=lambda x: -(x.get("score") or 0),
        )[:5]
        if unworked:
            for i, c in enumerate(unworked):
                if st.button(
                    f"{c.get('score', 0)}  ·  {c['company']}",
                    key=f"tu_{i}", use_container_width=True,
                ):
                    D.open_account(c["company"])
        else:
            st.caption("Everything researched has been worked.")
