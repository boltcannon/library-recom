from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.auth import ALLOWED_ROLES, is_valid_email, validate_password_rules
from src.chatbot_logic import collect_student_preferences
from src.config import get_database_config
from src.database import (
    authenticate_user,
    create_user,
    create_recommendation_session,
    ensure_admin_account,
    fetch_all_users,
    fetch_all_books,
    fetch_book_by_id,
    fetch_dashboard_metrics,
    fetch_latest_reviewed_lesson,
    fetch_saved_book_statuses_for_user,
    fetch_student_dashboard_data_for_user,
    fetch_student_profile_for_user,
    fetch_user_by_email,
    fetch_user_by_id,
    init_db,
    log_catalog_upload,
    log_generated_lesson,
    log_selected_book,
    save_quiz_result,
    save_reviewed_lesson,
    save_student_profile_for_user,
    save_user_feedback,
    update_user_active_status,
    update_user_role,
    update_saved_book_status_for_user,
)
from src.ingest_catalog import ingest_catalog
from src.lesson_generator import (
    generate_lesson,
    generate_quiz_questions,
    grade_quiz_answers,
    lesson_sections_to_text,
    suggest_concepts,
)
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

DB_CONFIG = get_database_config()
LANGUAGE_OPTIONS = ["English", "Hindi", "Bilingual", "Other"]
READING_LEVEL_OPTIONS = ["easy", "medium", "challenging"]


@st.cache_data(show_spinner=False)
def get_recommendations_cached(
    books_df: pd.DataFrame,
    preference_items: tuple[tuple[str, str], ...],
    top_n: int = 5,
) -> pd.DataFrame:
    return recommend_books(books_df, dict(preference_items), top_n=top_n)


def setup_page() -> None:
    st.set_page_config(
        page_title="School Library Recommendation Bot",
        page_icon="📚",
        layout="wide",
    )
    inject_global_styles()
    init_db(DB_CONFIG)
    admin_email = os.getenv("FIRST_ADMIN_EMAIL", "").strip()
    admin_password = os.getenv("FIRST_ADMIN_PASSWORD", "").strip()
    admin_name = os.getenv("FIRST_ADMIN_NAME", "").strip() or "Admin"
    if admin_email and admin_password:
        ensure_admin_account(DB_CONFIG, full_name=admin_name, email=admin_email, password=admin_password)

    st.session_state.setdefault("auth_user", None)
    st.session_state.setdefault("recommended_books", [])
    st.session_state.setdefault("selected_book_id", None)
    st.session_state.setdefault("student_profile", {})
    st.session_state.setdefault("latest_lesson", None)
    st.session_state.setdefault("active_session_id", None)
    st.session_state.setdefault("feedback_saved", False)
    st.session_state.setdefault("last_quiz_result", None)
    st.session_state.setdefault("quiz_saved", False)
    st.session_state.setdefault("student_profile_record", None)
    st.session_state.setdefault("last_recommendation_signature", None)
    st.session_state.setdefault("auth_view", "login")
    st.session_state.setdefault("nav_page", "Home")


def reset_student_learning_state() -> None:
    st.session_state["recommended_books"] = []
    st.session_state["selected_book_id"] = None
    st.session_state["latest_lesson"] = None
    st.session_state["active_session_id"] = None
    st.session_state["feedback_saved"] = False
    st.session_state["last_quiz_result"] = None
    st.session_state["quiz_saved"] = False
    st.session_state["last_recommendation_signature"] = None


def build_book_lookup(books_df: pd.DataFrame) -> dict[int, dict]:
    if books_df.empty:
        return {}
    return {
        int(row["id"]): row.to_dict()
        for _, row in books_df.iterrows()
    }


def get_current_user() -> dict | None:
    auth_user = st.session_state.get("auth_user")
    if not auth_user or not auth_user.get("id"):
        return None
    fresh_user = fetch_user_by_id(DB_CONFIG, int(auth_user["id"]))
    if fresh_user:
        st.session_state["auth_user"] = fresh_user
    return fresh_user or auth_user


def is_authenticated() -> bool:
    return get_current_user() is not None


def default_page_for_role(role: str) -> str:
    role = role.lower()
    if role == "teacher":
        return "Teacher Dashboard"
    if role == "admin":
        return "Admin Dashboard"
    return "Student Dashboard"


def logout_user() -> None:
    auth_view = st.session_state.get("auth_view", "login")
    st.session_state.clear()
    setup_page()
    st.session_state["auth_user"] = None
    st.session_state["auth_view"] = auth_view
    st.session_state["nav_page"] = "Home"


def enforce_role(required_roles: set[str]) -> dict | None:
    user = get_current_user()
    if not user:
        st.warning("Please log in to continue.")
        st.session_state["auth_view"] = "login"
        return None
    role = str(user.get("role", "")).lower()
    if role not in required_roles:
        st.error("You do not have access to this section.")
        st.session_state["nav_page"] = default_page_for_role(role)
        return None
    return user


def render_auth_page() -> None:
    render_hero(
        "Welcome to the School Library App",
        "Log in to continue, or create a student account to start discovering books and lessons.",
        kicker="Authentication",
    )
    selected_view = st.radio(
        "Choose an option",
        ["Login", "Sign Up"],
        horizontal=True,
        index=0 if st.session_state.get("auth_view", "login") == "login" else 1,
    )
    st.session_state["auth_view"] = "login" if selected_view == "Login" else "signup"

    if selected_view == "Login":
        with st.container(border=True):
            st.markdown("### Login")
            with st.form("login_form"):
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Log In", type="primary", use_container_width=True)
            if submitted:
                user = authenticate_user(DB_CONFIG, email=email, password=password)
                if not user:
                    st.error("Invalid email or password.")
                else:
                    st.session_state["auth_user"] = user
                    st.session_state["nav_page"] = default_page_for_role(str(user.get("role", "student")))
                    reset_student_learning_state()
                    st.rerun()
    else:
        with st.container(border=True):
            st.markdown("### Sign Up")
            with st.form("signup_form"):
                full_name = st.text_input("Full name")
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                confirm_password = st.text_input("Confirm password", type="password")
                submitted = st.form_submit_button("Create Student Account", type="primary", use_container_width=True)
            if submitted:
                if not full_name.strip():
                    st.error("Please enter your full name.")
                elif not is_valid_email(email):
                    st.error("Please enter a valid email address.")
                elif fetch_user_by_email(DB_CONFIG, email):
                    st.error("An account with this email already exists.")
                else:
                    password_error = validate_password_rules(password)
                    if password_error:
                        st.error(password_error)
                    elif password != confirm_password:
                        st.error("Passwords do not match.")
                    else:
                        user_id = create_user(DB_CONFIG, full_name=full_name, email=email, password=password, role="student")
                        st.session_state["auth_user"] = fetch_user_by_id(DB_CONFIG, user_id)
                        st.session_state["nav_page"] = default_page_for_role("student")
                        reset_student_learning_state()
                        st.success("Your student account is ready.")
                        st.rerun()


def get_cached_student_profile() -> dict | None:
    user = get_current_user()
    cached_profile = st.session_state.get("student_profile_record")
    if user and cached_profile and int(cached_profile.get("user_id", -1)) == int(user["id"]):
        return cached_profile
    return None


def require_student_profile() -> dict | None:
    user = enforce_role({"student"})
    if not user:
        return None
    cached_profile = get_cached_student_profile()
    if cached_profile:
        return {**cached_profile, "id": int(user["id"]), "full_name": user.get("full_name", "")}
    profile = fetch_student_profile_for_user(DB_CONFIG, int(user["id"]))
    if not profile:
        st.info("Please complete your student profile first from the Student Dashboard.")
        return None
    st.session_state["student_profile_record"] = profile
    st.session_state["student_profile"] = {
        "name": user.get("full_name", ""),
        "grade": profile["class_grade"],
        "preferred_language": profile.get("preferred_language", ""),
        "favorite_topics": profile.get("favorite_topics", ""),
        "reading_level": profile.get("reading_level", ""),
    }
    return {**profile, "id": int(user["id"]), "full_name": user.get("full_name", "")}


def render_student_profile_manager() -> None:
    user = enforce_role({"student"})
    if not user:
        return
    profile = fetch_student_profile_for_user(DB_CONFIG, int(user["id"]))
    current_profile = {
        "name": user.get("full_name", ""),
        "grade": profile.get("class_grade", "4") if profile else "4",
        "preferred_language": profile.get("preferred_language", "English") if profile else "English",
        "favorite_topics": profile.get("favorite_topics", "") if profile else "",
        "reading_level": profile.get("reading_level", "easy") if profile else "easy",
    }

    with st.container(border=True):
        st.markdown("### Student Profile")
        with st.form("student_profile_form"):
            name = st.text_input("Student name", value=current_profile.get("name", ""))
            grade = st.selectbox(
                "Class / grade",
                [str(level) for level in range(1, 13)],
                index=max(0, [str(level) for level in range(1, 13)].index(str(current_profile.get("grade", "4"))) if str(current_profile.get("grade", "4")) in [str(level) for level in range(1, 13)] else 3),
            )
            preferred_language = st.selectbox(
                "Preferred language",
                LANGUAGE_OPTIONS,
                index=LANGUAGE_OPTIONS.index(current_profile.get("preferred_language", "English")) if current_profile.get("preferred_language", "English") in LANGUAGE_OPTIONS else 0,
            )
            favorite_topics = st.text_input(
                "Favorite topics",
                value=current_profile.get("favorite_topics", ""),
                placeholder="animals, science, friendship, space",
            )
            reading_level = st.selectbox(
                "Reading comfort level",
                READING_LEVEL_OPTIONS,
                index=READING_LEVEL_OPTIONS.index(current_profile.get("reading_level", "easy")) if current_profile.get("reading_level", "easy") in READING_LEVEL_OPTIONS else 0,
            )
            saved = st.form_submit_button("Save Student Profile", type="primary", use_container_width=True)

        if saved:
            if not name.strip():
                st.error("Please enter the student's name.")
            else:
                save_student_profile_for_user(
                    DB_CONFIG,
                    user_id=int(user["id"]),
                    full_name=name,
                    class_grade=grade,
                    preferred_language=preferred_language,
                    favorite_topics=favorite_topics,
                    reading_level=reading_level,
                )
                st.session_state["auth_user"] = {**user, "full_name": name.strip()}
                st.session_state["student_profile_record"] = {
                    "user_id": int(user["id"]),
                    "class_grade": grade,
                    "preferred_language": preferred_language,
                    "favorite_topics": favorite_topics.strip(),
                    "reading_level": reading_level,
                }
                st.session_state["student_profile"] = {
                    "name": name.strip(),
                    "grade": grade,
                    "preferred_language": preferred_language,
                    "favorite_topics": favorite_topics.strip(),
                    "reading_level": reading_level,
                }
                reset_student_learning_state()
                st.success("Student profile saved.")


def home_page() -> None:
    render_hero(
        "School Library Recommendation and Story-Based Learning Bot",
        "A child-friendly library product where students discover books, save their reading journey, learn through stories, and teachers review lessons.",
        kicker="Welcome",
    )

    user = get_current_user()
    role = str(user.get("role", "student")).lower() if user else "student"
    role_text = {
        "student": "Complete your profile, find books, save favorites, read lessons, and take quizzes.",
        "teacher": "Review lessons, improve classroom wording, and save teacher-ready versions.",
        "admin": "Upload the catalog and monitor the activity dashboard.",
    }
    render_status_tip("Current role", role_text.get(role, role_text["student"]))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Student Experience")
        st.markdown(
            """
            - Build a saved student profile
            - Get personalized book recommendations
            - Save books for later or mark them as read
            - Track learning history and quiz progress
            """
        )
    with col2:
        st.subheader("School Team Experience")
        st.markdown(
            """
            - Upload library data safely
            - Review generated lessons
            - See dashboard activity
            - Keep the product simple and teacher-friendly
            """
        )


def admin_page() -> None:
    if not enforce_role({"admin"}):
        return
    render_hero(
        "Admin: Upload Catalog",
        "Upload the school library Excel file and safely store it in the app database.",
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
                result = ingest_catalog(uploaded_file, DB_CONFIG)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Catalog upload failed: {exc}")
            return

        reset_student_learning_state()
        log_catalog_upload(DB_CONFIG, result["imported_count"], result["columns"])

        st.success(f"Catalog uploaded successfully. Imported {result['imported_count']} items.")
        with st.expander("See detected columns and preview", expanded=True):
            st.write("**Detected columns:**", ", ".join(result["columns"]))
            st.dataframe(result["preview"], use_container_width=True, hide_index=True)


def student_dashboard_page() -> None:
    user = enforce_role({"student"})
    if not user:
        return
    render_hero(
        "Student Dashboard",
        "Manage the student profile, see reading progress, and look back at saved books, lessons, and activity.",
        kicker="Student dashboard",
    )
    render_student_profile_manager()
    profile = require_student_profile()
    if not profile:
        return

    dashboard = fetch_student_dashboard_data_for_user(DB_CONFIG, int(user["id"]))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Books explored", dashboard["total_books_explored"])
    c2.metric("Saved books", dashboard["total_books_saved"])
    c3.metric("Books read", dashboard["total_books_marked_as_read"])
    c4.metric("Lessons generated", dashboard["total_lessons_generated"])

    render_status_tip("Favorite topics", dashboard["favorite_topics"] or "No favorite topics saved yet.")

    st.markdown("### Recent Activity")
    if dashboard["recent_activity"].empty:
        st.info("No recent activity yet. Start by getting book recommendations.")
    else:
        st.dataframe(dashboard["recent_activity"], use_container_width=True, hide_index=True)

    history_tabs = st.tabs(["Reading History", "Recommended Books", "Selected Books", "Generated Lessons"])
    history_frames = [
        dashboard["reading_history"],
        dashboard["recommended_history"],
        dashboard["selected_history"],
        dashboard["lesson_history"],
    ]
    empty_messages = [
        "No saved or read books yet.",
        "No recommendation history yet.",
        "No selected books yet.",
        "No lessons generated yet.",
    ]
    for tab, frame, message in zip(history_tabs, history_frames, empty_messages):
        with tab:
            if frame.empty:
                st.info(message)
            else:
                st.dataframe(frame, use_container_width=True, hide_index=True)


def student_page() -> None:
    user = enforce_role({"student"})
    if not user:
        return
    render_hero(
        "Find Books",
        "Chat with the library bot by answering a few questions about what you like to read.",
        kicker="Student journey",
    )
    books_df = fetch_all_books(DB_CONFIG)
    book_lookup = build_book_lookup(books_df)
    if books_df.empty:
        st.warning("No books are available yet. Please ask the admin to upload a library catalog first.")
        return

    profile = require_student_profile()
    if not profile:
        return

    render_chat_bubble(
        f"Hi {profile['full_name']}! I can help you find a book from your school library. Let's use your profile and a few reading preferences."
    )
    with st.container(border=True):
        st.markdown("### Step 1: Tell the Bot What You Want Today")
        with st.form("student_preferences_form"):
            if profile.get("preferred_language"):
                st.caption(f"Preferred language: {profile['preferred_language']}")
            preferences = collect_student_preferences(
                include_grade=False,
                default_grade=profile["class_grade"],
                default_topics=profile.get("favorite_topics", ""),
                default_reading_level=profile.get("reading_level", "easy") or "easy",
            )
            preferences["grade"] = profile["class_grade"]
            submitted = st.form_submit_button("Find Books", type="primary", use_container_width=True)

    if submitted:
        recommendation_signature = (
            int(user["id"]),
            tuple(sorted((str(key), str(value)) for key, value in preferences.items())),
        )
        if (
            st.session_state.get("last_recommendation_signature") == recommendation_signature
            and st.session_state.get("recommended_books")
        ):
            recommendation_records = st.session_state["recommended_books"]
        else:
            recommendations = get_recommendations_cached(
                books_df,
                tuple(sorted((str(key), str(value)) for key, value in preferences.items())),
                top_n=5,
            )
            recommendation_records = recommendations.to_dict(orient="records")
            st.session_state["recommended_books"] = recommendation_records
            st.session_state["last_recommendation_signature"] = recommendation_signature
            st.session_state["active_session_id"] = create_recommendation_session(
                DB_CONFIG,
                student_id=int(user["id"]),
                grade=preferences.get("grade", ""),
                preferences=preferences,
                recommended_books=recommendation_records,
            )
        st.session_state["student_profile"] = {
            "name": profile["full_name"],
            "grade": profile["class_grade"],
            "preferred_language": profile.get("preferred_language", ""),
            "favorite_topics": profile.get("favorite_topics", ""),
            "reading_level": profile.get("reading_level", ""),
        }
        st.session_state["latest_lesson"] = None
        st.session_state["feedback_saved"] = False
        st.session_state["selected_book_id"] = None
        st.session_state["last_quiz_result"] = None
        st.session_state["quiz_saved"] = False

        if not recommendation_records:
            st.warning("I could not find a strong match yet. Try broader choices like Any, or leave topics blank.")
        else:
            render_chat_bubble("I found some books that may suit you. You can save them, mark them as read later, or continue to a lesson.")

    recommended_books = st.session_state.get("recommended_books", [])
    if not recommended_books:
        render_status_tip("What happens next?", "After you answer the questions, the app will show 3 to 5 book recommendations.")
        return

    student_book_statuses = fetch_saved_book_statuses_for_user(DB_CONFIG, int(user["id"]))
    st.markdown("### Step 2: Explore Your Book Cards")
    recommendation_df = pd.DataFrame(recommended_books)
    for _, row in recommendation_df.iterrows():
        book_id = int(row["id"])
        render_recommendation_card(row)
        status = student_book_statuses.get(book_id, {})
        col1, col2 = st.columns(2)
        saved_label = "Saved for later" if status.get("saved_for_later") else "Save for later"
        read_label = "Marked as read" if status.get("marked_as_read") else "Mark as read"
        with col1:
            if st.button(saved_label, key=f"save_book_{book_id}", use_container_width=True):
                update_saved_book_status_for_user(
                    DB_CONFIG,
                    int(user["id"]),
                    book_id,
                    saved_for_later=not bool(status.get("saved_for_later")),
                    marked_as_read=bool(status.get("marked_as_read")),
                )
                st.rerun()
        with col2:
            if st.button(read_label, key=f"read_book_{book_id}", use_container_width=True):
                update_saved_book_status_for_user(
                    DB_CONFIG,
                    int(user["id"]),
                    book_id,
                    saved_for_later=bool(status.get("saved_for_later")),
                    marked_as_read=not bool(status.get("marked_as_read")),
                )
                st.rerun()

    options = {book["id"]: book_label(book) for book in recommended_books}
    with st.container(border=True):
        st.markdown("### Step 3: Choose One Book")
        selected_book_id = st.selectbox(
            "Pick a book to continue",
            options=list(options.keys()),
            format_func=lambda value: options[value],
        )
        st.session_state["selected_book_id"] = selected_book_id
        st.success("Next step: open Story-Based Learning to turn this book into a lesson and quiz.")


def story_learning_page() -> None:
    user = enforce_role({"student"})
    if not user:
        return
    render_hero(
        "Story-Based Learning",
        "Use a selected book to build a simple lesson connected to a school subject, then try a short quiz.",
        kicker="Lesson builder",
    )
    books_df = fetch_all_books(DB_CONFIG)
    book_lookup = build_book_lookup(books_df)
    if books_df.empty:
        st.warning("No books are available yet. Please upload a catalog first.")
        return

    profile = require_student_profile()
    if not profile:
        return

    recommended_books = [
        book for book in st.session_state.get("recommended_books", [])
        if int(book.get("id", -1)) in book_lookup
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
            format_func=lambda value: book_label(book_lookup.get(value, {})),
        )
    st.session_state["selected_book_id"] = selected_book_id

    book = book_lookup.get(selected_book_id) or fetch_book_by_id(DB_CONFIG, selected_book_id)
    if not book:
        st.error("The selected book could not be loaded.")
        return

    with right_col:
        render_book_snapshot(book, "Selected book")

    render_chat_bubble(f"Nice choice, {profile['full_name']}. Pick a subject and concept, and then try the quiz after the lesson.")
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
                    DB_CONFIG,
                    student_id=int(user["id"]),
                    grade=fallback_preferences.get("grade", profile["class_grade"]),
                    preferences=fallback_preferences,
                    recommended_books=recommended_books,
                )
                st.session_state["active_session_id"] = session_id

            lesson = generate_lesson(
                book=book,
                subject=subject,
                concept=selected_concept,
                grade=profile["class_grade"],
            )

        lesson_text = lesson_sections_to_text(lesson["sections"])
        log_selected_book(DB_CONFIG, session_id, selected_book_id, student_id=int(user["id"]))
        lesson_log_id = log_generated_lesson(
            DB_CONFIG,
            student_id=int(user["id"]),
            session_id=session_id,
            book_id=selected_book_id,
            grade=profile["class_grade"],
            subject=subject,
            concept=lesson.get("chosen_concept", selected_concept),
            generated_lesson=lesson_text,
        )
        quiz_questions = generate_quiz_questions(book, lesson.get("chosen_concept", selected_concept), profile["class_grade"])
        st.session_state["latest_lesson"] = {
            "book_id": selected_book_id,
            "subject": subject,
            "concept": lesson.get("chosen_concept", selected_concept),
            "requested_concept": selected_concept,
            "grade": profile["class_grade"],
            "generated_lesson": lesson_text,
            "warning": lesson["warning"],
            "sections": lesson["sections"],
            "fit_result": lesson.get("fit_result", {}),
            "lesson_log_id": lesson_log_id,
            "quiz_questions": quiz_questions,
        }
        st.session_state["feedback_saved"] = False
        st.session_state["last_quiz_result"] = None
        st.session_state["quiz_saved"] = False
        render_chat_bubble("Your lesson is ready below. When you finish reading, try the quick quiz.")

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

        quiz_questions = latest_lesson.get("quiz_questions", [])
        if quiz_questions:
            st.markdown("### Quiz Mode")
            with st.container(border=True):
                with st.form("lesson_quiz_form"):
                    quiz_answers = []
                    for index, question in enumerate(quiz_questions, start=1):
                        quiz_answers.append(
                            st.radio(
                                f"{index}. {question['question']}",
                                question["options"],
                                key=f"quiz_q_{latest_lesson['lesson_log_id']}_{index}",
                            )
                        )
                    quiz_submitted = st.form_submit_button("Check Quiz", type="primary", use_container_width=True)

            if quiz_submitted:
                quiz_result = grade_quiz_answers(quiz_questions, quiz_answers)
                st.session_state["last_quiz_result"] = quiz_result
                if not st.session_state.get("quiz_saved"):
                    save_quiz_result(
                        DB_CONFIG,
                        student_id=int(user["id"]),
                        book_id=selected_book_id,
                        lesson_log_id=latest_lesson.get("lesson_log_id"),
                        score=quiz_result["score"],
                        total_questions=quiz_result["total_questions"],
                        answers=quiz_result["results"],
                    )
                    st.session_state["quiz_saved"] = True

            if st.session_state.get("last_quiz_result"):
                result = st.session_state["last_quiz_result"]
                st.success(f"Quiz score: {result['score']} / {result['total_questions']}")
                st.write(result["summary"])
                for item in result["results"]:
                    icon = "Correct" if item["is_correct"] else "Try again"
                    with st.expander(f"{icon}: {item['question']}", expanded=not item["is_correct"]):
                        st.write(f"**Your answer:** {item['selected_answer']}")
                        st.write(f"**Correct answer:** {item['correct_answer']}")
                        st.write(item["feedback"])

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
            save_user_feedback(
                DB_CONFIG,
                user_id=int(user["id"]),
                lesson_id=latest_lesson.get("lesson_log_id"),
                recommendation_useful=recommendation_useful == "Yes",
                lesson_understandable=lesson_understandable == "Yes",
                rating=rating,
                comment=comment,
            )
            st.session_state["feedback_saved"] = True
            st.rerun()


def teacher_dashboard_page() -> None:
    if not enforce_role({"teacher"}):
        return
    render_hero(
        "Teacher Dashboard",
        "See quick activity, library size, recommendation sessions, popular books, and feedback.",
        kicker="Teacher space",
    )

    metrics = fetch_dashboard_metrics(DB_CONFIG)
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


def admin_dashboard_page() -> None:
    if not enforce_role({"admin"}):
        return
    render_hero(
        "Admin Dashboard",
        "See library activity, recommendation sessions, catalog status, and feedback trends.",
        kicker="Admin space",
    )

    metrics = fetch_dashboard_metrics(DB_CONFIG)
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


def admin_user_management_page() -> None:
    current_admin = enforce_role({"admin"})
    if not current_admin:
        return

    render_hero(
        "Admin: User Management",
        "Create teacher accounts, review users, change roles, and control whether accounts can log in.",
        kicker="Admin space",
    )

    with st.container(border=True):
        st.markdown("### Create Staff Account")
        with st.form("create_staff_form"):
            full_name = st.text_input("Full name")
            email = st.text_input("Email")
            password = st.text_input("Temporary password", type="password")
            role = st.selectbox("Role", ["teacher", "admin"], index=0)
            create_submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)

        if create_submitted:
            if not full_name.strip():
                st.error("Please enter the full name.")
            elif not is_valid_email(email):
                st.error("Please enter a valid email address.")
            elif fetch_user_by_email(DB_CONFIG, email):
                st.error("An account with this email already exists.")
            else:
                password_error = validate_password_rules(password)
                if password_error:
                    st.error(password_error)
                else:
                    create_user(DB_CONFIG, full_name=full_name, email=email, password=password, role=role)
                    st.success(f"{role.title()} account created successfully.")
                    st.rerun()

    users_df = fetch_all_users(DB_CONFIG)
    st.markdown("### All Users")
    if users_df.empty:
        st.info("No users found yet.")
        return

    display_df = users_df.copy()
    display_df["is_active"] = display_df["is_active"].apply(lambda value: "Active" if bool(value) else "Inactive")
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.markdown("### Manage Existing Users")
    for _, row in users_df.iterrows():
        user_id = int(row["id"])
        is_self = user_id == int(current_admin["id"])
        role_value = str(row["role"])
        is_active = bool(row["is_active"])
        with st.expander(f"{row['full_name']} · {row['email']} · {role_value.title()}", expanded=False):
            st.write(f"**User ID:** {user_id}")
            st.write(f"**Created at:** {row['created_at']}")
            if is_self:
                st.warning("This is your current admin account. Self-demotion and self-deactivation are blocked.")

            with st.form(f"user_manage_{user_id}"):
                new_role = st.selectbox(
                    "Role",
                    ["student", "teacher", "admin"],
                    index=["student", "teacher", "admin"].index(role_value if role_value in {"student", "teacher", "admin"} else "student"),
                    key=f"role_select_{user_id}",
                )
                new_active = st.checkbox("Account is active", value=is_active, key=f"active_toggle_{user_id}")
                confirm_change = st.checkbox("I understand this will change this user's access", key=f"confirm_change_{user_id}")
                save_changes = st.form_submit_button("Save Changes", use_container_width=True)

            if save_changes:
                if not confirm_change:
                    st.error("Please confirm the change before saving.")
                elif is_self and new_role != "admin":
                    st.error("You cannot demote your own admin account.")
                elif is_self and not new_active:
                    st.error("You cannot deactivate your own admin account.")
                else:
                    changed_anything = False
                    if new_role != role_value:
                        update_user_role(DB_CONFIG, user_id, new_role)
                        changed_anything = True
                    if new_active != is_active:
                        update_user_active_status(DB_CONFIG, user_id, new_active)
                        changed_anything = True
                    if changed_anything:
                        st.success("User account updated.")
                        st.rerun()
                    else:
                        st.info("No changes were made.")


def teacher_review_page() -> None:
    if not enforce_role({"teacher"}):
        return
    render_hero(
        "Teacher Review",
        "Review the generated lesson, edit the final wording, save it, and export it for classroom use.",
        kicker="Teacher space",
    )

    books_df = fetch_all_books(DB_CONFIG)
    book_lookup = build_book_lookup(books_df)
    if books_df.empty:
        st.warning("No books are available yet. Please upload a catalog first.")
        return

    latest_lesson = st.session_state.get("latest_lesson")
    default_book_id = latest_lesson["book_id"] if latest_lesson else int(books_df.iloc[0]["id"])
    selected_book_id = st.selectbox(
        "Select a book for review",
        options=books_df["id"].tolist(),
        index=books_df["id"].tolist().index(default_book_id) if default_book_id in books_df["id"].tolist() else 0,
        format_func=lambda value: book_label(book_lookup.get(value, {})),
    )
    book = book_lookup.get(selected_book_id) or fetch_book_by_id(DB_CONFIG, selected_book_id)
    if not book:
        st.error("The selected book could not be loaded.")
        return

    lesson_context = latest_lesson if latest_lesson and latest_lesson.get("book_id") == selected_book_id else None
    saved_review = fetch_latest_reviewed_lesson(DB_CONFIG, selected_book_id)

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
                DB_CONFIG,
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
    if not is_authenticated():
        render_auth_page()
        return

    user = get_current_user()
    if not user:
        render_auth_page()
        return

    role = str(user.get("role", "student")).lower()
    if role not in ALLOWED_ROLES:
        st.error("This account has an invalid role configuration.")
        logout_user()
        st.rerun()
        return
    if not bool(user.get("is_active", True)):
        st.error("This account is inactive. Please contact an administrator.")
        logout_user()
        st.rerun()
        return

    page = render_sidebar_navigation(role, str(user.get("full_name", "User")))
    if st.sidebar.button("Log Out", use_container_width=True):
        logout_user()
        st.rerun()
        return

    allowed_pages = {
        "student": {"Home", "Student Dashboard", "Find Books", "Story-Based Learning"},
        "teacher": {"Home", "Teacher Dashboard", "Teacher Review"},
        "admin": {"Home", "Admin Dashboard", "Admin: User Management", "Admin: Upload Catalog"},
    }
    if page not in allowed_pages.get(role, set()):
        st.error("That page is not available for your role.")
        st.session_state["nav_page"] = default_page_for_role(role)
        st.rerun()
        return

    if page == "Home":
        home_page()
    elif page == "Student Dashboard":
        student_dashboard_page()
    elif page == "Find Books":
        student_page()
    elif page == "Admin: Upload Catalog":
        admin_page()
    elif page == "Story-Based Learning":
        story_learning_page()
    elif page == "Teacher Dashboard":
        teacher_dashboard_page()
    elif page == "Admin Dashboard":
        admin_dashboard_page()
    elif page == "Admin: User Management":
        admin_user_management_page()
    elif page == "Teacher Review":
        teacher_review_page()


if __name__ == "__main__":
    main()
