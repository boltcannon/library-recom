from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from src.chatbot_logic import explain_recommendation
from src.utils import safe_int, shorten_text


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=DM+Sans:wght@400;500;700&display=swap');

        :root {
            --bg: #fcfaf4;
            --surface: #fffdf8;
            --surface-alt: #f7f1df;
            --surface-soft: #f4f8ff;
            --border: #eadfca;
            --text: #2a241b;
            --muted: #6d6458;
            --green: #2f6f4f;
            --green-soft: #e3f2e8;
            --orange: #d7832f;
            --orange-soft: #fff1de;
            --blue: #2a5b8d;
            --blue-soft: #e5f0ff;
            --shadow: 0 12px 32px rgba(84, 66, 32, 0.08);
            --radius-lg: 28px;
            --radius-md: 20px;
            --radius-sm: 14px;
        }

        html, body, [class*="css"] {
            font-family: 'DM Sans', sans-serif;
            color: var(--text);
        }

        .stApp {
            background:
                radial-gradient(circle at top right, rgba(255, 232, 180, 0.35), transparent 28%),
                linear-gradient(180deg, #fffaf0 0%, #fcfaf4 42%, #f7fbff 100%);
        }

        .main .block-container {
            padding-top: 1.4rem;
            padding-bottom: 3rem;
            max-width: 1160px;
        }

        h1, h2, h3, h4, h5 {
            font-family: 'Nunito', sans-serif;
            color: var(--text);
            letter-spacing: -0.02em;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #fff8ea 0%, #f4f7fb 100%);
            border-right: 1px solid rgba(217, 198, 166, 0.55);
        }

        [data-testid="stSidebar"] * {
            color: var(--text);
        }

        [data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.75);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 0.8rem 0.9rem;
            box-shadow: var(--shadow);
        }

        div[data-testid="stForm"],
        div[data-testid="stExpander"] {
            border-radius: var(--radius-md);
        }

        .brand-shell {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            align-items: center;
            margin-bottom: 1rem;
        }

        .brand-mark {
            display: inline-flex;
            align-items: center;
            gap: 0.75rem;
            background: rgba(255, 255, 255, 0.74);
            border: 1px solid rgba(222, 205, 173, 0.95);
            padding: 0.8rem 1rem;
            border-radius: 999px;
            box-shadow: var(--shadow);
        }

        .brand-icon {
            width: 42px;
            height: 42px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #f6c86a 0%, #e98648 100%);
            color: white;
            font-size: 1rem;
            font-weight: 800;
        }

        .brand-title {
            font-family: 'Nunito', sans-serif;
            font-size: 1rem;
            font-weight: 800;
            margin: 0;
        }

        .brand-subtitle {
            color: var(--muted);
            font-size: 0.88rem;
            margin: 0.1rem 0 0 0;
        }

        .app-hero {
            padding: 1.6rem 1.6rem;
            border-radius: var(--radius-lg);
            background:
                radial-gradient(circle at top right, rgba(255,255,255,0.66), transparent 25%),
                linear-gradient(135deg, #fff6df 0%, #eef7ff 58%, #eef6ec 100%);
            border: 1px solid rgba(221, 206, 180, 0.95);
            box-shadow: var(--shadow);
            margin-bottom: 1.1rem;
        }

        .app-kicker {
            color: var(--green);
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.45rem;
        }

        .soft-card,
        .panel-card,
        .journey-card,
        .rec-card,
        .empty-card {
            background: rgba(255, 255, 255, 0.86);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            box-shadow: var(--shadow);
        }

        .soft-card {
            padding: 1rem 1.05rem;
            margin-bottom: 0.8rem;
        }

        .panel-card {
            padding: 1.2rem 1.2rem;
            margin-bottom: 1rem;
        }

        .journey-card {
            padding: 1.25rem 1.2rem;
            margin-bottom: 1rem;
            background: linear-gradient(180deg, rgba(255,255,255,0.92) 0%, rgba(247, 250, 255, 0.95) 100%);
        }

        .rec-card {
            padding: 1.15rem 1.15rem 1rem 1.15rem;
            margin-bottom: 1rem;
            transition: transform 160ms ease, box-shadow 160ms ease;
        }

        .rec-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 18px 38px rgba(84, 66, 32, 0.12);
        }

        .empty-card {
            padding: 1.35rem 1.2rem;
            text-align: center;
            background: linear-gradient(180deg, #fffdfa 0%, #f7fbff 100%);
        }

        .mini-label {
            color: var(--muted);
            font-size: 0.82rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.2rem;
        }

        .section-heading {
            margin: 1rem 0 0.65rem 0;
        }

        .section-heading h2 {
            margin: 0;
            font-size: 1.35rem;
        }

        .section-heading p {
            margin: 0.2rem 0 0 0;
            color: var(--muted);
        }

        .chat-bubble {
            padding: 1rem 1rem;
            border-radius: 18px;
            margin: 0.55rem 0;
            border: 1px solid rgba(223, 211, 188, 0.9);
            box-shadow: var(--shadow);
            animation: fadeUp 220ms ease;
        }

        .chat-bubble.bot {
            background: rgba(248, 251, 255, 0.95);
            border-left: 5px solid var(--blue);
        }

        .chat-bubble.user {
            background: rgba(255, 248, 237, 0.96);
            border-left: 5px solid var(--orange);
        }

        .progress-wrap {
            display: flex;
            gap: 0.55rem;
            flex-wrap: wrap;
            margin: 0.5rem 0 1rem 0;
        }

        .progress-chip {
            padding: 0.55rem 0.9rem;
            border-radius: 999px;
            font-size: 0.85rem;
            font-weight: 700;
            border: 1px solid rgba(220, 208, 183, 0.95);
            background: rgba(255, 255, 255, 0.8);
            color: var(--muted);
        }

        .progress-chip.current {
            background: var(--orange-soft);
            color: #8e4f15;
            border-color: #f0be75;
        }

        .progress-chip.done {
            background: var(--green-soft);
            color: var(--green);
            border-color: #acd3ba;
        }

        .badge-row {
            display: flex;
            gap: 0.45rem;
            flex-wrap: wrap;
            margin: 0.7rem 0 0.9rem 0;
        }

        .badge {
            border-radius: 999px;
            padding: 0.34rem 0.7rem;
            font-size: 0.78rem;
            font-weight: 800;
            line-height: 1;
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
        }

        .badge.green { background: var(--green-soft); color: var(--green); }
        .badge.orange { background: var(--orange-soft); color: #965719; }
        .badge.blue { background: var(--blue-soft); color: var(--blue); }
        .badge.neutral { background: #f3efe8; color: #6a5d4b; }

        .rec-head {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
        }

        .rec-title {
            margin: 0;
            font-size: 1.35rem;
        }

        .rec-meta {
            color: var(--muted);
            margin-top: 0.12rem;
            font-size: 0.92rem;
        }

        .score-pill {
            min-width: 82px;
            padding: 0.65rem 0.8rem;
            text-align: center;
            border-radius: 18px;
            background: linear-gradient(180deg, #fff5de 0%, #ffe1aa 100%);
            border: 1px solid #f1c269;
            color: #8b5217;
            font-weight: 800;
        }

        .score-pill small {
            display: block;
            font-size: 0.7rem;
            color: #9b6932;
            margin-bottom: 0.18rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }

        .meta-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 0.75rem;
            margin-top: 0.2rem;
            margin-bottom: 0.85rem;
        }

        .meta-card {
            background: rgba(249, 247, 241, 0.95);
            border: 1px solid rgba(230, 219, 196, 0.95);
            border-radius: 16px;
            padding: 0.7rem 0.75rem;
        }

        .meta-card strong {
            display: block;
            margin-bottom: 0.12rem;
            font-size: 0.8rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 0.9rem;
            margin: 0.8rem 0 1rem 0;
        }

        .dashboard-kpi {
            padding: 1rem;
            border-radius: 20px;
            border: 1px solid rgba(223, 211, 188, 0.95);
            background: rgba(255, 255, 255, 0.86);
            box-shadow: var(--shadow);
        }

        .dashboard-kpi .label {
            color: var(--muted);
            font-size: 0.82rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.2rem;
        }

        .dashboard-kpi .value {
            font-family: 'Nunito', sans-serif;
            font-size: 1.8rem;
            font-weight: 800;
            color: var(--text);
        }

        .dashboard-kpi .note {
            color: var(--muted);
            font-size: 0.88rem;
            margin-top: 0.15rem;
        }

        @keyframes fadeUp {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand_header(role: str | None = None) -> None:
    subtitle_parts = ['<p class="brand-subtitle">School library discovery and story-based learning</p>']
    if role:
        subtitle_parts.append(f'<p class="brand-subtitle">{escape(role.title())} experience</p>')
    brand_html = (
        '<div class="brand-shell">'
        '<div class="brand-mark">'
        '<div class="brand-icon">SS</div>'
        '<div>'
        '<p class="brand-title">StoryShelf</p>'
        f'{"".join(subtitle_parts)}'
        '</div>'
        '</div>'
        '</div>'
    )
    st.markdown(brand_html, unsafe_allow_html=True)


def render_hero(title: str, body: str, kicker: str = "School Library MVP") -> None:
    st.markdown(
        f"""
        <div class="app-hero">
            <div class="app-kicker">{escape(kicker)}</div>
            <h1 style="margin:0 0 0.35rem 0;">{escape(title)}</h1>
            <p style="margin:0;color:#4e463c;font-size:1rem;max-width:760px;">{escape(body)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_heading(title: str, body: str = "") -> None:
    body_html = f"<p>{escape(body)}</p>" if body else ""
    st.markdown(
        f"""
        <div class="section-heading">
            <h2>{escape(title)}</h2>
            {body_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_chat_bubble(text: str, speaker: str = "bot") -> None:
    bubble_class = "bot" if speaker == "bot" else "user"
    st.markdown(f'<div class="chat-bubble {bubble_class}">{escape(text)}</div>', unsafe_allow_html=True)


def render_status_tip(title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="soft-card">
            <div class="mini-label">{escape(title)}</div>
            <div>{escape(body)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(title: str, body: str, icon: str = "*") -> None:
    st.markdown(
        f"""
        <div class="empty-card">
            <div style="font-size:2rem;margin-bottom:0.35rem;">{escape(icon)}</div>
            <h3 style="margin:0 0 0.35rem 0;">{escape(title)}</h3>
            <p style="margin:0;color:#5f564a;">{escape(body)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_navigation(role: str, user_name: str) -> str:
    st.sidebar.markdown("## StoryShelf")
    st.sidebar.caption(f"Signed in as {user_name}")
    page_options = {
        "student": [
            "Home",
            "Student Dashboard",
            "Find Books",
            "Story-Based Learning",
        ],
        "admin": [
            "Home",
            "Admin Dashboard",
            "Admin: Lesson Review",
            "Admin: User Management",
            "Admin: Upload Catalog",
        ],
    }
    current_options = page_options.get(role, ["Home"])
    current_page = st.session_state.get("nav_page", current_options[0])
    if current_page not in current_options:
        st.session_state["nav_page"] = current_options[0]

    sidebar_key = "sidebar_nav_page"
    if st.session_state.get(sidebar_key) not in current_options:
        st.session_state[sidebar_key] = st.session_state["nav_page"]

    page = st.sidebar.radio(
        "Open a page",
        current_options,
        key=sidebar_key,
        label_visibility="collapsed",
    )
    st.session_state["nav_page"] = page
    st.sidebar.markdown("---")
    flow_text = {
        "student": "Profile -> Find a book -> Build a lesson -> Take the quiz",
        "admin": "Dashboard -> Review lessons -> Manage users -> Upload catalogs",
    }
    st.sidebar.markdown(f"**Suggested flow**\n\n{flow_text.get(role, flow_text['student'])}")
    return page


def render_progress_steps(steps: list[str], current_step: int) -> None:
    chips: list[str] = []
    for index, step in enumerate(steps, start=1):
        chip_class = "done" if index < current_step else "current" if index == current_step else ""
        chips.append(f'<div class="progress-chip {chip_class}">{index}. {escape(step)}</div>')
    st.markdown(f'<div class="progress-wrap">{"".join(chips)}</div>', unsafe_allow_html=True)


def render_metric_grid(items: list[dict[str, str]]) -> None:
    if not items:
        return

    columns = st.columns(len(items))
    for column, item in zip(columns, items):
        with column:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div class="mini-label">{escape(str(item.get("label", "")))}</div>
                    <div style="font-family:'Nunito',sans-serif;font-size:2rem;font-weight:800;line-height:1.1;">{escape(str(item.get("value", "")))}</div>
                    <div style="color:var(--muted);margin-top:0.35rem;">{escape(str(item.get("note", "")))}</div>
                    """,
                    unsafe_allow_html=True,
                )


def _badge_html(label: str, tone: str = "neutral") -> str:
    return f'<span class="badge {escape(tone)}">{escape(label)}</span>'


def render_recommendation_card(row: pd.Series) -> None:
    pages_value = safe_int(row.get("pages"))
    length_type = str(row.get("length_type") or "any").title()
    reading_level = str(row.get("reading_level") or "Mixed").title()
    item_type = str(row.get("item_type") or "Book")
    genre_text = str(row.get("genre_tags") or item_type or "General").replace(",", " | ")
    summary = shorten_text(row.get("abstract", ""), max_words=52)

    with st.container(border=True):
        title_col, score_col = st.columns([5, 1.2])
        with title_col:
            st.markdown(f"### {str(row.get('title') or 'Untitled Book')}")
            st.caption(f"by {str(row.get('author') or 'Unknown author')}")
        with score_col:
            st.metric("Match", f"{float(row.get('recommendation_score', 0)):.1f}")

        st.markdown(
            f"""
            <div class="badge-row">
                {_badge_html(length_type, "orange")}
                {_badge_html(reading_level, "green")}
                {_badge_html(genre_text.title(), "blue")}
            </div>
            """,
            unsafe_allow_html=True,
        )

        meta_col1, meta_col2, meta_col3 = st.columns(3)
        with meta_col1:
            st.caption("Location")
            st.write(str(row.get("location") or "Not specified"))
        with meta_col2:
            st.caption("Book Type")
            st.write(item_type)
        with meta_col3:
            st.caption("Pages")
            st.write(str(pages_value if pages_value else "Unknown"))

        st.success(explain_recommendation(row))
        st.write(summary)
        with st.expander("Peek inside this book", expanded=False):
            st.write(f"**Abstract:** {shorten_text(row.get('abstract', ''), max_words=120)}")
            if "abstract is missing" in str(row.get("abstract_status", "")).lower():
                st.warning("This book can still be recommended, but the lesson may be weaker because the abstract is missing.")


def render_book_snapshot(book: dict[str, Any], title: str = "Book details") -> None:
    with st.expander(title, expanded=True):
        st.markdown(
            f"""
            <div class="meta-grid">
                <div class="meta-card"><strong>Author</strong>{escape(str(book.get('author') or 'Unknown'))}</div>
                <div class="meta-card"><strong>Item Type</strong>{escape(str(book.get('item_type') or 'Not specified'))}</div>
                <div class="meta-card"><strong>Pages</strong>{escape(str(safe_int(book.get('pages')) or 'Unknown'))}</div>
                <div class="meta-card"><strong>Location</strong>{escape(str(book.get('location') or 'Not specified'))}</div>
                <div class="meta-card"><strong>Accession No</strong>{escape(str(book.get('accession_no') or 'Not specified'))}</div>
                <div class="meta-card"><strong>Publisher</strong>{escape(str(book.get('publisher') or 'Not specified'))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write(f"**Abstract:** {shorten_text(book.get('abstract', ''), max_words=80)}")


def render_lesson_sections(sections: list[tuple[str, Any]]) -> None:
    for section_title, section_body in sections:
        with st.container(border=True):
            st.markdown(f"### {section_title}")
            if isinstance(section_body, list):
                for item in section_body:
                    st.markdown(f"- {item}")
            else:
                st.write(section_body)
