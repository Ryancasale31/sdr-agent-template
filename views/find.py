"""
Find — the new-business engine.

Four hunts, one screen. Ask is the default because typing what you want in a
sentence is faster than remembering which tool does what. Every hunt ends in the
same place: a reviewed list you add to the pipeline in one click.
"""
import streamlit as st

from core import ai
from core import data as D
from core import scout
from ui import components as C
from ui import theme as T

MODES = {
    "Ask": "Describe what you're looking for and search the live web.",
    "Rival events": "Companies already paying to exhibit where your buyers go.",
    "Lapsed & quiet": "Past sponsors and stalled conversations worth reopening.",
    "New markets": "Categories big enough to carry an event we don't run yet.",
    "Review finds": "Anything the overnight radar turned up.",
}


# ── Shared results renderer ───────────────────────────────────────────────────
def _render_candidates(cands: list, key: str, source_label: str):
    if not cands:
        C.empty("Nothing new came back",
                "Everything found is already in your pipeline, or nothing cleared "
                "the fit bar. Try a broader phrasing.")
        return

    st.success(f"{len(cands)} new {'company' if len(cands) == 1 else 'companies'} "
               f"· none already in your pipeline")

    pick_all, add_col, _ = st.columns([1, 1, 3])
    if pick_all.button("Select all", key=f"{key}_all"):
        for i in range(len(cands)):
            st.session_state[f"{key}_chk_{i}"] = True
        st.rerun()

    selected = []
    for i, c in enumerate(cands):
        checked = st.checkbox(
            f"**{c.get('company', '')}** · {c.get('score', 0)}/100 · "
            f"{c.get('category', 'Uncategorised')}",
            key=f"{key}_chk_{i}",
        )
        with st.expander("Why this one", expanded=False):
            a, b = st.columns(2)
            with a:
                st.markdown(f"**What they do:** {c.get('what_they_do', '—')}")
                if c.get("signal"):
                    st.markdown(f"**Signal:** {c['signal']}")
                if c.get("source_url"):
                    st.markdown(f"[Source]({c['source_url']})")
            with b:
                if c.get("fit_reason"):
                    st.info(f"**Fit:** {c['fit_reason']}")
                if c.get("pitch_angle"):
                    st.success(f"**Pitch angle:** {c['pitch_angle']}")
        if checked:
            selected.append(c)

    if selected and add_col.button(f"Add {len(selected)} to pipeline",
                                   type="primary", key=f"{key}_add"):
        pipeline = D.load_pipeline()
        for c in selected:
            entry = {k: v for k, v in c.items() if not k.startswith("_")}
            pipeline = D.upsert_company(pipeline, entry)
        D.save_pipeline(pipeline)
        st.success(f"Added {len(selected)} companies from {source_label}.")
        for i in range(len(cands)):
            st.session_state.pop(f"{key}_chk_{i}", None)
        st.session_state.pop(f"{key}_results", None)
        st.rerun()


def _progress_box():
    bar = st.progress(0.0)
    label = st.empty()

    def update(msg, pct):
        label.caption(msg)
        bar.progress(min(max(pct, 0.0), 1.0))

    def clear():
        bar.empty()
        label.empty()

    return update, clear


def _requires_keys() -> bool:
    missing = []
    if not ai.ai_available():
        missing.append("ANTHROPIC_API_KEY")
    if not ai.search_available():
        missing.append("TAVILY_API_KEY")
    if missing:
        st.warning(
            "Live hunting needs " + " and ".join(f"`{m}`" for m in missing)
            + " in your secrets. Lapsed & quiet works without them."
        )
        return False
    return True


# ── Mode: Ask ─────────────────────────────────────────────────────────────────
def _mode_ask(pipeline, icp, cfg):
    st.markdown("##### What are you looking for?")
    question = st.text_input(
        "Search", key="ask_q", label_visibility="collapsed",
        placeholder="e.g. PIM vendors selling to industrial distributors that "
                    "raised funding this year",
    )

    # Instant local matches first, so an account you already own never shows up
    # as a shiny new find.
    if question:
        owned = scout.search_pipeline(pipeline, question, limit=6)
        if owned:
            with st.expander(f"Already in your pipeline ({len(owned)})", expanded=True):
                for i, c in enumerate(owned):
                    row, btn = st.columns([6, 1])
                    row.markdown(C.company_row_html(c), unsafe_allow_html=True)
                    btn.write("")
                    if btn.button("Open", key=f"ask_own_{i}", use_container_width=True):
                        D.open_account(c["company"])

    c1, c2 = st.columns([1, 4])
    if c1.button("Plan search", type="primary", disabled=not question):
        if _requires_keys():
            with st.spinner("Working out what to search for..."):
                try:
                    st.session_state["ask_plan"] = scout.plan_query(question, icp, cfg)
                except Exception as e:
                    st.error(f"Could not plan that search: {e}")

    plan = st.session_state.get("ask_plan")
    if not plan:
        return

    with st.container(border=True):
        st.markdown(f"**Reading that as:** {plan.get('interpretation', '')}")
        queries = st.text_area(
            "Searches it will run (edit freely)",
            value="\n".join(plan.get("queries", [])),
            height=110, key="ask_queries",
        )

    if st.button("Run the hunt", type="primary", key="ask_run"):
        plan = {**plan, "queries": [q.strip() for q in queries.splitlines() if q.strip()]}
        update, clear = _progress_box()
        try:
            results = scout.hunt_freeform(question, plan, pipeline, icp, cfg, update)
            st.session_state["ask_results"] = results
        except Exception as e:
            st.error(f"Hunt failed: {e}")
        finally:
            clear()

    if "ask_results" in st.session_state:
        st.divider()
        _render_candidates(st.session_state["ask_results"], "ask", "your search")


# ── Mode: Rival events ────────────────────────────────────────────────────────
def _mode_rivals(pipeline, icp, cfg):
    st.caption(
        "A company already paying for a booth somewhere has budget and has "
        "decided these buyers are worth reaching. That makes rival exhibitor "
        "lists the warmest cold list available."
    )

    if st.button("Find competing events", type="primary", key="rv_events"):
        if _requires_keys():
            with st.spinner("Identifying events chasing the same buyers..."):
                try:
                    st.session_state["rv_events_list"] = scout.find_rival_events(icp, cfg)
                except Exception as e:
                    st.error(f"Could not identify events: {e}")

    events = st.session_state.get("rv_events_list")
    if not events:
        return

    st.markdown("##### Which events should I pull exhibitors from?")
    chosen = []
    for i, e in enumerate(events):
        name = e.get("event", "") if isinstance(e, dict) else str(e)
        if st.checkbox(f"**{name}** — {e.get('organiser', '')}" if isinstance(e, dict)
                       else name, key=f"rv_e_{i}", value=i < 4):
            chosen.append(e)
        if isinstance(e, dict) and e.get("why"):
            st.caption(f"　{e['why']}")

    if chosen and st.button(f"Pull exhibitors from {len(chosen)} events",
                            type="primary", key="rv_run"):
        update, clear = _progress_box()
        try:
            st.session_state["rv_results"] = scout.hunt_rivals(
                chosen, pipeline, icp, cfg, update)
        except Exception as e:
            st.error(f"Hunt failed: {e}")
        finally:
            clear()

    if "rv_results" in st.session_state:
        st.divider()
        _render_candidates(st.session_state["rv_results"], "rv", "rival events")


# ── Mode: Lapsed & quiet ──────────────────────────────────────────────────────
KIND_STYLE = {
    "quiet": ("Gone quiet", T.STAGE_COLORS["meeting_booked"]),
    "lapsed": ("Lapsed sponsor", T.STAGE_COLORS["replied"]),
    "lost": ("Closed lost", T.STAGE_COLORS["closed_lost"]),
}


def _mode_lapsed(pipeline, icp, cfg):
    st.caption(
        "No searching needed — this reads your own pipeline. Cheapest revenue "
        "in the building is a company that already said yes once."
    )

    quiet_days = st.slider("Count as quiet after", 7, 120, 30, step=7,
                           format="%d days", key="lp_days")
    rows = scout.find_lapsed(pipeline, quiet_days=quiet_days)

    if not rows:
        C.empty("Nothing dormant",
                "Every account in play has recent activity. That's a good problem.")
        return

    counts = {}
    for r in rows:
        counts[r["_kind"]] = counts.get(r["_kind"], 0) + 1
    C.tile_row([
        ("Gone quiet", counts.get("quiet", 0), "mid-conversation, stalled", True),
        ("Lapsed sponsors", counts.get("lapsed", 0), "sponsored before"),
        ("Closed lost", counts.get("lost", 0), "worth a second look"),
    ])
    st.write("")

    kinds = st.multiselect("Show", list(KIND_STYLE.keys()),
                           default=list(KIND_STYLE.keys()),
                           format_func=lambda k: KIND_STYLE[k][0], key="lp_kinds")
    shown = [r for r in rows if r["_kind"] in kinds]
    st.caption(f"{len(shown)} accounts")

    for i, r in enumerate(shown[:40]):
        label, color = KIND_STYLE[r["_kind"]]
        head, act = st.columns([6, 1])
        with head:
            st.markdown(
                '<div class="row">'
                + C.score_html(r.get("score"))
                + f'<div><div class="name">{r.get("company", "")}</div>'
                + f'<div class="meta">{r.get("_reason", "")}'
                + (f' · {r["_contact"]}' if r.get("_contact") else " · no contact")
                + "</div></div><div class='spacer'></div>"
                + C.badge_html(label, color)
                + "</div>",
                unsafe_allow_html=True,
            )
        with act:
            st.write("")
            if st.button("Open", key=f"lp_open_{i}", use_container_width=True):
                D.open_account(r["company"])

        with st.expander("Suggest a way back in"):
            if st.button("Write me an angle", key=f"lp_ang_{i}"):
                if _requires_keys():
                    with st.spinner("Thinking of a reason to call..."):
                        try:
                            st.session_state[f"lp_angle_{i}"] = scout.reopen_angle(
                                r, icp, cfg)
                        except Exception as e:
                            st.error(f"Failed: {e}")
            angle = st.session_state.get(f"lp_angle_{i}")
            if angle:
                st.info(f"**Angle:** {angle.get('angle', '')}")
                st.markdown(f"**Opening line:** {angle.get('opener', '')}")
                st.caption(f"Confidence: {angle.get('confidence', 'unknown')}")


# ── Mode: New markets ─────────────────────────────────────────────────────────
def _mode_markets(pipeline, icp, cfg):
    st.caption(
        "Looks one step sideways from what we already run: categories with "
        "enough funded vendors and no event already owning them."
    )

    if st.button("Scan for market gaps", type="primary", key="mk_run"):
        if _requires_keys():
            update, clear = _progress_box()
            try:
                st.session_state["mk_results"] = scout.hunt_markets(
                    pipeline, icp, cfg, update)
            except Exception as e:
                st.error(f"Scan failed: {e}")
            finally:
                clear()

    results = st.session_state.get("mk_results")
    if not results:
        return

    st.divider()
    conf_color = {"high": T.GOOD, "medium": T.WARM, "low": T.INK_FAINT}
    for m in results:
        conf = (m.get("confidence") or "low").lower()
        st.markdown(
            '<div class="card">'
            f'<h4>{m.get("market", "")}</h4>'
            f'<p class="sub">{m.get("adjacency", "")}</p>'
            "</div>",
            unsafe_allow_html=True,
        )
        a, b = st.columns([3, 2])
        with a:
            st.markdown(f"**Why now:** {m.get('why_now', '')}")
            st.markdown(f"**Who'd attend:** {m.get('buyers', '')}")
        with b:
            st.markdown(
                C.badge_html(f"Confidence: {conf}", conf_color.get(conf, T.INK_FAINT))
                + C.badge_html(f"~{m.get('vendor_count', '?')} vendors", T.BLUE),
                unsafe_allow_html=True,
            )
            if m.get("sample_vendors"):
                st.caption("Named vendors: " + ", ".join(m["sample_vendors"]))
        st.write("")


# ── Mode: Review finds ────────────────────────────────────────────────────────
def _mode_review(pipeline, icp, cfg):
    finds = D.load_radar_finds()
    pending = [c for c in finds if not c.get("reviewed")]
    done = [c for c in finds if c.get("reviewed")]

    st.caption(f"{len(pending)} waiting · {len(done)} already reviewed")

    if not pending:
        C.empty("All caught up", "The radar adds new finds here as it runs.")
        return

    if st.button(f"Add all {len(pending)} to pipeline", type="primary", key="rf_all"):
        pl = D.load_pipeline()
        for rc in finds:
            if not rc.get("reviewed"):
                rc["reviewed"] = True
                entry = {k: v for k, v in rc.items()
                         if k not in ("reviewed", "dismissed")}
                entry["status"] = "researched"
                pl = D.upsert_company(pl, entry)
        D.save_pipeline(pl)
        D.save_radar_finds(finds)
        st.success(f"Added {len(pending)} companies.")
        st.rerun()

    for i, c in enumerate(pending):
        with st.expander(f"**{c.get('company', '')}** · {c.get('score', 0)}/100 · "
                         f"{c.get('signal', '')}"):
            a, b = st.columns(2)
            with a:
                st.markdown(f"**What they do:** {c.get('what_they_do', '—')}")
                st.markdown(f"**Category:** {c.get('category', '—')}")
                if c.get("source_url"):
                    st.markdown(f"[Source]({c['source_url']})")
            with b:
                st.info(f"**Pitch angle:** {c.get('pitch_angle', '—')}")
                st.markdown(f"**Fit:** {c.get('fit_reason', '—')}")

            keep, drop = st.columns(2)
            if keep.button("Add to pipeline", key=f"rf_add_{i}", type="primary"):
                pl = D.load_pipeline()
                entry = {k: v for k, v in c.items() if k not in ("reviewed", "dismissed")}
                entry["status"] = "researched"
                pl = D.upsert_company(pl, entry)
                D.save_pipeline(pl)
                for rc in finds:
                    if rc.get("company") == c.get("company"):
                        rc["reviewed"] = True
                D.save_radar_finds(finds)
                st.rerun()
            if drop.button("Dismiss", key=f"rf_skip_{i}"):
                for rc in finds:
                    if rc.get("company") == c.get("company"):
                        rc["reviewed"] = True
                        rc["dismissed"] = True
                D.save_radar_finds(finds)
                st.rerun()


# ── Entry ─────────────────────────────────────────────────────────────────────
def render():
    cfg = D.event_cfg()
    pipeline = D.load_pipeline()
    icp = D.load_icp()

    C.page_head("Find", "Four ways to turn up revenue that isn't in the pipeline yet.",
                eyebrow="New business")

    pending = len([c for c in D.load_radar_finds() if not c.get("reviewed")])
    labels = list(MODES.keys())
    if pending:
        labels[-1] = f"Review finds ({pending})"

    mode = st.radio("Hunt", labels, horizontal=True, label_visibility="collapsed",
                    key="find_mode")
    mode = mode.split(" (")[0] if mode.startswith("Review finds") else mode
    st.caption(MODES[mode])
    st.write("")

    {
        "Ask": _mode_ask,
        "Rival events": _mode_rivals,
        "Lapsed & quiet": _mode_lapsed,
        "New markets": _mode_markets,
        "Review finds": _mode_review,
    }[mode](pipeline, icp, cfg)
