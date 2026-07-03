from __future__ import annotations

import streamlit as st


def collect_student_preferences() -> dict[str, str]:
    grade = st.selectbox("Which class/grade are you in?", ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"])
    book_type = st.radio("What type of book do you want?", ["Story", "Knowledge", "Any"], horizontal=True)
    topics = st.text_input(
        "What topics do you like?",
        placeholder="animals, science, mystery, friendship, sports, space, nature, history",
    )
    length = st.selectbox("Do you want a short, medium, or long book?", ["short", "medium", "long", "any"])
    reading_level = st.selectbox("Do you want easy, medium, or challenging reading?", ["easy", "medium", "challenging", "any"])

    return {
        "grade": grade,
        "book_type": book_type.lower(),
        "topics": topics,
        "length_type": length.lower(),
        "reading_level": reading_level.lower(),
    }


def explain_recommendation(book: dict) -> str:
    title = book.get("title") or "This book"
    reason = str(book.get("recommendation_reason", "")).strip()
    if reason:
        return reason
    return f"{title} was recommended because it matches your overall reading preferences."
