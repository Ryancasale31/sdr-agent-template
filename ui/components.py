"""
Reusable UI pieces. Every view builds from these so the app looks like one thing
rather than eleven things that grew separately.
"""
import html

import streamlit as st

from ui import theme as T


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


# ── Page header ───────────────────────────────────────────────────────────────
def page_head(title: str, subtitle: str = "", eyebrow: str = ""):
    parts = ['<div class="page-head">']
    if eyebrow:
        parts.append(f'<div class="eyebrow">{_esc(eyebrow)}</div>')
    parts.append(f"<h1>{_esc(title)}</h1>")
    if subtitle:
        parts.append(f"<p>{_esc(subtitle)}</p>")
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ── Stat tiles ────────────────────────────────────────────────────────────────
def tile(label: str, value, delta: str = "", accent: bool = False):
    cls = "tile accent" if accent else "tile"
    delta_html = f'<div class="delta">{_esc(delta)}</div>' if delta else ""
    st.markdown(
        f'<div class="{cls}"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div>{delta_html}</div>',
        unsafe_allow_html=True,
    )


def tile_row(tiles: list):
    """tiles: list of (label, value, delta, accent) — accent optional."""
    cols = st.columns(len(tiles))
    for col, spec in zip(cols, tiles):
        label, value = spec[0], spec[1]
        delta = spec[2] if len(spec) > 2 else ""
        accent = spec[3] if len(spec) > 3 else False
        with col:
            tile(label, value, delta, accent)


# ── Badges ────────────────────────────────────────────────────────────────────
def badge_html(text: str, color: str) -> str:
    return (
        f'<span class="badge" style="background:{color}1A;color:{color};">'
        f"{_esc(text)}</span>"
    )


def stage_badge_html(status: str) -> str:
    from core.data import STATUS_LABELS, normalize_status

    status = normalize_status(status)
    label = STATUS_LABELS.get(status, status.replace("_", " ").title())
    if status == "researched":
        # The recessive funnel colour is too light to read as badge text.
        return (f'<span class="badge" style="background:{T.CANVAS_ALT};'
                f'color:{T.INK_MUTED};">{_esc(label)}</span>')
    return badge_html(label, T.STAGE_COLORS.get(status, T.INK_FAINT))


def priority_badge_html(priority: str) -> str:
    if not priority:
        return ""
    color = T.PRIORITY_COLORS.get(priority, T.INK_FAINT)
    return badge_html(priority.title(), color)


def score_html(score) -> str:
    try:
        s = int(score or 0)
    except (TypeError, ValueError):
        s = 0
    return f'<span class="score" style="background:{T.score_color(s)};">{s}</span>'


# ── Company row ───────────────────────────────────────────────────────────────
def company_row_html(company: dict, extra_meta: str = "") -> str:
    """One compact line describing a company. Used in lists where the point is
    scanning many at once, not reading any one in depth."""
    meta_bits = []
    if company.get("category"):
        meta_bits.append(_esc(company["category"]))
    contacts = company.get("contacts") or []
    meta_bits.append(f"{len(contacts)} contact{'s' if len(contacts) != 1 else ''}")
    if extra_meta:
        meta_bits.append(_esc(extra_meta))

    return (
        '<div class="row">'
        f"{score_html(company.get('score'))}"
        f'<div><div class="name">{_esc(company.get("company", ""))}</div>'
        f'<div class="meta">{" · ".join(meta_bits)}</div></div>'
        '<div class="spacer"></div>'
        f"{priority_badge_html(company.get('priority', ''))}"
        f"{stage_badge_html(company.get('status', 'researched'))}"
        "</div>"
    )


# ── Funnel bar ────────────────────────────────────────────────────────────────
def funnel_bar(counts: dict, order: list):
    """A single proportional bar broken into stages, with a key beneath.

    A stacked bar beats seven separate numbers here because the question this
    answers is 'where is everything piling up' — that is a part-to-whole
    question, and length is the most accurately read encoding for it.
    Zero-count stages are dropped from the key so it stays scannable.
    """
    total = sum(counts.get(s, 0) for s in order)
    if not total:
        st.markdown(
            '<div class="empty"><div class="t">Nothing in the funnel yet</div></div>',
            unsafe_allow_html=True,
        )
        return

    segs, keys = [], []
    for stage in order:
        n = counts.get(stage, 0)
        if not n:
            continue
        pct = n / total * 100
        color = T.STAGE_COLORS.get(stage, T.INK_FAINT)
        from core.data import STATUS_LABELS

        label = STATUS_LABELS.get(stage, stage)
        segs.append(
            f'<div class="seg" style="width:{pct:.2f}%;background:{color};" '
            f'title="{_esc(label)}: {n}"></div>'
        )
        keys.append(
            f'<div class="k"><span class="sw" style="background:{color};"></span>'
            f"{_esc(label)} <strong style='color:{T.INK};'>{n}</strong></div>"
        )

    st.markdown(
        f'<div class="funnel">{"".join(segs)}</div>'
        f'<div class="funnel-key">{"".join(keys)}</div>',
        unsafe_allow_html=True,
    )


# ── Empty state ───────────────────────────────────────────────────────────────
def empty(title: str, detail: str = ""):
    detail_html = f'<div class="d">{_esc(detail)}</div>' if detail else ""
    st.markdown(
        f'<div class="empty"><div class="t">{_esc(title)}</div>{detail_html}</div>',
        unsafe_allow_html=True,
    )


def section(title: str, caption: str = ""):
    st.markdown(f"### {title}")
    if caption:
        st.caption(caption)
