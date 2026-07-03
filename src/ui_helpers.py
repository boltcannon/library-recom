from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.chatbot_logic import explain_recommendation
from src.utils import safe_int, shorten_text


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
        .main .block-container {
            padding-top: 1.6rem;
            padding-bottom: 2.5rem;
            max-width: 1100px;
        }
        .app-hero {
            padding: 1.25rem 1.4rem;
            border-radius: 18px;
            background: linear-gradient(135deg, #f8fbff 0%, #eef6f0 100%);
            border: 1px solid #d7e7da;
            margin-bottom: 1rem;
        }
        .app-kicker {
            color: #2f6f4f;
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
        }
        .chat-bubble {
            padding: 0.85rem 1rem;
            border-radius: 16px;
            margin: 0.45rem 0;
            border: 1px solid #e4e7eb;
        }
        .chat-bubble.bot {
            background: #f8fafc;
            border-left: 4px solid #2f6f4f;
        }
        .chat-bubble.user {
            background: #fffdf5;
            border-left: 4px solid #d48a00;
        }
        .soft-card {
            padding: 0.9rem 1rem;
            border-radius: 16px;
            background: #fbfcfd;
            border: 1px solid #e8edf2;
            margin-bottom: 0.8rem;
        }
        .mini-label {
            color: #536471;
            font-size: 0.85rem;
            font-weight: 600;
            margin-bottom: 0.15rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(title: str, body: str, kicker: str = "School Library MVP") -> None:
    st.markdown(
        f"""
        <div class="app-hero">
            <div class="app-kicker">{kicker}</div>
            <h1 style="margin:0 0 0.35rem 0;">{title}</h1>
            <p style="margin:0;color:#344054;">{body}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_chat_bubble(text: str, speaker: str = "bot") -> None:
    bubble_class = "bot" if speaker == "bot" else "user"
    st.markdown(f'<div class="chat-bubble {bubble_class}">{text}</div>', unsafe_allow_html=True)


def render_status_tip(title: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="soft-card">
            <div class="mini-label">{title}</div>
            <div>{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_navigation(active_role: str) -> str:
    st.sidebar.title("Library Guide")
    st.sidebar.caption("Move step by step through the parts of the app that match your role.")
    selected_role = st.sidebar.radio(
        "Choose your role",
        ["Student", "Teacher", "Admin"],
        key="active_role",
        horizontal=False,
    )
    page_options = {
        "Student": [
            "Home",
            "Student Dashboard",
            "Find Books",
            "Story-Based Learning",
        ],
        "Teacher": [
            "Home",
            "Teacher Review",
            "Dashboard",
        ],
        "Admin": [
            "Home",
            "Admin: Upload Catalog",
            "Dashboard",
        ],
    }
    page = st.sidebar.radio(
        "Open a page",
        page_options.get(selected_role, page_options["Student"]),
    )
    st.sidebar.markdown("---")
    flow_text = {
        "Student": "1. Set your profile\n2. Find books\n3. Build a lesson\n4. Take a quiz",
        "Teacher": "1. Open a lesson\n2. Review content\n3. Save and export",
        "Admin": "1. Upload a catalog\n2. Check activity\n3. Support teachers and students",
    }
    st.sidebar.markdown(f"**Suggested flow**\n\n{flow_text.get(selected_role, flow_text['Student'])}")
    return page


def render_recommendation_card(row: pd.Series) -> None:
    with st.container(border=True):
        top_left, top_right = st.columns([4, 1])
        top_left.markdown(f"### {row['title'] or 'Untitled Book'}")
        top_right.metric("Score", f"{float(row.get('recommendation_score', 0)):.2f}")

        meta1, meta2, meta3 = st.columns(3)
        meta1.write(f"**Author:** {row['author'] or 'Unknown'}")
        meta2.write(f"**Location:** {row['location'] or 'Not specified'}")
        meta3.write(f"**Type:** {row['item_type'] or 'Not specified'}")

        st.write(f"**Short summary:** {shorten_text(row.get('abstract', ''), max_words=60)}")
        st.success(explain_recommendation(row))
        if "abstract is missing" in str(row.get("abstract_status", "")).lower():
            st.warning("This book can still be recommended, but the lesson may be weaker because the abstract is missing.")


def render_book_snapshot(book: dict[str, Any], title: str = "Book details") -> None:
    with st.expander(title, expanded=True):
        col1, col2 = st.columns(2)
        col1.write(f"**Author:** {book.get('author') or 'Unknown'}")
        col1.write(f"**Item Type:** {book.get('item_type') or 'Not specified'}")
        col1.write(f"**Pages:** {safe_int(book.get('pages')) or 'Unknown'}")
        col2.write(f"**Location:** {book.get('location') or 'Not specified'}")
        col2.write(f"**Accession No:** {book.get('accession_no') or 'Not specified'}")
        col2.write(f"**Publisher:** {book.get('publisher') or 'Not specified'}")
        st.write(f"**Abstract:** {shorten_text(book.get('abstract', ''), max_words=80)}")


def render_lesson_sections(sections: list[tuple[str, Any]]) -> None:
    for section_title, section_body in sections:
        st.markdown(f"### {section_title}")
        if isinstance(section_body, list):
            for item in section_body:
                st.markdown(f"- {item}")
        else:
            st.write(section_body)
