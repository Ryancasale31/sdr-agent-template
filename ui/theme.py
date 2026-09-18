"""
Design system for the WBR SDR Agent.

One source of truth for colour, type, spacing and the reusable CSS classes the
views rely on. Import `inject()` once per run, right after st.set_page_config.
"""
import streamlit as st

# ── Brand ─────────────────────────────────────────────────────────────────────
NAVY = "#0E2747"
BLUE = "#1E5BA8"
ORANGE = "#F39200"

# ── Semantic palette ──────────────────────────────────────────────────────────
INK = "#101828"          # primary text
INK_MUTED = "#667085"    # secondary text
INK_FAINT = "#98A2B3"    # tertiary text
LINE = "#E4E7EC"         # borders
SURFACE = "#FFFFFF"      # cards
CANVAS = "#F7F8FA"       # page background
CANVAS_ALT = "#EEF2F7"   # subtle fills

HOT = "#D92D20"
WARM = "#F79009"
COOL = "#0BA5EC"
GOOD = "#12B76A"

# Sales stages, in order, each with a colour for badges and the funnel.
#
# Validated with the dataviz palette validator (light surface). The six worked
# stages pass lightness, chroma and the normal-vision floor; the two CVD warnings
# sit in the 6-8 band, which is legal here because every segment carries a direct
# label and count in the funnel key and the segments are separated by a gap.
# "researched" is deliberately a recessive light neutral rather than a hue: it is
# the not-yet-worked remainder, not a stage anyone is working.
STAGE_COLORS = {
    "researched": "#CBD5E1",
    "contacted": "#1990D6",
    "replied": "#8A5CF0",
    "meeting_booked": "#E08A1E",
    "contract_out": "#A3541F",
    "closed_won": "#0F9E5F",
    "closed_lost": "#B02418",
}

PRIORITY_COLORS = {"hot": HOT, "medium": WARM, "cold": COOL}


def score_color(score: int) -> str:
    """Colour for a 0-100 fit score. Deliberately only three steps — a
    continuous gradient reads as decoration, three steps reads as a decision."""
    if score >= 85:
        return GOOD
    if score >= 70:
        return WARM
    return INK_FAINT


def inject():
    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ── Base ────────────────────────────────────────────────────────────────── */
html, body, [class*="css"], .stMarkdown, button, input, textarea, select {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}}
.stApp {{ background: {CANVAS}; }}
.block-container {{ padding-top: 2rem; padding-bottom: 4rem; max-width: 1400px; }}

h1, h2, h3, h4 {{ color: {INK}; letter-spacing: -0.02em; }}
h1 {{ font-size: 1.75rem !important; font-weight: 700 !important; }}
h2 {{ font-size: 1.3rem !important; font-weight: 650 !important; }}
h3 {{ font-size: 1.05rem !important; font-weight: 650 !important; }}

/* Hide Streamlit chrome we don't want */
#MainMenu, footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] > div {{
    background: linear-gradient(175deg, {NAVY} 0%, #14325C 55%, #16386A 100%);
    padding-top: 1.2rem;
}}
section[data-testid="stSidebar"] * {{ color: #E8EEF7; }}
section[data-testid="stSidebar"] [data-baseweb="select"] *,
section[data-testid="stSidebar"] input {{ color: {NAVY} !important; }}
section[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.12); }}

.wbr-mark {{ font-weight: 800; font-size: 1.9rem; letter-spacing: .5px;
             color: #fff; line-height: 1; }}
.wbr-mark .dot {{ color: {ORANGE}; }}
.wbr-sub {{ font-size: .63rem; letter-spacing: 2.4px; color: #90A9CC;
            text-transform: uppercase; margin: 3px 0 0; }}

/* Sidebar stat strip */
.side-stat {{ display:flex; justify-content:space-between; align-items:baseline;
              padding: 5px 0; }}
.side-stat .k {{ font-size:.76rem; color:#A8BDD9; }}
.side-stat .v {{ font-size:.95rem; font-weight:650; color:#fff; }}

/* Sidebar buttons sit on navy, so the default light-on-light treatment is
   invisible there. Give them a translucent fill and a readable border. */
section[data-testid="stSidebar"] .stButton > button {{
    background: rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.22);
    color:#E8EEF7;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(255,255,255,.16); border-color:#fff; color:#fff;
}}

/* ── Page header ─────────────────────────────────────────────────────────── */
.page-head {{ margin: 0 0 22px; }}
.page-head .eyebrow {{ font-size:.7rem; font-weight:600; letter-spacing:1.6px;
    text-transform:uppercase; color:{ORANGE}; margin-bottom:5px; }}
.page-head h1 {{ margin:0 0 4px; }}
.page-head p {{ margin:0; color:{INK_MUTED}; font-size:.92rem; }}

/* ── Cards ───────────────────────────────────────────────────────────────── */
.card {{
    background:{SURFACE}; border:1px solid {LINE}; border-radius:12px;
    padding:18px 20px; margin-bottom:12px;
}}
.card-tight {{ padding:14px 16px; }}
.card h4 {{ margin:0 0 2px; font-size:1rem; font-weight:650; }}
.card .sub {{ color:{INK_MUTED}; font-size:.84rem; margin:0; }}

/* Stat tile */
.tile {{
    background:{SURFACE}; border:1px solid {LINE}; border-radius:12px;
    padding:16px 18px; height:100%;
}}
.tile .label {{ font-size:.73rem; font-weight:600; letter-spacing:.8px;
    text-transform:uppercase; color:{INK_FAINT}; margin-bottom:6px; }}
.tile .value {{ font-size:1.9rem; font-weight:700; color:{INK}; line-height:1.05; }}
.tile .delta {{ font-size:.79rem; color:{INK_MUTED}; margin-top:3px; }}
.tile.accent {{ border-left:3px solid {ORANGE}; }}

/* ── Badges ──────────────────────────────────────────────────────────────── */
.badge {{
    display:inline-block; font-size:.7rem; font-weight:650; letter-spacing:.2px;
    padding:2px 9px; border-radius:20px; white-space:nowrap; line-height:1.55;
}}
.badge + .badge {{ margin-left:5px; }}

/* Score chip */
.score {{
    display:inline-flex; align-items:center; justify-content:center;
    min-width:42px; height:26px; border-radius:7px; font-weight:700;
    font-size:.82rem; color:#fff; padding:0 7px;
}}

/* ── Row (list item) ─────────────────────────────────────────────────────── */
.row {{
    display:flex; align-items:center; gap:12px; padding:11px 14px;
    border:1px solid {LINE}; border-radius:10px; background:{SURFACE};
    margin-bottom:7px;
}}
.row .name {{ font-weight:600; color:{INK}; font-size:.92rem; }}
.row .meta {{ color:{INK_MUTED}; font-size:.79rem; }}
.row .spacer {{ flex:1; }}

/* ── Funnel ──────────────────────────────────────────────────────────────── */
.funnel {{ display:flex; gap:2px; margin:4px 0 2px; }}
.funnel .seg {{ height:10px; border-radius:3px; }}
.funnel-key {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:10px; }}
.funnel-key .k {{ display:flex; align-items:center; gap:6px;
    font-size:.78rem; color:{INK_MUTED}; }}
.funnel-key .sw {{ width:9px; height:9px; border-radius:2px; }}

/* ── Empty state ─────────────────────────────────────────────────────────── */
.empty {{
    text-align:center; padding:44px 20px; border:1px dashed {LINE};
    border-radius:12px; background:{SURFACE};
}}
.empty .t {{ font-weight:650; color:{INK}; margin-bottom:5px; }}
.empty .d {{ color:{INK_MUTED}; font-size:.87rem; }}

/* ── Streamlit widget polish ─────────────────────────────────────────────── */
.stButton > button {{
    border-radius:8px; font-weight:600; font-size:.86rem; border:1px solid {LINE};
    transition: all .12s ease;
}}
.stButton > button:hover {{ border-color:{BLUE}; color:{BLUE}; }}
.stButton > button[kind="primary"] {{
    background:{ORANGE}; border-color:{ORANGE}; color:#fff;
}}
.stButton > button[kind="primary"]:hover {{
    background:#DD8300; border-color:#DD8300; color:#fff;
}}
div[data-testid="stExpander"] {{
    border:1px solid {LINE} !important; border-radius:12px !important;
    background:{SURFACE}; margin-bottom:9px;
}}
div[data-testid="stExpander"] summary {{ font-size:.92rem; }}
div[data-testid="stExpander"] summary:hover {{ color:{BLUE}; }}
div[data-testid="stMetricValue"] {{ font-size:1.6rem; font-weight:700; }}
.stTextInput input, .stTextArea textarea, .stNumberInput input {{
    border-radius:8px !important;
}}
hr {{ margin: 1.1rem 0; border-color:{LINE}; }}
</style>
""",
        unsafe_allow_html=True,
    )
