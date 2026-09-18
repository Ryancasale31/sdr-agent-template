"""
Setup — event data, imports and the radar.

Absorbs the old Import, Setup and Event Info tabs. These are all "configure the
event once" jobs, so they belong behind one door rather than three.
"""
import importlib
import os
import tempfile
from pathlib import Path

import streamlit as st

import storage
from core import ai
from core import data as D
from ui import components as C
from ui import theme as T

ROOT = Path(__file__).resolve().parent.parent


# ── Attendees / ICP ───────────────────────────────────────────────────────────
def _attendees(icp, cfg):
    import pandas as pd

    if icp:
        C.tile_row([
            ("Registered buyers", icp.get("buyer_count", "?")),
            ("Senior (VP+)", f"{icp.get('senior_buyer_pct', '?')}%"),
            ("Top companies", len(icp.get("top_companies", []))),
            ("Confirmed sponsors", len(set(icp.get("existing_sponsors", []))), "excluded from hunts", True),
        ])
        if icp.get("top_companies"):
            st.caption("Attending: " + ", ".join(icp["top_companies"][:10]))
        st.write("")
    else:
        C.empty("No buyer profile yet",
                "Upload your registration export to build one.")

    up = st.file_uploader("Attendee registration CSV", type=["csv"], key="att_csv",
                          help="WBR registration export. Needs Account, Job Title, "
                               "Price List Type.")
    if not up:
        return

    raw = up.read()
    import io
    df = pd.read_csv(io.StringIO(raw.decode("utf-8-sig", errors="replace")),
                     on_bad_lines="skip")
    st.success(f"Loaded {len(df)} rows · {len(df.columns)} columns")
    st.dataframe(df.head(8), use_container_width=True, hide_index=True)

    if st.button("Build buyer profile from this file", type="primary", key="att_build"):
        with st.spinner("Analysing attendees..."):
            try:
                import event_setup
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv",
                                                 mode="wb") as tmp:
                    tmp.write(raw)
                    path = tmp.name
                new_icp = event_setup.build_icp_from_csv(path, event_id=D.event_id())
                storage.save_icp(new_icp, event_id=D.event_id())
                os.unlink(path)
                st.success(f"Profile built: {new_icp['buyer_count']} buyers · "
                           f"{new_icp['senior_buyer_pct']}% VP/Director+")
                st.rerun()
            except Exception as e:
                st.error(f"Could not build profile: {e}")


# ── Confirmed sponsors ────────────────────────────────────────────────────────
def _sponsors(icp):
    st.caption(
        "Companies here are never suggested by any hunt and are excluded from "
        "outreach. Keep this current — it is the single biggest cause of "
        "pitching someone who already signed."
    )
    current = sorted(set(icp.get("existing_sponsors", [])))
    edited = st.text_area(
        "One company per line", value="\n".join(current), height=220, key="sp_list")

    if st.button("Save sponsor list", type="primary", key="sp_save"):
        names = [n.strip() for n in edited.splitlines() if n.strip()]
        new_icp = {**icp, "existing_sponsors": names}
        try:
            storage.save_icp(new_icp, event_id=D.event_id())
        except Exception as e:
            st.error(f"Could not save: {e}")
            return

        # Mirror into the pipeline so the funnel and the hunts agree.
        pipeline = D.load_pipeline()
        from core.scout import _norm
        wanted = {_norm(n) for n in names}
        touched = 0
        for c in pipeline:
            if _norm(c.get("company", "")) in wanted:
                if D.normalize_status(c.get("status", "")) != "closed_won":
                    c["status"] = "closed_won"
                    c["sponsor_confirmed"] = True
                    touched += 1
        if touched:
            D.save_pipeline(pipeline)
        st.success(f"Saved {len(names)} sponsors"
                   + (f" · {touched} pipeline records marked closed won" if touched else ""))
        st.rerun()


# ── Sales Navigator import ────────────────────────────────────────────────────
def _import(icp, cfg):
    import pandas as pd
    import salesnav_import as sni

    with st.expander("How to export from Sales Navigator"):
        st.markdown(
            "**Accounts** — Sales Nav → Accounts → run your search → select → "
            "Export CSV. Reads Account Name, Industry, Headcount, Website, HQ.\n\n"
            "**Leads** — Sales Nav → Leads → run your search → select → Export CSV. "
            "Reads name, title, company, email, LinkedIn URL.\n\n"
            "The type is detected automatically."
        )

    up = st.file_uploader("Sales Navigator CSV", type=["csv"], key="sn_csv")
    if not up:
        return

    import csv as _csv
    import io
    raw = up.read()
    decoded = raw.decode("utf-8-sig", errors="replace")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
        tmp.write(raw)
        path = tmp.name

    headers = list(_csv.DictReader(io.StringIO(decoded)).fieldnames or [])
    kind = sni.detect_csv_type(headers)
    df = pd.read_csv(io.StringIO(decoded), on_bad_lines="skip")
    st.success(f"{len(df)} rows · detected as {kind}")
    st.dataframe(df.head(5), use_container_width=True, hide_index=True)

    if kind == "unknown":
        st.warning("Could not tell whether this is accounts or contacts. "
                   "Check the column names against a fresh Sales Nav export.")

    elif kind == "accounts":
        entries, skipped, total = sni.parse_accounts_csv(path)
        C.tile_row([("New companies", len(entries)),
                    ("Already in pipeline", len(skipped))])
        if entries:
            a, b = st.columns(2)
            score_them = a.checkbox("Score each one with AI", value=False,
                                    help="Roughly 1-2 minutes per 10 companies.")
            limit = b.number_input("Max to import", 1, len(entries),
                                   min(100, len(entries)))
            if st.button("Add to pipeline", type="primary", key="sn_acc"):
                to_add = entries[:limit]
                if score_them and ai.ai_available():
                    prog, stat = st.progress(0.0), st.empty()
                    for i, entry in enumerate(to_add):
                        stat.caption(f"Scoring {entry['company']} ({i + 1}/{len(to_add)})")
                        try:
                            scored = ai.research_company(entry["company"], icp, cfg)
                            entry.update({k: v for k, v in scored.items()
                                          if k != "company"})
                            entry["source"] = "salesnav_import"
                        except Exception:
                            pass
                        prog.progress((i + 1) / len(to_add))
                    prog.empty()
                    stat.empty()
                n = sni.add_accounts_to_pipeline(to_add)
                st.success(f"Added {n} companies.")
                st.rerun()
        else:
            st.info("Everything in this file is already in your pipeline.")

    elif kind == "contacts":
        contacts, total = sni.parse_contacts_csv(path)
        missing = len([c for c in contacts if not c.get("email")])
        C.tile_row([("Contacts", len(contacts)),
                    ("Have email", len(contacts) - missing),
                    ("Need enrichment", missing, "via Tiga", True)])
        if contacts:
            enrich = st.checkbox(f"Enrich {missing} missing emails via Tiga",
                                 value=missing > 0, disabled=missing == 0)
            if st.button("Save contacts", type="primary", key="sn_ct"):
                if enrich and missing:
                    prog, stat = st.progress(0.0), st.empty()

                    def _cb(i, n, name):
                        stat.caption(f"Enriching {name} ({i + 1}/{n})")
                        prog.progress((i + 1) / max(n, 1))

                    contacts, n_en = sni.enrich_contacts_batch(contacts, progress_cb=_cb)
                    prog.empty()
                    stat.empty()
                    st.info(f"Enriched {n_en} contacts.")
                n_saved = sni.save_contacts_csv(contacts)
                st.success(f"Saved {n_saved} contacts.")

    try:
        os.unlink(path)
    except Exception:
        pass


# ── Agenda ────────────────────────────────────────────────────────────────────
def _agenda(cfg):
    import pandas as pd

    path = f"{D.event_id()}_agenda.json"
    sessions = D.load_json(path, [])

    st.caption("The radar and the hunts read the agenda to understand what the "
               "event is actually about, so keeping it current sharpens scoring.")

    up = st.file_uploader("Agenda file (CSV, Excel or Word)", key="ag_up")
    if up:
        df = _parse_agenda(up)
        if df is not None and not df.empty:
            df.columns = [str(c).strip() for c in df.columns]
            cols = list(df.columns)
            st.success(f"{len(df)} rows · {', '.join(cols)}")
            st.dataframe(df.head(5), use_container_width=True, hide_index=True)

            def pick(label, hints):
                guess = next((c for c in cols for h in hints if h in c.lower()), cols[0])
                return st.selectbox(label, ["(none)"] + cols,
                                    index=cols.index(guess) + 1 if guess in cols else 0,
                                    key=f"ag_{label}")

            m1, m2, m3, m4 = st.columns(4)
            with m1: c_sess = pick("Session", ["session", "title", "topic", "agenda"])
            with m2: c_time = pick("Time", ["time", "start", "slot"])
            with m3: c_spk = pick("Speaker", ["speaker", "presenter", "host"])
            with m4: c_trk = pick("Track", ["track", "room", "stream", "day"])

            if c_sess != "(none)" and st.button("Save agenda", type="primary"):
                parsed = [{
                    "time": str(r[c_time]).strip() if c_time != "(none)" else "",
                    "session": str(r[c_sess]).strip(),
                    "speaker": str(r[c_spk]).strip() if c_spk != "(none)" else "",
                    "track": str(r[c_trk]).strip() if c_trk != "(none)" else "",
                } for _, r in df.iterrows()]
                D.save_json(path, parsed)
                st.success(f"Saved {len(parsed)} sessions.")
                st.rerun()

    if sessions:
        st.markdown(f"**{len(sessions)} sessions**")
        st.dataframe(pd.DataFrame(sessions), use_container_width=True, hide_index=True)
        if st.button("Clear agenda"):
            D.save_json(path, [])
            st.rerun()
    else:
        st.caption("No agenda loaded yet.")


def _parse_agenda(f):
    import io

    import pandas as pd
    name = f.name.lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(io.StringIO(f.read().decode("utf-8-sig", errors="replace")),
                               on_bad_lines="skip")
        if name.endswith((".xlsx", ".xls")):
            return pd.read_excel(f, engine="openpyxl")
        if name.endswith(".docx"):
            from docx import Document
            doc = Document(f)
            rows = []
            for table in doc.tables:
                if len(table.rows) < 2:
                    continue
                header = [c.text.strip() for c in table.rows[0].cells]
                day = header[0] if header else ""
                for tr in table.rows[1:]:
                    cells = [c.text.strip() for c in tr.cells]
                    seen, uniq = set(), []
                    for c in cells[1:]:
                        if c and c not in seen:
                            uniq.append(c)
                            seen.add(c)
                    for sess in uniq:
                        parts = sess.split("\n", 1)
                        rows.append({"Time": cells[0] if cells else "",
                                     "Session": parts[0].strip(),
                                     "Speaker": parts[1].strip() if len(parts) > 1 else "",
                                     "Day": day})
            if rows:
                return pd.DataFrame(rows)
            return pd.DataFrame({"Session": [p.text.strip() for p in doc.paragraphs
                                             if p.text.strip()]})
        st.error(f"Unsupported file type: {name}")
    except Exception as e:
        st.error(f"Could not read that file: {e}")
    return None


# ── Radar ─────────────────────────────────────────────────────────────────────
def _radar(icp, cfg):
    finds = D.load_radar_finds()
    pending = [c for c in finds if not c.get("reviewed")]
    C.tile_row([("Total finds", len(finds)),
                ("Waiting for review", len(pending), "shown in Find", True)])
    st.write("")
    st.caption("A full sweep takes 10-15 minutes. Leave the tab open while it runs.")

    auto = st.checkbox("Auto-add anything scoring 60+", value=True, key="rd_auto")
    if st.button("Run radar now", type="primary", key="rd_run"):
        if not (ai.ai_available() and ai.search_available()):
            st.warning("Needs ANTHROPIC_API_KEY and TAVILY_API_KEY in secrets.")
            return
        with st.spinner("Sweeping the web..."):
            try:
                import radar as radar_module
                importlib.reload(radar_module)
                agenda = D.load_json(f"{D.event_id()}_agenda.json", [])
                found = radar_module.run_radar(
                    auto_add=auto, auto_add_min_score=60, event_cfg=cfg,
                    agenda_sessions=agenda or None, icp=icp, event_id=D.event_id(),
                )
                stats = getattr(radar_module, "_last_run_stats", {})
                if not found and stats.get("total_extracted"):
                    st.info(f"Found {stats['total_extracted']} companies but all "
                            f"{stats.get('total_dupes', 0)} were already known.")
                elif not found:
                    st.info("Nothing new qualified this run.")
                else:
                    added = len([f for f in found if f.get("auto_added")])
                    st.success(f"{len(found)} new companies · {added} auto-added.")
                st.rerun()
            except Exception as e:
                st.error(f"Radar error: {e}")


# ── Connections ─────────────────────────────────────────────────────
_SERVICES = (
    ("Anthropic", "Company research, outreach drafting, and three of the four hunts.",
     lambda: ai.ai_available(), ai.check_anthropic),
    ("Tavily", "The web search behind every live hunt.",
     lambda: ai.search_available(), ai.check_tavily),
    ("GitHub", "Saves your edits so they survive a reboot.",
     lambda: storage.github_configured(), storage.check_github),
)


def _connections():
    C.section("Connections",
              "What the app can actually reach. A dead key looks exactly like an "
              "empty result, so check here first when a screen comes back blank.")

    if st.button("Test all three", type="primary"):
        results = {}
        with st.spinner("Calling each service..."):
            for name, _, _, check in _SERVICES:
                try:
                    results[name] = check()
                except Exception as e:
                    results[name] = (False, str(e))
        st.session_state["conn_results"] = results

    results = st.session_state.get("conn_results", {})

    for name, purpose, configured, _ in _SERVICES:
        with st.container(border=True):
            tested = results.get(name)
            if tested is None:
                label, colour = ("Key present", T.COOL) if configured() else ("No key", T.HOT)
                detail = "Not tested yet." if configured() else "Nothing configured."
            else:
                ok, detail = tested
                label, colour = ("Working", T.GOOD) if ok else ("Not working", T.HOT)
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:10px;'>"
                f"<span style='font-weight:650;'>{name}</span>"
                f"{C.badge_html(label, colour)}</div>"
                f"<div style='color:{T.INK_MUTED};font-size:.85rem;margin-top:2px;'>"
                f"{purpose}</div>"
                f"<div style='font-size:.85rem;margin-top:6px;'>{detail}</div>",
                unsafe_allow_html=True,
            )

    st.caption("Keys are read from the environment first, then the app's secrets. "
               "On Streamlit Cloud that is Settings → Secrets: ANTHROPIC_API_KEY and "
               "TAVILY_API_KEY sit at the top level, GitHub goes in a [github] section "
               "with token, repo and branch.")


# ══════════════════════════════════════════════════════════════════════════════
def render():
    cfg, icp = D.event_cfg(), D.load_icp()
    C.page_head("Setup", f"{cfg.get('name', '')} · {cfg.get('location', '')} · "
                         f"{cfg.get('dates', '')}", eyebrow="Event configuration")

    t_att, t_spon, t_imp, t_ag, t_rad, t_conn = st.tabs(
        ["Attendees", "Confirmed sponsors", "Import", "Agenda", "Radar", "Connections"])
    with t_att:
        _attendees(icp, cfg)
    with t_spon:
        _sponsors(icp)
    with t_imp:
        _import(icp, cfg)
    with t_ag:
        _agenda(cfg)
    with t_rad:
        _radar(icp, cfg)
    with t_conn:
        _connections()
