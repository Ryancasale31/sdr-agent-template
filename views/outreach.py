"""
Outreach — drafted sequences, approvals, and the Outlook link.

Two fixes carried over from the old tabs:

1. Approving a sequence used to write status="approved" onto the company, which
   silently destroyed its sales stage (a company at "meeting_booked" dropped back
   to a non-stage). Approval now lives in its own field, so the funnel stays true.
2. Outlook matched prospects on the legacy contact_email field only, so it saw
   almost nobody once contacts moved into a list. It now reads every contact.
"""
import csv
import io

import streamlit as st

import outlook_integration as outlook
from core import ai
from core import data as D
from ui import components as C
from ui import theme as T

SEQ_PENDING, SEQ_APPROVED, SEQ_SKIPPED = "pending", "approved", "skipped"


def _seq_status(company: dict) -> str:
    """Read approval state, migrating records that used the old status field."""
    if company.get("sequence_status"):
        return company["sequence_status"]
    if company.get("status") == "approved":
        return SEQ_APPROVED
    if company.get("status") == "skipped":
        return SEQ_SKIPPED
    return SEQ_PENDING


def _set_seq_status(company: dict, value: str):
    company["sequence_status"] = value
    # Repair legacy records: put the company back on a real sales stage.
    if company.get("status") in ("approved", "skipped"):
        company["status"] = "contacted" if value == SEQ_APPROVED else "researched"
    D.persist(company)


# ── Queue ─────────────────────────────────────────────────────────────────────
def _queue(pipeline, icp, cfg):
    drafted = [c for c in pipeline if c.get("emails")]
    if not drafted:
        C.empty("No sequences drafted yet",
                "Open an account with a contact on it and click "
                "'Draft outreach for this account'.")
        return

    by_state = {s: [c for c in drafted if _seq_status(c) == s]
                for s in (SEQ_PENDING, SEQ_APPROVED, SEQ_SKIPPED)}
    C.tile_row([
        ("Awaiting review", len(by_state[SEQ_PENDING]), "drafted, not approved", True),
        ("Approved", len(by_state[SEQ_APPROVED]), "ready to send"),
        ("Skipped", len(by_state[SEQ_SKIPPED])),
    ])
    st.write("")

    show = st.radio("Show", ["Awaiting review", "Approved", "Skipped", "All"],
                    horizontal=True, label_visibility="collapsed", key="oq_filter")
    wanted = {"Awaiting review": [SEQ_PENDING], "Approved": [SEQ_APPROVED],
              "Skipped": [SEQ_SKIPPED],
              "All": [SEQ_PENDING, SEQ_APPROVED, SEQ_SKIPPED]}[show]
    rows = [c for c in drafted if _seq_status(c) in wanted]

    if not rows:
        st.caption("Nothing in this bucket.")
        return

    for company in rows:
        contacts = D.get_contacts(company)
        who = contacts[0].get("name", "") if contacts else "no contact"
        state = _seq_status(company)
        state_color = {SEQ_APPROVED: T.GOOD, SEQ_SKIPPED: T.INK_FAINT,
                       SEQ_PENDING: T.WARM}[state]

        with st.expander(f"**{company['company']}** · {who} · {state}"):
            st.markdown(C.badge_html(state.title(), state_color)
                        + C.stage_badge_html(company.get("status", "")),
                        unsafe_allow_html=True)

            for email in company.get("emails", []):
                st.markdown(f"**Touch {email.get('touch', '?')} — "
                            f"{email.get('send_day', '')}**")
                st.text_input("Subject", value=email.get("subject", ""),
                              key=f"sub_{company['company']}_{email.get('touch')}")
                st.text_area("Body", value=email.get("body", ""), height=170,
                             key=f"body_{company['company']}_{email.get('touch')}")

            a, b, c = st.columns(3)
            if a.button("Approve", key=f"ap_{company['company']}", type="primary",
                        use_container_width=True):
                _set_seq_status(company, SEQ_APPROVED)
                st.rerun()
            if b.button("Regenerate", key=f"rg_{company['company']}",
                        use_container_width=True):
                if not ai.ai_available():
                    st.warning("Needs ANTHROPIC_API_KEY.")
                else:
                    ct = contacts[0] if contacts else {}
                    with st.spinner("Rewriting..."):
                        try:
                            company["emails"] = ai.generate_sequence(
                                company, ct.get("name", ""), ct.get("title", ""),
                                icp, cfg)
                            D.persist(company)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")
            if c.button("Skip", key=f"sk_{company['company']}",
                        use_container_width=True):
                _set_seq_status(company, SEQ_SKIPPED)
                st.rerun()

    approved = by_state[SEQ_APPROVED]
    if approved:
        st.divider()
        st.download_button(
            f"Export {len(approved)} approved sequences for Tiga",
            data=_tiga_csv(approved), file_name="tiga_import.csv",
            mime="text/csv", type="primary",
        )


def _tiga_csv(companies) -> str:
    rows = []
    for c in companies:
        contacts = D.get_contacts(c)
        ct = contacts[0] if contacts else {}
        name = ct.get("name", "")
        emails = c.get("emails", [])
        row = {
            "First Name": name.split(" ")[0] if name else "",
            "Last Name": " ".join(name.split(" ")[1:]) if name else "",
            "Email": ct.get("email", "") or D.primary_email(c),
            "Job Title": ct.get("title", ""),
            "Company": c.get("company", ""),
        }
        for i in range(3):
            e = emails[i] if len(emails) > i else {}
            row[f"Email {i + 1} Subject"] = e.get("subject", "")
            row[f"Email {i + 1} Body"] = e.get("body", "")
        rows.append(row)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


# ── Outlook ───────────────────────────────────────────────────────────────────
def _mailbox(pipeline):
    if not outlook.is_configured():
        C.empty("Outlook isn't connected yet",
                "Add AZURE_CLIENT_ID, AZURE_CLIENT_SECRET and AZURE_TENANT_ID to "
                "your secrets and this activates.")
        st.markdown(
            "Once connected: replies get flagged automatically, sent touches log "
            "themselves against the account, and you can send approved sequences "
            "without leaving the app."
        )
        return

    if not outlook.is_authenticated():
        st.warning("Outlook is configured but needs a one-time authorisation.")
        st.markdown(f"[Authorise Outlook access]({outlook.get_auth_url()})")
        code = st.text_input("Authorisation code from the redirect URL")
        if code and st.button("Complete authorisation", type="primary"):
            try:
                outlook.exchange_code_for_token(code)
                st.success("Connected.")
                st.rerun()
            except Exception as e:
                st.error(f"Authorisation failed: {e}")
        return

    profile = outlook.get_profile() or {}
    st.success(f"Connected as {profile.get('displayName', '')} "
               f"({profile.get('mail', '')})")

    # Every contact's email, not just the legacy single field.
    email_to_company = {}
    for c in pipeline:
        for ct in D.get_contacts(c):
            if ct.get("email"):
                email_to_company[ct["email"].lower()] = c
    addresses = list(email_to_company.keys())

    if not addresses:
        st.info("No contact email addresses in the pipeline yet.")
        return

    left, right = st.columns(2)
    with left:
        st.subheader("Replies")
        with st.spinner("Checking inbox..."):
            try:
                replies = outlook.get_recent_replies(addresses)
            except Exception as e:
                replies = []
                st.error(f"Could not read inbox: {e}")
        if not replies:
            st.caption("No replies from prospects recently.")
        for msg in replies:
            sender = msg["from"]["emailAddress"]["address"].lower()
            match = email_to_company.get(sender)
            st.markdown(f"**{match['company'] if match else sender}** · "
                        f"{msg['receivedDateTime'][:10]}")
            st.caption(f"Re: {msg['subject']}")
            st.caption(msg.get("bodyPreview", "")[:150])
            if match and st.button("Log reply", key=f"lr_{msg['id'][:8]}"):
                D.log_activity(match, "reply_received", subject=msg["subject"],
                               preview=msg.get("bodyPreview", "")[:150],
                               source="outlook")
                match["status"] = "replied"
                D.persist(match)
                st.rerun()
            st.divider()

    with right:
        st.subheader("Sent")
        with st.spinner("Checking sent items..."):
            try:
                sent = outlook.get_sent_to_prospects(addresses)
            except Exception as e:
                sent = []
                st.error(f"Could not read sent items: {e}")
        if not sent:
            st.caption("Nothing sent to prospects yet.")
        for msg in sent:
            to_addr = (msg["toRecipients"][0]["emailAddress"]["address"].lower()
                       if msg.get("toRecipients") else "")
            match = email_to_company.get(to_addr)
            st.markdown(f"**{match['company'] if match else to_addr}**")
            st.caption(f"{msg['subject']} · {msg['sentDateTime'][:10]}")

    st.divider()
    st.subheader("Send")
    sendable = [c for c in pipeline if c.get("emails") and D.primary_email(c)]
    if not sendable:
        st.caption("Need a contact with an email address and a drafted sequence.")
        return

    options = {f"{c['company']} — {D.primary_email(c)}": c for c in sendable}
    chosen = options[st.selectbox("Contact", list(options.keys()))]
    touch = st.selectbox("Touch", [f"Touch {e.get('touch')} ({e.get('send_day')})"
                                   for e in chosen["emails"]])
    idx = [f"Touch {e.get('touch')} ({e.get('send_day')})"
           for e in chosen["emails"]].index(touch)
    email = chosen["emails"][idx]

    subject = st.text_input("Subject", value=email.get("subject", ""), key="ol_subj")
    body = st.text_area("Body", value=email.get("body", ""), height=220, key="ol_body")

    if st.button("Send", type="primary"):
        to = D.primary_email(chosen)
        try:
            ok = outlook.send_email(to, subject, body)
        except Exception as e:
            ok = False
            st.error(f"Send failed: {e}")
        if ok:
            D.log_activity(chosen, "email_sent", touch=idx + 1, subject=subject,
                           source="outlook")
            if D.normalize_status(chosen.get("status", "")) == "researched":
                chosen["status"] = "contacted"
            D.persist(chosen)
            st.success(f"Sent to {to}")
            st.rerun()
        elif ok is False:
            st.error("Send failed. Check the Outlook connection.")


# ══════════════════════════════════════════════════════════════════════════════
def render():
    pipeline = D.load_pipeline()
    icp, cfg = D.load_icp(), D.event_cfg()
    C.page_head("Outreach", "Review what's drafted, approve it, send it.",
                eyebrow="Sequences")

    tab_queue, tab_mail = st.tabs(["Queue", "Mailbox"])
    with tab_queue:
        _queue(pipeline, icp, cfg)
    with tab_mail:
        _mailbox(pipeline)
