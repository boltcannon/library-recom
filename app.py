from __future__ import annotations

import pandas as pd
import streamlit as st

from src.chatbot_logic import collect_student_preferences
from src.config import get_database_path
from src.database import (
    create_recommendation_session,
    fetch_all_books,
    fetch_book_by_id,
    fetch_dashboard_metrics,
    fetch_latest_reviewed_lesson,
    init_db,
    log_catalog_upload,
    log_generated_lesson,
    log_selected_book,
    save_feedback,
    save_reviewed_lesson,
)
from src.ingest_catalog import ingest_catalog
from src.lesson_generator import generate_lesson, lesson_sections_to_text, suggest_concepts
from src.recommender import recommend_books
from src.ui_helpers import (
    inject_global_styles,
    render_book_snapshot,
    render_chat_bubble,
    render_hero,
    render_lesson_sections,
    render_recommendation_card,
    render_sidebar_navigation,
    render_status_tip,
)
from src.utils import book_label

DB_PATH = get_database_path()


def setup_page() -> None:
    st.set_page_config(
        page_title="School Library Recommendation Bot",
        page_icon="📚",
        layout="wide",
    )
    inject_global_styles()
    init_db(DB_PATH)
    st.session_state.setdefault("recommended_books", [])
    st.session_state.setdefault("selected_book_id", None)
    st.session_state.setdefault("student_profile", {})
    st.session_state.setdefault("latest_lesson", None)
    st.session_state.setdefault("active_session_id", None)
    st.session_state.setdefault("feedback_saved", False)


def home_page() -> None:
    render_hero(
        "School Library Recommendation and Story-Based Learning Bot",
        "Turn a school library catalog into book suggestions, simple lessons, and teacher-reviewed learning moments.",
        kicker="Welcome",
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("What Students Can Do")
        st.markdown(
            """
            - Answer a few easy reading questions
            - Get real book suggestions from the school library
            - Pick one book and build a lesson from it
            - Share quick feedback after learning
            """
        )
    with col2:
        st.subheader("What Teachers And Admins Can Do")
        st.markdown(
            """
            - Upload a school library Excel catalog
            - Review generated lessons before classroom use
            - Track sessions, selections, and feedback
            - Use the dashboard to see simple project activity
            """
        )

    render_status_tip("Suggested flow", "Start with Admin, move to Student, continue to Story-Based Learning, then use Teacher Review.")


def admin_page() -> None:
    render_hero(
        "Admin: Upload Catalog",
        "Upload the school library Excel file and safely store it in SQLite.",
        kicker="Admin space",
    )
    st.write("The upload flow handles missing columns safely so imperfect catalog exports can still be imported.")

    uploaded_file = st.file_uploader("Upload library catalog (.xlsx)", type=["xlsx"])
    if uploaded_file is None:
        render_status_tip("Upload tip", "Upload your school library Excel file here to begin.")
        return

    if st.button("Import Catalog", type="primary", use_container_width=True):
        try:
            with st.spinner("Importing and enriching catalog data..."):
                result = ingest_catalog(uploaded_file, DB_PATH)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Catalog upload failed: {exc}")
            return

        st.session_state["recommended_books"] = []
        st.session_state["selected_book_id"] = None
        st.session_state["latest_lesson"] = None
        st.session_state["active_session_id"] = None
        st.session_state["feedback_saved"] = False
        log_catalog_upload(DB_PATH, result["imported_count"], result["columns"])

        st.success(f"Catalog uploaded successfully. Imported {result['imported_count']} items.")
        with st.expander("See detected columns and preview", expanded=True):
            st.write("**Detected columns:**", ", ".join(result["columns"]))
            st.dataframe(result["preview"], use_container_width=True, hide_index=True)


def student_page() -> None:
    render_hero(
        "Student: Get Book Recommendation",
        "Chat with the library bot by answering a few questions about what you like to read.",
        kicker="Student journey",
    )
    books_df = fetch_all_books(DB_PATH)
    if books_df.empty:
        st.warning("No books are available yet. Please ask the admin to upload a library catalog first.")
        return

    render_chat_bubble("Hi! I can help you find a book from your school library. Tell me a little about what you enjoy reading.")
    with st.container(border=True):
        st.markdown("### Step 1: Tell the Bot About You")
        with st.form("student_preferences_form"):
            preferences = collect_student_preferences()
            submitted = st.form_submit_button("Find Books", type="primary", use_container_width=True)

    if submitted:
        recommendations = recommend_books(books_df, preferences, top_n=5)
        recommendation_records = recommendations.to_dict(orient="records")
        st.session_state["recommended_books"] = recommendation_records
        st.session_state["student_profile"] = preferences
        st.session_state["active_session_id"] = create_recommendation_session(
            DB_PATH,
            grade=preferences.get("grade", ""),
            preferences=preferences,
            recommended_books=recommendation_records,
        )
        st.session_state["latest_lesson"] = None
        st.session_state["feedback_saved"] = False
        st.session_state["selected_book_id"] = None

        if recommendations.empty:
            st.warning("I could not find a strong match yet. Try broader choices like Any, or leave topics blank.")
        else:
            render_chat_bubble("I found some books that may suit you. Open each card to see why it matched.")

    recommended_books = st.session_state.get("recommended_books", [])
    if not recommended_books:
        render_status_tip("What happens next?", "After you answer the questions, the app will show 3 to 5 book recommendations.")
        return

    st.markdown("### Step 2: Explore Your Book Cards")
    recommendation_df = pd.DataFrame(recommended_books)
    for _, row in recommendation_df.iterrows():
        render_recommendation_card(row)

    options = {book["id"]: book_label(book) for book in recommended_books}
    with st.container(border=True):
        st.markdown("### Step 3: Choose One Book")
        selected_book_id = st.selectbox(
            "Pick a book to continue",
            options=list(options.keys()),
            format_func=lambda value: options[value],
        )
        st.session_state["selected_book_id"] = selected_book_id
        st.success("Next step: open Story-Based Learning to turn this book into a lesson.")


def story_learning_page() -> None:
    render_hero(
        "Story-Based Learning",
        "Use a selected book to build a simple lesson connected to a school subject.",
        kicker="Lesson builder",
    )
    books_df = fetch_all_books(DB_PATH)
    if books_df.empty:
        st.warning("No books are available yet. Please upload a catalog first.")
        return

    recommended_books = [
        book for book in st.session_state.get("recommended_books", [])
        if fetch_book_by_id(DB_PATH, book.get("id"))
    ]
    default_book_id = st.session_state.get("selected_book_id")
    recommended_ids = [book["id"] for book in recommended_books]

    if recommended_ids:
        selectable_ids = recommended_ids
        help_text = "You are using books from the current recommendation session."
    else:
        selectable_ids = books_df["id"].tolist()
        help_text = "No recommendation session is active, so you can choose any book in the catalog."

    render_status_tip("Book source", help_text)

    left_col, right_col = st.columns([1.15, 1])
    with left_col:
        selected_book_id = st.selectbox(
            "Choose a book",
            options=selectable_ids,
            index=selectable_ids.index(default_book_id) if default_book_id in selectable_ids else 0,
            format_func=lambda value: book_label(fetch_book_by_id(DB_PATH, value)),
        )
    st.session_state["selected_book_id"] = selected_book_id

    book = fetch_book_by_id(DB_PATH, selected_book_id)
    if not book:
        st.error("The selected book could not be loaded.")
        return

    with right_col:
        render_book_snapshot(book, "Selected book")

    render_chat_bubble("Nice choice. Now pick a subject and a concept, and I will help build the lesson.")
    with st.container(border=True):
        st.markdown("### Build the Lesson")
        subject = st.selectbox("Which subject do you want to learn?", ["Math", "Science", "English", "Social Science", "Values"])
        concept_suggestions = suggest_concepts(book, subject)
        st.info("Possible concept ideas: " + ", ".join(concept_suggestions))
        quick_pick = st.selectbox(
            "Choose a suggested concept if you want",
            options=["I want to type my own concept"] + concept_suggestions,
        )
        concept = st.text_input("Which concept do you want to learn?", placeholder=concept_suggestions[0])
        selected_concept = concept.strip() or (quick_pick if quick_pick != "I want to type my own concept" else concept_suggestions[0])

    if st.button("Generate Lesson", type="primary", use_container_width=True):
        with st.spinner("Generating lesson..."):
            session_id = st.session_state.get("active_session_id")
            if session_id is None:
                fallback_preferences = st.session_state.get("student_profile", {})
                session_id = create_recommendation_session(
                    DB_PATH,
                    grade=fallback_preferences.get("grade", ""),
                    preferences=fallback_preferences,
                    recommended_books=recommended_books,
                )
                st.session_state["active_session_id"] = session_id

            lesson = generate_lesson(
                book=book,
                subject=subject,
                concept=selected_concept,
                grade=st.session_state.get("student_profile", {}).get("grade", "student"),
            )

        lesson_text = lesson_sections_to_text(lesson["sections"])
        log_selected_book(DB_PATH, session_id, selected_book_id)
        lesson_log_id = log_generated_lesson(
            DB_PATH,
            session_id=session_id,
            book_id=selected_book_id,
            grade=st.session_state.get("student_profile", {}).get("grade", "student"),
            subject=subject,
            concept=lesson.get("chosen_concept", selected_concept),
            generated_lesson=lesson_text,
        )
        st.session_state["latest_lesson"] = {
            "book_id": selected_book_id,
            "subject": subject,
            "concept": lesson.get("chosen_concept", selected_concept),
            "requested_concept": selected_concept,
            "grade": st.session_state.get("student_profile", {}).get("grade", "student"),
            "generated_lesson": lesson_text,
            "warning": lesson["warning"],
            "sections": lesson["sections"],
            "fit_result": lesson.get("fit_result", {}),
            "lesson_log_id": lesson_log_id,
        }
        st.session_state["feedback_saved"] = False
        render_chat_bubble("Your lesson is ready below. You can read it now and then leave quick feedback.")

    latest_lesson = st.session_state.get("latest_lesson")
    if (
        latest_lesson
        and latest_lesson.get("book_id") == selected_book_id
        and latest_lesson.get("subject") == subject
        and latest_lesson.get("requested_concept") == selected_concept
    ):
        st.markdown("### Your Lesson")
        st.write(f"**Lesson concept:** {latest_lesson.get('concept', selected_concept)}")

        if latest_lesson["warning"]:
            st.warning(latest_lesson["warning"])
        elif not latest_lesson.get("fit_result", {}).get("is_strong", True):
            suggested = latest_lesson.get("fit_result", {}).get("suggested_concept", "")
            if suggested:
                st.info(f"A stronger concept may be: {suggested}")

        with st.container(border=True):
            render_lesson_sections(latest_lesson["sections"])

        st.info("Teacher may review this lesson before classroom use.")
        st.markdown("### Quick Feedback")
        if st.session_state.get("feedback_saved"):
            st.success("Feedback saved. Thank you for helping improve the app.")

        with st.container(border=True):
            with st.form("feedback_form"):
                recommendation_useful = st.radio("Was the recommendation useful?", ["Yes", "No"], horizontal=True)
                lesson_understandable = st.radio("Was the lesson understandable?", ["Yes", "No"], horizontal=True)
                rating = st.slider("Overall rating", min_value=1, max_value=5, value=4)
                comment = st.text_input("Optional comment")
                feedback_submitted = st.form_submit_button("Save Feedback", type="primary", use_container_width=True)

        if feedback_submitted:
            save_feedback(
                DB_PATH,
                session_id=st.session_state.get("active_session_id"),
                recommendation_useful=recommendation_useful == "Yes",
                lesson_understandable=lesson_understandable == "Yes",
                rating=rating,
                comment=comment,
            )
            st.session_state["feedback_saved"] = True
            st.rerun()


def dashboard_page() -> None:
    render_hero(
        "Dashboard",
        "See quick project activity, library size, recommendation sessions, popular books, and feedback.",
        kicker="Project view",
    )

    metrics = fetch_dashboard_metrics(DB_PATH)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Uploads", metrics["total_uploads"])
    col2.metric("Total Books", metrics["total_books"])
    col3.metric("Recommendation Sessions", metrics["total_recommendation_sessions"])
    col4.metric(
        "Average Feedback Rating",
        f"{metrics['average_feedback_rating']:.2f}" if metrics["average_feedback_rating"] is not None else "No feedback yet",
    )

    st.markdown("### Most Selected Books")
    most_selected_books = metrics["most_selected_books"]
    if most_selected_books.empty:
        st.info("No book selections have been logged yet.")
    else:
        with st.container(border=True):
            st.dataframe(most_selected_books, use_container_width=True, hide_index=True)


def teacher_review_page() -> None:
    render_hero(
        "Teacher Review",
        "Review the generated lesson, edit the final wording, save it, and export it for classroom use.",
        kicker="Teacher space",
    )

    books_df = fetch_all_books(DB_PATH)
    if books_df.empty:
        st.warning("No books are available yet. Please upload a catalog first.")
        return

    latest_lesson = st.session_state.get("latest_lesson")
    default_book_id = latest_lesson["book_id"] if latest_lesson else int(books_df.iloc[0]["id"])
    selected_book_id = st.selectbox(
        "Select a book for review",
        options=books_df["id"].tolist(),
        index=books_df["id"].tolist().index(default_book_id) if default_book_id in books_df["id"].tolist() else 0,
        format_func=lambda value: book_label(fetch_book_by_id(DB_PATH, value)),
    )
    book = fetch_book_by_id(DB_PATH, selected_book_id)
    if not book:
        st.error("The selected book could not be loaded.")
        return

    lesson_context = latest_lesson if latest_lesson and latest_lesson.get("book_id") == selected_book_id else None
    saved_review = fetch_latest_reviewed_lesson(DB_PATH, selected_book_id)

    if lesson_context is None and saved_review:
        lesson_context = {
            "book_id": selected_book_id,
            "subject": saved_review["subject"],
            "concept": saved_review["concept"],
            "grade": saved_review["grade"],
            "generated_lesson": saved_review["generated_lesson"],
            "warning": "",
            "sections": [],
        }

    if lesson_context is None:
        st.info("Generate a lesson first from Story-Based Learning, then come here to review and save it.")
        return

    st.subheader(book["title"] or "Untitled Book")
    render_book_snapshot(book, "Book details")

    if lesson_context.get("warning"):
        st.warning(lesson_context["warning"])

    subject = lesson_context["subject"]
    concept = lesson_context["concept"]
    grade = lesson_context["grade"]
    generated_lesson = lesson_context["generated_lesson"]

    with st.container(border=True):
        st.markdown("### Generated Lesson")
        st.text_area("Generated lesson text", value=generated_lesson, height=280, disabled=True)

    default_review = saved_review["reviewed_lesson"] if saved_review else generated_lesson
    with st.container(border=True):
        st.markdown("### Teacher Edited Version")
        reviewed_lesson = st.text_area("Edit reviewed lesson", value=default_review, height=320)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Save Reviewed Lesson", type="primary", use_container_width=True):
            save_reviewed_lesson(
                DB_PATH,
                book_id=selected_book_id,
                subject=subject,
                concept=concept,
                grade=grade,
                generated_lesson=generated_lesson,
                reviewed_lesson=reviewed_lesson,
            )
            st.success("Reviewed lesson saved to the database.")
    with col2:
        filename = f"reviewed_lesson_book_{selected_book_id}.txt"
        st.download_button(
            "Download Reviewed Lesson",
            data=reviewed_lesson,
            file_name=filename,
            mime="text/plain",
            use_container_width=True,
        )


def main() -> None:
    setup_page()
    page = render_sidebar_navigation()

    if page == "Home":
        home_page()
    elif page == "Admin: Upload Catalog":
        admin_page()
    elif page == "Student: Get Book Recommendation":
        student_page()
    elif page == "Story-Based Learning":
        story_learning_page()
    elif page == "Dashboard":
        dashboard_page()
    elif page == "Teacher Review":
        teacher_review_page()


if __name__ == "__main__":
    main()
