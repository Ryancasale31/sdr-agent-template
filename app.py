"""
WBR SDR Agent — sponsorship pipeline and new-business engine.

Run with: streamlit run app.py

Structure:
  app.py          gate, chrome, navigation
  ui/             theme tokens and shared components
  core/           data access, AI calls, the Scout engine
  views/          one module per workspace
"""
import streamlit as st

st.set_page_config(
    page_title="WBR SDR Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

from events_registry import EVENTS  # noqa: E402
from ui import theme  # noqa: E402
from ui import components as C  # noqa: E402

theme.inject()


# ── Gate ──────────────────────────────────────────────────────────────────────
def _login():
    st.markdown(
        f"""
<div style="max-width:430px;margin:9vh auto 0;text-align:center;">
  <div style="font-weight:800;font-size:2.4rem;color:{theme.NAVY};letter-spacing:.5px;">
    WBR<span style="color:{theme.ORANGE};">.</span>
  </div>
  <div style="font-size:.66rem;letter-spacing:2.6px;color:{theme.INK_FAINT};
              text-transform:uppercase;margin-top:4px;">Worldwide Business Research</div>
  <h1 style="margin:26px 0 4px;font-size:1.5rem;">SDR Agent</h1>
  <p style="color:{theme.INK_MUTED};font-size:.9rem;margin:0 0 6px;">
    Pick your event to continue.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 1.6, 1])
    with mid:
        selected = st.selectbox(
            "Event",
            options=list(EVENTS.keys()),
            format_func=lambda k: EVENTS[k]["name"],
            label_visibility="collapsed",
        )
        password = st.text_input(
            "Access code", type="password", placeholder="Access code",
            label_visibility="collapsed",
        )
        if st.button("Enter", type="primary", use_container_width=True):
            try:
                expected = st.secrets.get("event_passwords", {}).get(selected, "")
            except Exception:
                expected = ""
            if password == expected or (not expected and not password):
                st.session_state["event_id"] = selected
                st.session_state["event_cfg"] = EVENTS[selected]
                st.rerun()
            else:
                st.error("Incorrect access code.")


if "event_id" not in st.session_state:
    _login()
    st.stop()

# ── Everything below needs an active event ────────────────────────────────────
import storage  # noqa: E402
from core import data as D  # noqa: E402
from views import find as find_view  # noqa: E402
from views import outreach as outreach_view  # noqa: E402
from views import pipeline as pipeline_view  # noqa: E402
from views import setup as setup_view  # noqa: E402
from views import today as today_view  # noqa: E402

cfg = D.event_cfg()
pipeline = D.load_pipeline()
icp = D.load_icp()


# ── Sidebar ───────────────────────────────────────────────────────────────────
def _stat(label, value):
    st.markdown(
        f'<div class="side-stat"><span class="k">{label}</span>'
        f'<span class="v">{value}</span></div>',
        unsafe_allow_html=True,
    )


with st.sidebar:
    st.markdown(
        '<div class="wbr-mark">WBR<span class="dot">.</span></div>'
        '<div class="wbr-sub">SDR Agent</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="margin:14px 0 2px;font-weight:650;font-size:.95rem;">'
        f'{cfg.get("short_name", "")} · {cfg.get("name", "")}</div>'
        f'<div style="font-size:.74rem;color:#90A9CC;">'
        f'{cfg.get("location", "")}<br>{cfg.get("dates", "")}</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    active = D.active_companies(pipeline)
    contacts_n = sum(len(D.get_contacts(c)) for c in pipeline)
    won = sum(1 for c in pipeline if D.normalize_status(c.get("status", "")) == "closed_won")

    _stat("Active prospects", len(active))
    _stat("Contacts", contacts_n)
    _stat("Signed", won)
    if icp.get("buyer_count"):
        _stat("Buyers in room", icp["buyer_count"])

    new_finds = [c for c in D.load_radar_finds() if not c.get("reviewed")]
    replied = [c for c in pipeline if c.get("status") == "replied"]
    if new_finds or replied:
        st.divider()
        if replied:
            st.error(f"{len(replied)} replied — follow up")
        if new_finds:
            st.warning(f"{len(new_finds)} new finds to review")

    st.divider()
    backend = storage.backend_name()
    if backend == "Local":
        st.caption("Storage: local only. Edits reset on reboot.")
    else:
        st.caption(f"Storage: {backend}")
        if st.button("Refresh data", use_container_width=True):
            storage.refresh_cache(event_id=D.event_id())
            st.rerun()

    if st.button("Switch event", use_container_width=True):
        for k in ("event_id", "event_cfg", "account_view"):
            st.session_state.pop(k, None)
        st.rerun()


# ── Navigation ────────────────────────────────────────────────────────────────
# url_path is explicit because every view's entry point is called render(), and
# Streamlit otherwise infers the same pathname for all five and refuses to build
# the navigation.
nav = st.navigation([
    st.Page(today_view.render, title="Today", url_path="today",
            icon=":material/bolt:", default=True),
    st.Page(find_view.render, title="Find", url_path="find",
            icon=":material/travel_explore:"),
    st.Page(pipeline_view.render, title="Pipeline", url_path="pipeline",
            icon=":material/view_kanban:"),
    st.Page(outreach_view.render, title="Outreach", url_path="outreach",
            icon=":material/mail:"),
    st.Page(setup_view.render, title="Setup", url_path="setup",
            icon=":material/settings:"),
])

# An open account takes over the main area; the nav stays put so you can leave.
if st.session_state.get("account_view"):
    pipeline_view.render_account(st.session_state["account_view"])
else:
    nav.run()
