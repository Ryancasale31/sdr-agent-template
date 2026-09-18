"""
Pipeline — accounts, the board, and every contact in one place.

Replaces the old Pipeline, Funnel and Contacts tabs. They were three screens
answering one question ("what have I got and where is it"), so they are now
three views of the same data rather than three destinations.
"""
import csv
import io

import streamlit as st

from core import ai
from core import data as D
from ui import components as C
from ui import theme as T

PAGE = 20


# ══════════════════════════════════════════════════════════════════════════════
# Account detail
# ══════════════════════════════════════════════════════════════════════════════
def render_account(company_name: str):
    pipeline = D.load_pipeline()
    company = D.get_company(pipeline, company_name)

    if st.button("← Back to pipeline"):
        D.close_account()

    if not company:
        st.error(f"Account '{company_name}' not found.")
        return

    cfg, icp = D.event_cfg(), D.load_icp()
    status = D.normalize_status(company.get("status", ""))

    st.markdown(
        f'<div class="page-head"><div class="eyebrow">'
        f'{company.get("category", "Account")}</div>'
        f'<h1>{company.get("company", "")}</h1></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        C.score_html(company.get("score")) + " "
        + C.priority_badge_html(company.get("priority", ""))
        + C.stage_badge_html(status)
        + (C.badge_html("Confirmed sponsor", T.GOOD)
           if company.get("sponsor_confirmed") else ""),
        unsafe_allow_html=True,
    )
    st.write("")

    # ── Stage controls ────────────────────────────────────────────────────────
    e1, e2, e3 = st.columns([2, 2, 1])
    cur_pri = company.get("priority") if company.get("priority") in D.PRIORITIES else "cold"
    new_pri = e1.selectbox("Priority", D.PRIORITIES,
                           index=D.PRIORITIES.index(cur_pri), key="acc_pri")
    new_status = e2.selectbox("Sales stage", D.STATUSES,
                              index=D.STATUSES.index(status), key="acc_stage")
    e3.write("")
    e3.write("")
    if e3.button("Save", type="primary", use_container_width=True):
        D.set_stage(company, new_status, new_pri)
        st.success("Saved")
        st.rerun()

    if company.get("what_they_do"):
        st.markdown(f"**What they do:** {company['what_they_do']}")
    if company.get("pitch_angle") or company.get("outreach_note"):
        st.info(f"**Pitch angle:** "
                f"{company.get('pitch_angle') or company.get('outreach_note')}")
    if company.get("fit_reason"):
        st.caption(company["fit_reason"])
    if company.get("vs_sponsor"):
        st.warning(f"**Competitors already sponsoring:** {company['vs_sponsor']}")

    st.divider()
    _contacts_block(company, pipeline, icp, cfg)
    st.divider()
    _activity_block(company, key_prefix="acc")


def _contacts_block(company, pipeline, icp, cfg):
    st.subheader("Contacts")
    contacts = D.get_contacts(company)

    if contacts and not company.get("contacts"):
        company["contacts"] = contacts
        D.persist(company)

    if not contacts:
        st.caption("No contacts yet.")

    def _save_field(ci):
        c = contacts[ci]
        for f in ("name", "title", "email", "phone", "notes"):
            c[f] = st.session_state.get(f"ct_{f}_{ci}", c.get(f, ""))
        company["contacts"] = contacts
        D.persist(company)

    for ci, contact in enumerate(contacts):
        label = contact.get("name") or "(unnamed contact)"
        if contact.get("title"):
            label += f" — {contact['title']}"
        with st.expander(label, expanded=len(contacts) == 1):
            a, b = st.columns(2)
            a.text_input("Name", contact.get("name", ""), key=f"ct_name_{ci}",
                         on_change=_save_field, args=(ci,))
            b.text_input("Title", contact.get("title", ""), key=f"ct_title_{ci}",
                         on_change=_save_field, args=(ci,))
            a.text_input("Email", contact.get("email", ""), key=f"ct_email_{ci}",
                         on_change=_save_field, args=(ci,))
            b.text_input("Phone", contact.get("phone", ""), key=f"ct_phone_{ci}",
                         on_change=_save_field, args=(ci,))
            if contact.get("linkedin"):
                st.caption(f"[LinkedIn]({contact['linkedin']})")
            st.text_area("Notes", contact.get("notes", ""), key=f"ct_notes_{ci}",
                         height=80, on_change=_save_field, args=(ci,))

            acts = st.columns(5)
            for col, (atype, lbl) in zip(acts, [
                ("email_sent", "Email"), ("reply_received", "Reply"),
                ("call", "Call"), ("meeting", "Meeting"),
            ]):
                if col.button(lbl, key=f"ct_act_{ci}_{atype}", use_container_width=True):
                    D.log_contact_activity(contact, atype)
                    company["contacts"] = contacts
                    D.persist(company)
                    st.rerun()
            if acts[4].button("Remove", key=f"ct_del_{ci}", use_container_width=True):
                contacts.pop(ci)
                company["contacts"] = contacts
                D.persist(company)
                st.rerun()

            clog = sorted(contact.get("activity_log", []),
                          key=lambda x: x.get("date", ""), reverse=True)
            for entry in clog[:8]:
                lbl = D.ACTIVITY_LABELS.get(entry["type"], entry["type"])
                detail = entry.get("note") or entry.get("subject") or ""
                st.caption(f"{lbl} · {entry.get('date', '')}"
                           + (f" — {detail}" if detail else ""))

    with st.expander("Add a contact"):
        a, b = st.columns(2)
        nn = a.text_input("Name", key="newc_name")
        nt = b.text_input("Title", key="newc_title")
        ne = a.text_input("Email", key="newc_email")
        nph = b.text_input("Phone", key="newc_phone")
        if st.button("Add contact", type="primary", key="newc_add") and (nn or ne):
            contacts.append({"name": nn, "title": nt, "email": ne, "phone": nph,
                             "notes": "", "activity_log": []})
            company["contacts"] = contacts
            D.persist(company)
            st.rerun()

    # ── Draft outreach ────────────────────────────────────────────────────────
    if contacts:
        st.write("")
        if st.button("Draft outreach for this account", type="primary", key="acc_draft"):
            if not ai.ai_available():
                st.warning("Needs ANTHROPIC_API_KEY in secrets.")
            else:
                ct = contacts[0]
                with st.spinner("Writing..."):
                    try:
                        company["emails"] = ai.generate_sequence(
                            company, ct.get("name", ""), ct.get("title", ""), icp, cfg)
                        if D.normalize_status(company.get("status", "")) == "researched":
                            company["status"] = "contacted"
                        D.persist(company)
                        st.success("Sequence drafted. It's in Outreach.")
                    except Exception as e:
                        st.error(f"Could not draft: {e}")


def _activity_block(company, key_prefix: str):
    st.subheader("Activity")
    log = sorted(company.get("activity_log", []),
                 key=lambda x: x.get("date", ""), reverse=True)
    if log:
        for entry in log[:12]:
            lbl = D.ACTIVITY_LABELS.get(entry["type"],
                                        entry["type"].replace("_", " ").title())
            src = " (Outlook)" if entry.get("source") == "outlook" else ""
            detail = entry.get("subject") or entry.get("note") or entry.get("preview", "")
            st.markdown(f"**{lbl}**{src} · {entry.get('date', '')}")
            if detail:
                st.caption(detail[:160])
    else:
        st.caption("Nothing logged yet.")

    cols = st.columns(4)
    quick = [("email_sent", "Log email"), ("reply_received", "Log reply"),
             ("meeting_booked", "Log meeting"), ("call", "Log call")]
    stage_for = {"reply_received": "replied", "meeting_booked": "meeting_booked"}
    for col, (atype, lbl) in zip(cols, quick):
        if col.button(lbl, key=f"{key_prefix}_{atype}", use_container_width=True):
            D.log_activity(company, atype)
            if atype in stage_for:
                company["status"] = stage_for[atype]
            elif D.normalize_status(company.get("status", "")) == "researched":
                company["status"] = "contacted"
            D.persist(company)
            st.rerun()

    note = st.text_input("Add a note", key=f"{key_prefix}_note",
                         placeholder="Left voicemail, asked about budget...")
    if st.button("Save note", key=f"{key_prefix}_savenote") and note:
        D.log_activity(company, "note", note=note)
        D.persist(company)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Accounts list
# ══════════════════════════════════════════════════════════════════════════════
def _accounts(pipeline):
    f1, f2, f3, f4 = st.columns(4)
    stage_f = f1.selectbox("Stage", ["All"] + D.STATUSES, key="pl_stage",
                           format_func=lambda s: D.STATUS_LABELS.get(s, s))
    pri_f = f2.selectbox("Priority", ["All"] + D.PRIORITIES, key="pl_pri")
    cats = sorted({c.get("category", "") for c in pipeline if c.get("category")})
    cat_f = f3.selectbox("Category", ["All"] + cats, key="pl_cat")
    sort_by = f4.selectbox("Sort", ["Score", "Company", "Last activity"], key="pl_sort")

    search = st.text_input("Search accounts, contacts, notes", key="pl_search",
                           placeholder="Type anything...")

    rows = pipeline
    if stage_f != "All":
        rows = [c for c in rows if D.normalize_status(c.get("status", "")) == stage_f]
    if pri_f != "All":
        rows = [c for c in rows if c.get("priority") == pri_f]
    if cat_f != "All":
        rows = [c for c in rows if c.get("category", "") == cat_f]
    if search:
        from core import scout
        rows = scout.search_pipeline(rows, search, limit=500)

    if sort_by == "Score":
        # Closed business sorts last whatever its score. Signed sponsors carry
        # score 100 and hot priority, so without this the first screen of the
        # pipeline is entirely companies you can no longer sell to.
        order = {"hot": 0, "medium": 1, "cold": 2}
        rows = sorted(rows, key=lambda x: (0 if D.is_active(x) else 1,
                                           order.get(x.get("priority"), 3),
                                           -(x.get("score") or 0)))
    elif sort_by == "Company":
        rows = sorted(rows, key=lambda x: (x.get("company") or "").lower())
    else:
        rows = sorted(rows, key=lambda x: (D.days_since_last_activity(x) or 9999))

    # Reset paging whenever the result set changes, otherwise "show more" state
    # from a previous filter leaks into the next one.
    sig = (stage_f, pri_f, cat_f, search, len(rows))
    if st.session_state.get("pl_sig") != sig:
        st.session_state["pl_sig"] = sig
        st.session_state["pl_n"] = PAGE
    show_n = st.session_state.get("pl_n", PAGE)

    st.caption(f"{min(show_n, len(rows))} of {len(rows)} shown · {len(pipeline)} in pipeline")

    for idx, company in enumerate(rows[:show_n]):
        days = D.days_since_last_activity(company)
        meta = f"{days}d since last touch" if days is not None else ""
        row, btn = st.columns([6, 1])
        row.markdown(C.company_row_html(company, meta), unsafe_allow_html=True)
        btn.write("")
        if btn.button("Open", key=f"pl_open_{idx}", use_container_width=True):
            D.open_account(company["company"])

    if show_n < len(rows):
        if st.button(f"Show {min(PAGE, len(rows) - show_n)} more"):
            st.session_state["pl_n"] = show_n + PAGE
            st.rerun()

    st.divider()
    st.download_button("Export pipeline CSV", data=_pipeline_csv(pipeline),
                       file_name="pipeline_export.csv", mime="text/csv")


def _pipeline_csv(pipeline) -> str:
    rows = []
    for c in pipeline:
        base = {
            "Company": c.get("company", ""), "Score": c.get("score", ""),
            "Tier": c.get("tier", ""), "Stage": c.get("status", ""),
            "Priority": c.get("priority", ""), "Category": c.get("category", ""),
            "What They Do": c.get("what_they_do", ""),
            "Pitch Angle": c.get("pitch_angle", ""),
        }
        contacts = D.get_contacts(c)
        if contacts:
            for ct in contacts:
                rows.append({**base, "Contact": ct.get("name", ""),
                             "Title": ct.get("title", ""), "Email": ct.get("email", ""),
                             "Phone": ct.get("phone", ""),
                             "LinkedIn": ct.get("linkedin", "")})
        else:
            rows.append({**base, "Contact": "", "Title": "", "Email": "",
                         "Phone": "", "LinkedIn": ""})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# Board
# ══════════════════════════════════════════════════════════════════════════════
def _board(pipeline):
    counts = D.stage_counts(pipeline)
    C.funnel_bar(counts, D.STATUSES)
    st.write("")

    cols = st.columns(len(D.ACTIVE_STATUSES))
    for col, stage in zip(cols, D.ACTIVE_STATUSES):
        members = sorted(
            [c for c in pipeline if D.normalize_status(c.get("status", "")) == stage],
            key=lambda x: -(x.get("score") or 0),
        )
        with col:
            st.markdown(
                f'<div style="font-size:.76rem;font-weight:650;text-transform:uppercase;'
                f'letter-spacing:.6px;color:{T.STAGE_COLORS[stage]};margin-bottom:8px;">'
                f'{D.STATUS_LABELS[stage]} · {len(members)}</div>',
                unsafe_allow_html=True,
            )
            for si, c in enumerate(members[:10]):
                if st.button(f"{c.get('score', 0)} · {c['company']}",
                             key=f"bd_{stage}_{si}", use_container_width=True):
                    D.open_account(c["company"])
            if len(members) > 10:
                st.caption(f"+{len(members) - 10} more")

    st.divider()
    won = [c for c in pipeline if D.normalize_status(c.get("status", "")) == "closed_won"]
    lost = [c for c in pipeline if D.normalize_status(c.get("status", "")) == "closed_lost"]
    a, b = st.columns(2)
    with a:
        st.markdown(f"##### Closed won ({len(won)})")
        st.caption(", ".join(c["company"] for c in won) or "None yet")
    with b:
        st.markdown(f"##### Closed lost ({len(lost)})")
        st.caption(", ".join(c["company"] for c in lost) or "None")


# ══════════════════════════════════════════════════════════════════════════════
# Contacts
# ══════════════════════════════════════════════════════════════════════════════
def _contacts_table(pipeline):
    import pandas as pd

    rows = []
    for company in pipeline:
        for contact in D.get_contacts(company):
            rows.append({
                "Company": company.get("company", ""),
                "Score": company.get("score", ""),
                "Stage": D.STATUS_LABELS.get(
                    D.normalize_status(company.get("status", "")), ""),
                "Name": contact.get("name", ""),
                "Title": contact.get("title", ""),
                "Email": contact.get("email", ""),
                "Phone": contact.get("phone", ""),
                "LinkedIn": contact.get("linkedin", ""),
            })

    if not rows:
        C.empty("No contacts yet",
                "Open an account and add one, or run contact discovery.")
        return

    C.tile_row([
        ("Contacts", len(rows)),
        ("Companies covered", len({r["Company"] for r in rows})),
        ("With email", sum(1 for r in rows if r["Email"]), "reachable now", True),
    ])
    st.write("")

    f1, f2 = st.columns([3, 1])
    q = f1.text_input("Filter", key="ct_filter",
                      placeholder="Company, name or title...")
    email_only = f2.checkbox("Has email", key="ct_email_only")

    filtered = rows
    if q:
        ql = q.lower()
        filtered = [r for r in filtered
                    if ql in f"{r['Company']} {r['Name']} {r['Title']}".lower()]
    if email_only:
        filtered = [r for r in filtered if r["Email"]]

    st.caption(f"{len(filtered)} of {len(rows)}")
    st.dataframe(pd.DataFrame(filtered), use_container_width=True, hide_index=True)
    st.download_button("Export contacts CSV",
                       data=pd.DataFrame(filtered).to_csv(index=False),
                       file_name="contacts_export.csv", mime="text/csv")


# ══════════════════════════════════════════════════════════════════════════════
def render():
    pipeline = D.load_pipeline()
    C.page_head("Pipeline", f"{len(pipeline)} companies · "
                            f"{sum(len(D.get_contacts(c)) for c in pipeline)} contacts",
                eyebrow="Book of business")

    if not pipeline:
        C.empty("Nothing here yet", "Go to Find and run a hunt.")
        return

    tab_accounts, tab_board, tab_contacts = st.tabs(["Accounts", "Board", "Contacts"])
    with tab_accounts:
        _accounts(pipeline)
    with tab_board:
        _board(pipeline)
    with tab_contacts:
        _contacts_table(pipeline)
