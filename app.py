from __future__ import annotations

import json
import logging
import os
from typing import Any

import pandas as pd
import streamlit as st

from src.auth import ALLOWED_ROLES, is_valid_email, validate_password_rules
from src.config import get_database_config
from src.config import get_recommendation_api_base_url
from src.database import (
    authenticate_user,
    create_lesson_sequence,
    create_user,
    create_recommendation_session,
    ensure_admin_account,
    fetch_admin_user_count,
    fetch_all_users,
    fetch_all_books,
    fetch_book_by_id,
    fetch_dashboard_metrics,
    fetch_latest_lesson_sequence_for_user,
    fetch_latest_reviewed_lesson,
    fetch_saved_book_statuses_for_user,
    fetch_student_dashboard_data_for_user,
    fetch_student_profile_for_user,
    fetch_user_by_email,
    fetch_user_by_id,
    init_auth_db,
    init_db,
    log_catalog_upload,
    log_generated_lesson,
    log_lesson_sequence_attempt,
    log_selected_book,
    save_quiz_result,
    save_reviewed_lesson,
    save_student_profile_for_user,
    save_user_feedback,
    update_lesson_sequence,
    update_user_active_status,
    update_user_role,
    update_saved_book_status_for_user,
)
from src.ingest_catalog import ingest_catalog
from src.lesson_generator import (
    evaluate_activity_feedback,
    evaluate_open_ended_feedback,
    generate_learning_sequence,
    generate_sequence_quiz,
    lesson_sections_to_text,
    score_sequence_quiz,
    suggest_concepts,
)
from src.recommendation_api import (
    RecommendationAPIError,
    create_client_session_id,
    delete_recommendation_session,
    send_recommendation_message,
)
from src.recommender import recommend_books
from src.recommender import normalize_text
from src.ui_helpers import (
    inject_global_styles,
    render_brand_header,
    render_book_snapshot,
    render_chat_bubble,
    render_empty_state,
    render_hero,
    render_lesson_sections,
    render_metric_grid,
    render_progress_steps,
    render_recommendation_card,
    render_resume_banner,
    render_section_heading,
    render_sidebar_navigation,
    render_status_tip,
    render_student_top_navigation,
)
from src.utils import book_label

DB_CONFIG = get_database_config()
RECOMMENDATION_API_BASE_URL = get_recommendation_api_base_url()
LANGUAGE_OPTIONS = ["English", "Hindi", "Bilingual", "Other"]
READING_LEVEL_OPTIONS = ["easy", "medium", "challenging"]
LOGGER = logging.getLogger(__name__)

STUDENT_DISCOVER_PAGE = "Discover Books"
STUDENT_BOOKS_PAGE = "My Books"
STUDENT_LEARN_PAGE = "Learn"
STUDENT_PROGRESS_PAGE = "My Progress"
STUDENT_SIGN_OUT = "Sign Out"

ADMIN_DASHBOARD_PAGE = "Dashboard"
ADMIN_CATALOG_PAGE = "Catalog Upload"
ADMIN_USERS_PAGE = "User Management"
ADMIN_LESSON_REVIEW_PAGE = "Lesson Review"


def normalize_role(role: str) -> str:
    role_value = role.lower().strip()
    return "admin" if role_value == "teacher" else role_value


@st.cache_data(show_spinner=False)
def get_recommendations_cached(
    books_df: pd.DataFrame,
    preference_items: tuple[tuple[str, str], ...],
    top_n: int = 5,
) -> pd.DataFrame:
    return recommend_books(books_df, dict(preference_items), top_n=top_n)


@st.cache_resource(show_spinner=False)
def bootstrap_admin_account_if_configured(config: Any, full_name: str, email: str, password: str) -> bool:
    if not email.strip() or not password.strip():
        return False
    ensure_admin_account(config, full_name=full_name, email=email, password=password)
    return True


def setup_page() -> None:
    st.set_page_config(
        page_title="StoryShelf",
        page_icon="📚",
        layout="wide",
    )
    inject_global_styles()
    init_auth_db(DB_CONFIG)
    admin_email = os.getenv("FIRST_ADMIN_EMAIL", "").strip()
    admin_password = os.getenv("FIRST_ADMIN_PASSWORD", "").strip()
    admin_name = os.getenv("FIRST_ADMIN_NAME", "").strip() or "Admin"
    bootstrap_admin_account_if_configured(DB_CONFIG, admin_name, admin_email, admin_password)

    st.session_state.setdefault("auth_user", None)
    st.session_state.setdefault("recommended_books", [])
    st.session_state.setdefault("selected_book_id", None)
    st.session_state.setdefault("student_profile", {})
    st.session_state.setdefault("latest_lesson", None)
    st.session_state.setdefault("active_session_id", None)
    st.session_state.setdefault("recommendation_chat_session_id", None)
    st.session_state.setdefault("recommendation_chat_messages", [])
    st.session_state.setdefault("recommendation_chat_owner_id", None)
    st.session_state.setdefault("recommendation_chat_error", "")
    st.session_state.setdefault("recommendation_chat_used_fallback", False)
    st.session_state.setdefault("recommendation_chat_notice", "")
    st.session_state.setdefault("feedback_saved", False)
    st.session_state.setdefault("last_quiz_result", None)
    st.session_state.setdefault("quiz_saved", False)
    st.session_state.setdefault("student_profile_record", None)
    st.session_state.setdefault("last_recommendation_signature", None)
    st.session_state.setdefault("restored_sequence_id", None)
    st.session_state.setdefault("auth_view", "login")
    st.session_state.setdefault("nav_page", STUDENT_PROGRESS_PAGE)
    st.session_state.setdefault("pending_nav_page", None)
    st.session_state.setdefault(
        "finder_preferences",
        {
            "book_type": "story",
            "topics": "",
            "length_type": "any",
            "reading_level": "easy",
        },
    )
    st.session_state.setdefault("finder_step", 1)


def reset_student_learning_state() -> None:
    st.session_state["recommended_books"] = []
    st.session_state["selected_book_id"] = None
    st.session_state["latest_lesson"] = None
    st.session_state["active_session_id"] = None
    st.session_state["recommendation_chat_session_id"] = None
    st.session_state["recommendation_chat_messages"] = []
    st.session_state["recommendation_chat_owner_id"] = None
    st.session_state["recommendation_chat_error"] = ""
    st.session_state["recommendation_chat_used_fallback"] = False
    st.session_state["recommendation_chat_notice"] = ""
    st.session_state["feedback_saved"] = False
    st.session_state["last_quiz_result"] = None
    st.session_state["quiz_saved"] = False
    st.session_state["last_recommendation_signature"] = None
    st.session_state["restored_sequence_id"] = None
    st.session_state["finder_step"] = 1
    st.session_state["finder_preferences"] = {
        "book_type": "story",
        "topics": "",
        "length_type": "any",
        "reading_level": "easy",
    }


def build_book_lookup(books_df: pd.DataFrame) -> dict[int, dict]:
    if books_df.empty:
        return {}
    return {
        int(row["id"]): row.to_dict()
        for _, row in books_df.iterrows()
    }


def reset_recommendation_chat_session(user_id: int | None = None) -> None:
    owner_id = st.session_state.get("recommendation_chat_owner_id")
    session_id = st.session_state.get("recommendation_chat_session_id")
    if session_id and owner_id and (user_id is None or int(owner_id) == int(user_id)):
        try:
            delete_recommendation_session(RECOMMENDATION_API_BASE_URL, str(session_id))
        except RecommendationAPIError:
            LOGGER.warning("Unable to delete recommendation chat session %s", session_id)

    st.session_state["recommendation_chat_session_id"] = None
    st.session_state["recommendation_chat_messages"] = []
    st.session_state["recommendation_chat_owner_id"] = None
    st.session_state["recommendation_chat_error"] = ""
    st.session_state["recommendation_chat_used_fallback"] = False


def ensure_recommendation_chat_owner(user_id: int) -> None:
    owner_id = st.session_state.get("recommendation_chat_owner_id")
    if owner_id is None:
        st.session_state["recommendation_chat_owner_id"] = int(user_id)
        return
    if int(owner_id) != int(user_id):
        reset_recommendation_chat_session()
        st.session_state["recommendation_chat_owner_id"] = int(user_id)


def build_backend_recommendation_records(backend_recommendations: list[Any], books_df: pd.DataFrame) -> list[dict[str, Any]]:
    if books_df.empty or not backend_recommendations:
        return []

    working_df = books_df.copy()
    working_df["normalized_title"] = working_df["title"].apply(normalize_text)
    working_df["normalized_author"] = working_df["author"].apply(normalize_text)
    matched_records: list[dict[str, Any]] = []
    used_ids: set[int] = set()

    for item in backend_recommendations:
        title = ""
        author = ""
        reason = ""
        if isinstance(item, dict):
            book_payload = item.get("book") if isinstance(item.get("book"), dict) else {}
            title = str(
                item.get("title")
                or item.get("book_title")
                or item.get("name")
                or book_payload.get("title")
                or book_payload.get("book_title")
                or ""
            ).strip()
            author = str(item.get("author") or book_payload.get("author") or "").strip()
            reason = str(item.get("reason") or item.get("why") or item.get("explanation") or "").strip()
        elif isinstance(item, str):
            title = item.strip()
        if not title:
            continue

        normalized_title = normalize_text(title)
        normalized_author = normalize_text(author)
        candidates = working_df[working_df["normalized_title"] == normalized_title]
        if candidates.empty and normalized_title:
            candidates = working_df[working_df["normalized_title"].str.contains(normalized_title, na=False)]
        if candidates.empty and normalized_author:
            candidates = working_df[working_df["normalized_author"] == normalized_author]
        if candidates.empty:
            continue

        for _, row in candidates.iterrows():
            book_id = int(row["id"])
            if book_id in used_ids:
                continue
            record = row.to_dict()
            record["simple_recommendation_reason"] = reason or "Recommended from your conversation with StoryShelf."
            matched_records.append(record)
            used_ids.add(book_id)
            break

    return matched_records


def generate_fallback_recommendations(profile: dict[str, Any], books_df: pd.DataFrame, message: str) -> list[dict[str, Any]]:
    if books_df.empty:
        return []

    learning_profile = profile.get("learning_profile", {}) if isinstance(profile, dict) else {}
    fallback_preferences = {
        "grade": profile.get("class_grade", ""),
        "book_type": "any",
        "topics": message,
        "length_type": "any",
        "reading_level": profile.get("reading_level", "easy") or "easy",
        "profile_topics": ", ".join(learning_profile.get("interest_topics", [])),
        "profile_genres": ", ".join(learning_profile.get("preferred_genres", [])),
        "profile_lengths": ", ".join(learning_profile.get("preferred_lengths", [])),
        "profile_subjects": ", ".join(learning_profile.get("strongest_subjects", [])),
        "profile_concepts": ", ".join(learning_profile.get("strongest_concepts", [])),
        "weighted_topics_json": json.dumps(learning_profile.get("weighted_topics", [])),
        "weighted_genres_json": json.dumps(learning_profile.get("weighted_genres", [])),
        "weighted_lengths_json": json.dumps(learning_profile.get("weighted_lengths", [])),
        "preference_confidence": str(learning_profile.get("preference_confidence", "emerging")),
    }
    recommendations = get_recommendations_cached(
        books_df,
        tuple(sorted((str(key), str(value)) for key, value in fallback_preferences.items())),
        top_n=5,
    )
    return recommendations.to_dict(orient="records")


def build_fallback_assistant_message(message: str, recommendations_found: bool) -> str:
    if recommendations_found:
        return "I could not use the live chat service just now, so I matched a few books from your school library instead."
    if message.strip():
        return "I could not reach the live recommendation service right now. You can try again, or use the quick recommendation path below."
    return "The recommendation service is not ready right now. You can still use the quick recommendation path below."


def store_recommendation_records_for_student(
    user_id: int,
    profile: dict[str, Any],
    recommendation_records: list[dict[str, Any]],
    *,
    source: str,
    message: str,
    backend_session_id: str | None = None,
) -> None:
    st.session_state["recommended_books"] = recommendation_records
    st.session_state["last_recommendation_signature"] = None
    st.session_state["active_session_id"] = create_recommendation_session(
        DB_CONFIG,
        student_id=int(user_id),
        grade=profile.get("class_grade", ""),
        preferences={
            "source": source,
            "message": message,
            "backend_session_id": backend_session_id or "",
        },
        recommended_books=recommendation_records,
    )
    st.session_state["latest_lesson"] = None
    st.session_state["feedback_saved"] = False
    st.session_state["selected_book_id"] = None
    st.session_state["last_quiz_result"] = None
    st.session_state["quiz_saved"] = False


def build_student_recommendation_preferences(
    profile: dict[str, Any],
    finder_state: dict[str, Any],
    learning_profile: dict[str, Any],
) -> dict[str, str]:
    return {
        "grade": profile["class_grade"],
        "book_type": str(finder_state.get("book_type", "story")),
        "topics": str(finder_state.get("topics", "")),
        "length_type": str(finder_state.get("length_type", "any")),
        "reading_level": str(finder_state.get("reading_level", "easy")),
        "profile_topics": ", ".join(learning_profile.get("interest_topics", [])),
        "profile_genres": ", ".join(learning_profile.get("preferred_genres", [])),
        "profile_lengths": ", ".join(learning_profile.get("preferred_lengths", [])),
        "profile_subjects": ", ".join(learning_profile.get("strongest_subjects", [])),
        "profile_concepts": ", ".join(learning_profile.get("strongest_concepts", [])),
        "weighted_topics_json": json.dumps(learning_profile.get("weighted_topics", [])),
        "weighted_genres_json": json.dumps(learning_profile.get("weighted_genres", [])),
        "weighted_lengths_json": json.dumps(learning_profile.get("weighted_lengths", [])),
        "preference_confidence": str(learning_profile.get("preference_confidence", "emerging")),
    }


def resolve_final_concept(manual_concept: str, quick_pick: str, concept_suggestions: list[str]) -> str:
    manual_value = manual_concept.strip()
    if manual_value:
        return manual_value
    if quick_pick and quick_pick != "I want to type my own concept":
        return quick_pick.strip()
    return concept_suggestions[0].strip() if concept_suggestions else ""


def hydrate_latest_lesson_from_sequence(sequence: dict[str, Any]) -> dict[str, Any]:
    quiz_score = sequence.get("quiz_score")
    total_questions = sequence.get("total_questions")
    quiz_payload = sequence.get("quiz_payload", []) or []
    quiz_answers = sequence.get("quiz_answers", []) or []
    quiz_result = None
    if quiz_payload and quiz_answers:
        quiz_result = score_sequence_quiz(quiz_payload, [str(answer) for answer in quiz_answers])
    elif quiz_score is not None and total_questions:
        percentage = round((float(quiz_score) / float(total_questions)) * 100.0, 1) if total_questions else 0.0
        passed = bool(sequence.get("passed"))
        quiz_result = {
            "score": int(quiz_score),
            "total_questions": int(total_questions),
            "percentage": percentage,
            "passed": passed,
            "results": [],
            "summary": "Great work. You passed the quiz." if passed else "Good try. Review the lesson and try the quiz again.",
            "review_summary": (
                "You passed the learning check. Keep using the same book idea and concept connection."
                if passed
                else "Review the concept, the key examples, and one real book detail before trying again."
            ),
        }

    return {
        "book_id": int(sequence["book_id"]),
        "subject": sequence.get("subject", ""),
        "concept": sequence.get("concept", ""),
        "requested_concept": sequence.get("concept", ""),
        "grade": "",
        "generated_lesson": sequence.get("lesson_content", ""),
        "warning": "",
        "sections": [],
        "teach_sections": [],
        "fit_result": {"level": sequence.get("fit_level", "")},
        "lesson_log_id": sequence.get("lesson_id"),
        "sequence_id": int(sequence["id"]),
        "reflect_question": {"prompt": sequence.get("reflect_question", "")} if sequence.get("reflect_question") else None,
        "reflect_answer": sequence.get("reflect_answer", "") or "",
        "reflect_feedback": sequence.get("reflect_feedback"),
        "activity": {"prompt": sequence.get("activity_prompt", "")} if sequence.get("activity_prompt") else None,
        "activity_answer": sequence.get("activity_answer", "") or "",
        "activity_feedback": sequence.get("activity_feedback"),
        "quiz_questions": quiz_payload,
        "quiz_result": quiz_result,
        "quiz_attempts": [],
        "retry_count": int(sequence.get("retry_count", 0) or 0),
        "passed": bool(sequence.get("passed")),
        "mode": "lesson",
    }


def restore_latest_sequence_state(
    user_id: int,
    selected_book_id: int,
    book: dict[str, Any],
    profile: dict[str, Any],
    learning_profile: dict[str, Any] | None = None,
) -> None:
    persisted_sequence = fetch_latest_lesson_sequence_for_user(DB_CONFIG, user_id, book_id=selected_book_id)
    if not persisted_sequence:
        return
    if st.session_state.get("restored_sequence_id") == persisted_sequence["id"]:
        return

    latest_lesson = hydrate_latest_lesson_from_sequence(persisted_sequence)
    regenerated_sequence = generate_learning_sequence(
        book=book,
        subject=persisted_sequence.get("subject", "English"),
        concept=persisted_sequence.get("concept", ""),
        grade=profile["class_grade"],
        student_context={
            "reading_level": profile.get("reading_level", ""),
            "quiz_band": (learning_profile or {}).get("quiz_band", ""),
            "strongest_concepts": (learning_profile or {}).get("strongest_concepts", []),
            "weak_concepts": (learning_profile or {}).get("weak_concepts", []),
        },
    )
    latest_lesson["teach_sections"] = regenerated_sequence.get("teach_sections", [])
    latest_lesson["sections"] = latest_lesson["teach_sections"]
    latest_lesson["adaptive_profile"] = regenerated_sequence.get("adaptive_profile", {})
    st.session_state["latest_lesson"] = latest_lesson
    st.session_state["story_learning_subject"] = persisted_sequence.get("subject", "English")
    st.session_state["story_learning_quick_pick"] = "I want to type my own concept"
    st.session_state["story_learning_concept"] = persisted_sequence.get("concept", "")
    st.session_state["restored_sequence_id"] = persisted_sequence["id"]


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
    role = normalize_role(role)
    if role == "admin":
        return ADMIN_DASHBOARD_PAGE
    return STUDENT_PROGRESS_PAGE


def set_current_page(page: str) -> None:
    st.session_state["nav_page"] = page
    st.session_state["pending_nav_page"] = page


def logout_user() -> None:
    auth_view = st.session_state.get("auth_view", "login")
    auth_user = st.session_state.get("auth_user")
    if auth_user and auth_user.get("id"):
        reset_recommendation_chat_session(int(auth_user["id"]))
    st.session_state.clear()
    setup_page()
    st.session_state["auth_user"] = None
    st.session_state["auth_view"] = auth_view
    set_current_page(STUDENT_PROGRESS_PAGE)


def get_student_resume_book(user_id: int) -> dict | None:
    latest_lesson = st.session_state.get("latest_lesson")
    if latest_lesson and latest_lesson.get("book_id"):
        return fetch_book_by_id(DB_CONFIG, int(latest_lesson["book_id"]))

    persisted_sequence = fetch_latest_lesson_sequence_for_user(DB_CONFIG, user_id)
    if persisted_sequence and persisted_sequence.get("book_id"):
        return fetch_book_by_id(DB_CONFIG, int(persisted_sequence["book_id"]))

    selected_book_id = st.session_state.get("selected_book_id")
    if selected_book_id:
        return fetch_book_by_id(DB_CONFIG, int(selected_book_id))

    dashboard = fetch_student_dashboard_data_for_user(DB_CONFIG, user_id)
    if dashboard.get("last_selected_book_id"):
        return fetch_book_by_id(DB_CONFIG, int(dashboard["last_selected_book_id"]))
    if dashboard.get("last_lesson_book_id"):
        return fetch_book_by_id(DB_CONFIG, int(dashboard["last_lesson_book_id"]))

    return None


def render_student_journey_header(
    *,
    user: dict,
    current_page: str,
    title: str,
    body: str,
    kicker: str,
) -> None:
    render_brand_header("student")
    clicked_page = render_student_top_navigation(str(user.get("full_name") or "Student"), current_page)
    if clicked_page == STUDENT_SIGN_OUT:
        logout_user()
        st.rerun()
    if clicked_page and clicked_page != current_page:
        set_current_page(clicked_page)
        st.rerun()

    dashboard = fetch_student_dashboard_data_for_user(DB_CONFIG, int(user["id"]))
    has_profile = fetch_student_profile_for_user(DB_CONFIG, int(user["id"])) is not None
    has_lesson = dashboard.get("total_lessons_generated", 0) > 0 or bool(st.session_state.get("latest_lesson"))
    has_quiz = dashboard.get("quiz_attempts", 0) > 0 or st.session_state.get("last_quiz_result") is not None

    step_lookup = {
        STUDENT_DISCOVER_PAGE: 2,
        STUDENT_BOOKS_PAGE: 2,
        STUDENT_LEARN_PAGE: 3 if not has_quiz else 4,
        STUDENT_PROGRESS_PAGE: 4 if has_quiz else 3,
    }
    current_step = step_lookup.get(current_page, 1)
    if not has_profile:
        current_step = 1
    elif has_quiz and current_page == STUDENT_PROGRESS_PAGE:
        current_step = 5
    elif current_page == STUDENT_PROGRESS_PAGE and has_lesson:
        current_step = 4

    render_hero(title, body, kicker=kicker)
    render_progress_steps(
        ["Profile", "Find Book", "Learn", "Quiz", "Progress"],
        current_step,
    )

    summary_cards = [
        {"label": "Books explored", "value": str(dashboard.get("total_books_explored", 0)), "note": "Books you opened or selected"},
        {"label": "Saved books", "value": str(dashboard.get("total_books_saved", 0)), "note": "Stories waiting on your shelf"},
        {"label": "Lessons started", "value": str(dashboard.get("total_lessons_generated", 0)), "note": "Learning journeys you began"},
    ]
    render_metric_grid(summary_cards)

    resume_book = get_student_resume_book(int(user["id"]))
    if resume_book and current_page != STUDENT_LEARN_PAGE:
        resume_title = str(resume_book.get("title") or "Your selected book")
        if st.session_state.get("latest_lesson"):
            resume_body = "Your lesson is already prepared. Open Learn to keep going with the lesson and quiz."
        else:
            resume_body = "You already picked a book. Open Learn to continue from the same story."
        render_resume_banner(resume_title, resume_body)
        if st.button("Continue Learning", key=f"continue_learning_{current_page.lower().replace(' ', '_')}", type="primary", use_container_width=False):
            st.session_state["selected_book_id"] = int(resume_book["id"])
            set_current_page(STUDENT_LEARN_PAGE)
            st.rerun()


def enforce_role(required_roles: set[str]) -> dict | None:
    user = get_current_user()
    if not user:
        st.warning("Please log in to continue.")
        st.session_state["auth_view"] = "login"
        return None
    role = str(user.get("role", "")).lower()
    normalized_role = normalize_role(role)
    normalized_required_roles = {normalize_role(item) for item in required_roles}
    if normalized_role not in normalized_required_roles:
        st.error("This page is not available for your account.")
        set_current_page(default_page_for_role(normalized_role))
        return None
    return user


def render_auth_page() -> None:
    auth_options = ["Login", "Student Sign Up", "Admin Setup"]

    render_brand_header()
    render_hero(
        "Welcome to StoryShelf",
        "Discover library books, learn through stories, and manage the school catalog in one calm, guided app.",
        kicker="Authentication",
    )
    selected_view = st.radio(
        "Choose how you want to enter",
        auth_options,
        horizontal=True,
        index=max(0, auth_options.index(
            "Admin Setup" if st.session_state.get("auth_view") == "admin_setup"
            else "Student Sign Up" if st.session_state.get("auth_view") == "signup"
            else "Login"
        )),
    )
    st.caption("Students and admins use the same login form. Use Admin Setup only when you need to create the first admin account.")
    if selected_view == "Login":
        st.session_state["auth_view"] = "login"
    elif selected_view == "Admin Setup":
        st.session_state["auth_view"] = "admin_setup"
    else:
        st.session_state["auth_view"] = "signup"

    if selected_view == "Login":
        with st.container(border=True):
            st.markdown("### Login")
            st.caption("Use your student or admin email to continue.")
            with st.form("login_form"):
                email = st.text_input("Email", key="login_email")
                password = st.text_input("Password", type="password", key="login_password")
                submitted = st.form_submit_button("Log In", type="primary", use_container_width=True)
            if submitted:
                user = authenticate_user(DB_CONFIG, email=email, password=password)
                if not user:
                    st.error("Email or password not recognized.")
                else:
                    st.session_state["auth_user"] = user
                    set_current_page(default_page_for_role(str(user.get("role", "student"))))
                    reset_student_learning_state()
                    st.rerun()
    elif selected_view == "Student Sign Up":
        with st.container(border=True):
            st.markdown("### Student Sign Up")
            st.caption("Create a student account to begin your reading journey.")
            with st.form("signup_form"):
                full_name = st.text_input("Full name", key="signup_full_name")
                email = st.text_input("Email", key="signup_email")
                password = st.text_input("Password", type="password", key="signup_password")
                confirm_password = st.text_input("Confirm password", type="password", key="signup_confirm_password")
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
                        try:
                            user_id = create_user(DB_CONFIG, full_name=full_name, email=email, password=password, role="student")
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.session_state["auth_user"] = fetch_user_by_id(DB_CONFIG, user_id)
                            set_current_page(default_page_for_role("student"))
                            reset_student_learning_state()
                            st.success("Student account created. You can now complete the profile and start exploring books.")
                            st.rerun()
    else:
        with st.container(border=True):
            st.markdown("### Admin Setup")
            st.caption("Create the first admin account. After that, new admin accounts can be created from User Management.")
            with st.form("first_admin_form"):
                full_name = st.text_input("Admin full name", value="School Admin", key="admin_signup_full_name")
                email = st.text_input("Admin email", key="admin_signup_email")
                password = st.text_input("Admin password", type="password", key="admin_signup_password")
                confirm_password = st.text_input("Confirm admin password", type="password", key="admin_signup_confirm_password")
                submitted = st.form_submit_button("Create Admin Account", type="primary", use_container_width=True)
            if submitted:
                admin_exists = fetch_admin_user_count(DB_CONFIG) > 0
                if admin_exists:
                    st.error("An admin account already exists. Please log in.")
                elif not full_name.strip():
                    st.error("Please enter the admin's full name.")
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
                        try:
                            user_id = create_user(DB_CONFIG, full_name=full_name, email=email, password=password, role="admin")
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.session_state["auth_user"] = fetch_user_by_id(DB_CONFIG, user_id)
                            st.session_state["auth_view"] = "login"
                            set_current_page(default_page_for_role("admin"))
                            reset_student_learning_state()
                            st.success("Admin account created.")
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
        st.info("Complete your profile in My Progress before continuing.")
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
        "grade": profile.get("class_grade", "") if profile else "",
        "preferred_language": profile.get("preferred_language", "English") if profile else "English",
        "favorite_topics": profile.get("favorite_topics", "") if profile else "",
        "reading_level": profile.get("reading_level", "easy") if profile else "easy",
    }
    grade_options = ["Select grade"] + [str(level) for level in range(1, 13)]
    selected_grade = str(current_profile.get("grade", "") or "")
    grade_index = grade_options.index(selected_grade) if selected_grade in grade_options else 0

    render_section_heading("Your profile", "This helps StoryShelf suggest books that fit you better.")
    with st.container(border=True):
        if profile:
            render_status_tip(
                "Saved profile",
                f"Grade {current_profile['grade']} | {current_profile['preferred_language']} | {current_profile['reading_level']} reading",
            )
            if current_profile.get("favorite_topics", "").strip():
                st.caption(f"Favorite topics: {current_profile['favorite_topics']}")
            profile_container = st.expander("Edit profile", expanded=False)
        else:
            render_status_tip(
                "Profile needed",
                "Complete this once so StoryShelf can personalize book suggestions and lesson difficulty for you.",
            )
            profile_container = st.container()

        with profile_container:
            with st.form("student_profile_form"):
                name = st.text_input("Student name", value=current_profile.get("name", ""), key="student_profile_name")
                grade = st.selectbox(
                    "Class / grade",
                    grade_options,
                    index=grade_index,
                    key="student_profile_grade",
                )
                preferred_language = st.selectbox(
                    "Preferred language",
                    LANGUAGE_OPTIONS,
                    index=LANGUAGE_OPTIONS.index(current_profile.get("preferred_language", "English")) if current_profile.get("preferred_language", "English") in LANGUAGE_OPTIONS else 0,
                    key="student_profile_language",
                )
                favorite_topics = st.text_input(
                    "Favorite topics",
                    value=current_profile.get("favorite_topics", ""),
                    placeholder="animals, science, friendship, space",
                    key="student_profile_topics",
                )
                reading_level = st.selectbox(
                    "Reading comfort level",
                    READING_LEVEL_OPTIONS,
                    index=READING_LEVEL_OPTIONS.index(current_profile.get("reading_level", "easy")) if current_profile.get("reading_level", "easy") in READING_LEVEL_OPTIONS else 0,
                    key="student_profile_reading_level",
                )
                saved = st.form_submit_button("Save Profile", type="primary", use_container_width=True)

            if saved:
                if not name.strip():
                    st.error("Please enter the student's name.")
                elif grade == "Select grade":
                    st.error("Please choose the student's class or grade.")
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
                    st.success("Profile saved.")


def home_page() -> None:
    user = get_current_user()
    role = normalize_role(str(user.get("role", "student"))) if user else "student"
    render_brand_header(role)
    render_hero(
        "Welcome to StoryShelf",
        "A school library experience where students discover books, save their journey, and learn through guided story-based lessons.",
        kicker="Welcome",
    )
    if role == "student" and user:
        dashboard = fetch_student_dashboard_data_for_user(DB_CONFIG, int(user["id"]))
        learning_profile = dashboard.get("learning_profile", {})
        render_metric_grid(
            [
                {"label": "Books explored", "value": str(dashboard["total_books_explored"]), "note": "Stories you have opened or chosen"},
                {"label": "Saved books", "value": str(dashboard["total_books_saved"]), "note": "Books waiting for your next visit"},
                {"label": "Lessons started", "value": str(dashboard["total_lessons_generated"]), "note": "Guided learning journeys you began"},
                {"label": "Quizzes passed", "value": str(dashboard["total_quizzes_passed"]), "note": "Learning checks you completed successfully"},
            ]
        )
        col1, col2 = st.columns([1.05, 0.95])
        with col1:
            render_section_heading("Continue your reading journey", "Move through the app step by step instead of jumping between unrelated screens.")
            render_status_tip(
                "Suggested path",
                "Start in My Progress, then discover a book, save it to My Books, and finish in Learn.",
            )
            if dashboard["favorite_topics"]:
                render_status_tip("Favorite topics", dashboard["favorite_topics"])
            else:
                render_status_tip("Favorite topics", "Add favorite topics in your profile to get sharper recommendations.")
            if dashboard.get("recent_concepts_learned"):
                render_status_tip("Recent concepts", ", ".join(dashboard["recent_concepts_learned"]))
        with col2:
            render_section_heading("Recent activity", "Your newest actions show up here so you can continue where you left off.")
            if dashboard["recent_activity"].empty:
                render_empty_state("Your reading timeline is waiting", "Save your profile and ask for book recommendations to begin your first reading journey.", "🚀")
            else:
                st.dataframe(dashboard["recent_activity"], use_container_width=True, hide_index=True)
        if learning_profile:
            summary_col1, summary_col2 = st.columns(2)
            with summary_col1:
                render_status_tip(
                    "Your learning rhythm",
                    (
                        f"{learning_profile.get('quiz_band', 'growing').title()} learner with favorite topics like "
                        f"{', '.join(learning_profile.get('favorite_topics', [])[:3]) or 'new discoveries on the way'}."
                    ),
                )
            with summary_col2:
                render_status_tip(
                    "Next best move",
                    learning_profile.get("next_focus") or "Discover a new book to unlock a personalized next step.",
                )
        action_col1, action_col2, action_col3 = st.columns(3)
        with action_col1:
            if st.button("Open My Progress", key="home_open_progress", type="primary", use_container_width=True):
                set_current_page(STUDENT_PROGRESS_PAGE)
                st.rerun()
        with action_col2:
            if st.button("Discover Books", key="home_discover_books", use_container_width=True):
                set_current_page(STUDENT_DISCOVER_PAGE)
                st.rerun()
        with action_col3:
            if st.button("Go to Learn", key="home_go_learn", use_container_width=True):
                set_current_page(STUDENT_LEARN_PAGE)
                st.rerun()
    else:
        metrics = fetch_dashboard_metrics(DB_CONFIG)
        render_metric_grid(
            [
                {"label": "Catalog uploads", "value": str(metrics["total_uploads"]), "note": "Imports completed so far"},
                {"label": "Books in catalog", "value": str(metrics["total_books"]), "note": "Titles available for recommendations"},
                {"label": "Recommendation sessions", "value": str(metrics["total_recommendation_sessions"]), "note": "Student journeys launched"},
                {
                    "label": "Average rating",
                    "value": f"{metrics['average_feedback_rating']:.2f}" if metrics["average_feedback_rating"] is not None else "No ratings yet",
                    "note": "Student feedback snapshot",
                },
            ]
        )
        render_section_heading("Admin control center", "Keep the app calm and school-ready by managing the catalog, lessons, and users from one place.")
        col1, col2 = st.columns(2)
        with col1:
            render_status_tip("What to check first", "Review the dashboard, then make sure the catalog is uploaded and student insights are healthy.")
        with col2:
            render_status_tip("What students see", "Students get a guided reading flow with recommendations, adaptive lessons, quizzes, and progress tracking.")


def admin_page() -> None:
    if not enforce_role({"admin"}):
        return
    render_brand_header("admin")
    render_hero(
        "Catalog Upload",
        "Upload the school library Excel file and save it safely for students to explore.",
        kicker="Admin space",
    )
    render_section_heading("Upload the school catalog", "The importer can handle missing columns, mixed page values, and messy spreadsheet exports.")

    uploaded_file = st.file_uploader("Upload library catalog (.xlsx)", type=["xlsx"])
    if uploaded_file is None:
        render_empty_state("Upload a catalog to get started", "Add a school library Excel file here to fill StoryShelf with books.", "📥")
        return

    if st.button("Import Catalog", type="primary", use_container_width=True):
        try:
            with st.spinner("Importing catalog..."):
                result = ingest_catalog(uploaded_file, DB_CONFIG)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Catalog upload failed", exc_info=exc)
            st.error("The catalog could not be imported. Please check the file and try again.")
            return

        reset_student_learning_state()
        log_catalog_upload(DB_CONFIG, result["imported_count"], result["columns"])

        st.success(f"Catalog uploaded. {result['imported_count']} books are now available.")
        with st.expander("Preview import details", expanded=True):
            st.write("**Detected columns:**", ", ".join(result["columns"]))
            st.dataframe(result["preview"], use_container_width=True, hide_index=True)


def student_dashboard_page() -> None:
    user = enforce_role({"student"})
    if not user:
        return
    render_student_journey_header(
        user=user,
        current_page=STUDENT_PROGRESS_PAGE,
        title="My Progress",
        body="See your reading journey, update your profile, and continue the next best step without hunting across pages.",
        kicker="Student progress",
    )
    render_student_profile_manager()
    profile = require_student_profile()
    if not profile:
        return

    dashboard = fetch_student_dashboard_data_for_user(DB_CONFIG, int(user["id"]))
    learning_profile = dashboard.get("learning_profile", {})
    render_metric_grid(
        [
            {"label": "Books explored", "value": str(dashboard["total_books_explored"]), "note": "Books you visited or selected"},
            {"label": "Saved books", "value": str(dashboard["total_books_saved"]), "note": "Stories saved for later"},
            {"label": "Lessons started", "value": str(dashboard["total_lessons_generated"]), "note": "Guided learning sequences you began"},
            {"label": "Quizzes passed", "value": str(dashboard["total_quizzes_passed"]), "note": "Pass checks you completed successfully"},
        ]
    )

    col1, col2 = st.columns([0.95, 1.05])
    with col1:
        render_status_tip("Favorite topics", dashboard["favorite_topics"] or "Add favorite topics to help StoryShelf suggest better matches.")
    with col2:
        render_status_tip(
            "Quiz performance",
            (
                f"{dashboard['quiz_attempts']} quiz attempts with an average score of {dashboard['quiz_average_percent']}%"
                if dashboard.get("quiz_average_percent") is not None
                else "Generate a lesson and try the quiz to start building your learning score."
            ),
        )
    render_status_tip("Lessons completed", str(dashboard["total_lessons_completed"]))
    if dashboard.get("recent_concepts_learned"):
        render_status_tip("Recent concepts learned", ", ".join(dashboard["recent_concepts_learned"]))
    if learning_profile:
        insight_col1, insight_col2 = st.columns(2)
        with insight_col1:
            render_status_tip(
                "Learning profile",
                (
                    f"{learning_profile.get('quiz_band', 'growing').title()} learner"
                    if learning_profile.get("quiz_band")
                    else "Your learning profile will grow as you explore more books."
                ),
            )
            render_status_tip(
                "Preferred book styles",
                ", ".join(learning_profile.get("preferred_genres", []))
                or "Your favorite book styles will appear here after you explore more titles.",
            )
        with insight_col2:
            render_status_tip(
                "Strongest subjects",
                ", ".join(learning_profile.get("strongest_subjects", []))
                or "Your strongest subjects will appear here after a few lessons.",
            )
            render_status_tip(
                "Next focus",
                learning_profile.get("next_focus") or "Complete one more lesson to unlock a next-step suggestion.",
            )
    memory_col1, memory_col2 = st.columns(2)
    with memory_col1:
        remembered_topics = learning_profile.get("interest_topics", [])
        remembered_genres = learning_profile.get("preferred_genres", [])
        render_status_tip(
            "What StoryShelf remembers",
            (
                f"Topics: {', '.join(remembered_topics[:3]) or 'none yet'} | Genres: {', '.join(remembered_genres[:2]) or 'none yet'}"
            ),
        )
    with memory_col2:
        mastered_concepts = learning_profile.get("mastered_concepts", [])
        weak_concepts = learning_profile.get("weak_concepts", [])
        render_status_tip(
            "Concept mastery",
            (
                f"Strongest: {', '.join(mastered_concepts[:2]) or 'none yet'} | Needs support: {', '.join(weak_concepts[:2]) or 'none yet'}"
            ),
        )
    st.caption(f"Preference confidence: {str(learning_profile.get('preference_confidence', 'emerging')).title()}")

    render_section_heading("Recent activity", "These are the newest things you did across reading, lessons, and quiz practice.")
    if dashboard["recent_activity"].empty:
        render_empty_state("No progress yet", "Save your profile and discover a book to begin your StoryShelf journey.", "📖")
        if st.button("Discover Books", key="progress_empty_discover", type="primary", use_container_width=True):
            set_current_page(STUDENT_DISCOVER_PAGE)
            st.rerun()
    else:
        st.dataframe(dashboard["recent_activity"], use_container_width=True, hide_index=True)

    render_section_heading("Your history", "Browse your reading trail, recommendations, selected books, lessons, and quiz results in one place.")
    history_tabs = st.tabs(["Reading History", "Recommended Books", "Selected Books", "Generated Lessons", "Quiz History", "Preference Memory", "Concept Mastery"])
    history_frames = [
        dashboard["reading_history"].drop(columns=["book_id"], errors="ignore"),
        dashboard["recommended_history"],
        dashboard["selected_history"].drop(columns=["book_id"], errors="ignore"),
        dashboard["lesson_history"].drop(columns=["book_id", "sequence_id"], errors="ignore"),
        dashboard["quiz_history"].drop(columns=["book_id"], errors="ignore"),
        dashboard["preference_memory"].drop(columns=["updated_at"], errors="ignore"),
        dashboard["concept_mastery"].drop(columns=["updated_at"], errors="ignore"),
    ]
    empty_messages = [
        "No saved or finished books yet.",
        "No recommendation history yet.",
        "No chosen books yet.",
        "No lessons yet.",
        "No quiz history yet.",
        "No preference memory yet.",
        "No concept mastery yet.",
    ]
    for tab, frame, message in zip(history_tabs, history_frames, empty_messages):
        with tab:
            if frame.empty:
                st.info(message)
                if message == "No saved or finished books yet.":
                    if st.button("Find Books", key="history_empty_reading", type="primary", use_container_width=True):
                        set_current_page(STUDENT_DISCOVER_PAGE)
                        st.rerun()
                elif message == "No recommendation history yet.":
                    if st.button("Start Discovering", key="history_empty_recommendations", type="primary", use_container_width=True):
                        set_current_page(STUDENT_DISCOVER_PAGE)
                        st.rerun()
                elif message == "No chosen books yet.":
                    if st.button("Open My Books", key="history_empty_selected", type="primary", use_container_width=True):
                        set_current_page(STUDENT_BOOKS_PAGE)
                        st.rerun()
                elif message == "No lessons yet.":
                    if st.button("Go to Learn", key="history_empty_lessons", type="primary", use_container_width=True):
                        set_current_page(STUDENT_LEARN_PAGE)
                        st.rerun()
                elif message == "No quiz history yet.":
                    if st.button("Start a Quiz", key="history_empty_quiz", type="primary", use_container_width=True):
                        set_current_page(STUDENT_LEARN_PAGE)
                        st.rerun()
            else:
                st.dataframe(frame, use_container_width=True, hide_index=True)


def my_books_page() -> None:
    user = enforce_role({"student"})
    if not user:
        return
    render_student_journey_header(
        user=user,
        current_page=STUDENT_BOOKS_PAGE,
        title="My Books",
        body="Keep your saved books, finished books, and next reading choice together in one calm place.",
        kicker="Student library",
    )
    profile = require_student_profile()
    if not profile:
        return

    dashboard = fetch_student_dashboard_data_for_user(DB_CONFIG, int(user["id"]))
    reading_history = dashboard["reading_history"].copy()
    render_metric_grid(
        [
            {"label": "Saved for later", "value": str(dashboard["total_books_saved"]), "note": "Books you can reopen any time"},
            {"label": "Finished books", "value": str(dashboard["total_books_marked_as_read"]), "note": "Books you marked as read"},
            {"label": "Lessons ready", "value": str(dashboard["total_lessons_generated"]), "note": "Learning journeys linked to your books"},
        ]
    )
    if reading_history.empty:
        render_empty_state("No saved books yet", "Save a book from Discover Books and it will show up here for quick access later.", "📚")
        if st.button("Go to Discover Books", key="my_books_empty_discover", type="primary", use_container_width=True):
            set_current_page(STUDENT_DISCOVER_PAGE)
            st.rerun()
        return

    selected_book_id = st.session_state.get("selected_book_id")
    if selected_book_id:
        selected_book = fetch_book_by_id(DB_CONFIG, int(selected_book_id))
        if selected_book:
            render_resume_banner(
                str(selected_book.get("title") or "Your selected book"),
                "This book is already waiting for you in Learn.",
            )

    saved_books = reading_history[reading_history["status"].isin(["saved", "saved_read"])] if "status" in reading_history.columns else pd.DataFrame()
    finished_books = reading_history[reading_history["status"].isin(["read", "saved_read"])] if "status" in reading_history.columns else pd.DataFrame()

    render_section_heading("Saved for later", "These are the books you kept for your next reading session.")
    if saved_books.empty:
        render_empty_state("No saved books", "Save a book from Discover Books to build your own shelf.", "📚")
    else:
        for _, row in saved_books.iterrows():
            with st.container(border=True):
                st.markdown(f"### {row.get('title', 'Untitled book')}")
                st.caption(f"by {row.get('author', 'Unknown author')}")
                status_text = "Marked as read too" if str(row.get("status", "")) == "saved_read" else "Saved for later"
                st.write(status_text)
                if st.button("Open in Learn", key=f"open_saved_book_{int(row['book_id'])}", type="primary", use_container_width=True):
                    st.session_state["selected_book_id"] = int(row["book_id"])
                    set_current_page(STUDENT_LEARN_PAGE)
                    st.rerun()

    if saved_books.empty:
        if st.button("Discover More Books", key="my_books_no_saved_action", type="primary", use_container_width=True):
            set_current_page(STUDENT_DISCOVER_PAGE)
            st.rerun()

    render_section_heading("Finished books", "Look back at the books you already completed or used in learning.")
    if finished_books.empty:
        render_empty_state("No read books yet", "Mark a book as read after finishing it and it will show up here.", "📘")
    else:
        st.dataframe(finished_books.drop(columns=["book_id"], errors="ignore"), use_container_width=True, hide_index=True)


def render_recommendation_chat(user: dict[str, Any], profile: dict[str, Any], books_df: pd.DataFrame) -> None:
    ensure_recommendation_chat_owner(int(user["id"]))
    render_section_heading(
        "Recommendation chat",
        "Tell StoryShelf what you want to read. You can chat naturally here, or use the quick path below.",
    )
    with st.container(border=True):
        top_left, top_right = st.columns([1, 1])
        with top_left:
            render_status_tip(
                "How it works",
                "Ask for a kind of story, a topic, or a reading mood. StoryShelf will keep the conversation going and suggest books.",
            )
        with top_right:
            if st.button("Start new recommendation chat", key="start_new_recommendation_chat", use_container_width=True):
                reset_recommendation_chat_session(int(user["id"]))
                st.session_state["recommended_books"] = []
                st.session_state["selected_book_id"] = None
                st.session_state["active_session_id"] = None
                st.rerun()

        chat_messages = st.session_state.get("recommendation_chat_messages", [])
        if not chat_messages:
            render_chat_bubble(
                f"Hi {profile['full_name']}! Tell me what kind of book you want, like mystery, animals, space, funny stories, or short books.",
                speaker="bot",
            )
        else:
            for chat_message in chat_messages:
                render_chat_bubble(
                    str(chat_message.get("content", "")),
                    speaker="user" if chat_message.get("role") == "user" else "bot",
                )

        chat_error = st.session_state.get("recommendation_chat_error", "")
        if chat_error:
            st.warning(chat_error)

        chat_notice = st.session_state.get("recommendation_chat_notice", "")
        if chat_notice:
            st.info(chat_notice)

        if st.session_state.get("recommendation_chat_used_fallback"):
            st.info("StoryShelf used your school library directly for these suggestions so you can keep reading without waiting.")

        with st.form("recommendation_chat_form"):
            student_message = st.text_input(
                "What would you like to read?",
                placeholder="I want a short science book about space.",
            )
            send_message = st.form_submit_button("Send", type="primary", use_container_width=True)

        if send_message:
            message = student_message.strip()
            if not message:
                st.error("Type a message first so StoryShelf knows what to recommend.")
                return

            current_messages = list(st.session_state.get("recommendation_chat_messages", []))
            current_messages.append({"role": "user", "content": message})
            st.session_state["recommendation_chat_messages"] = current_messages

            session_id = str(st.session_state.get("recommendation_chat_session_id") or create_client_session_id())
            st.session_state["recommendation_chat_session_id"] = session_id
            st.session_state["recommendation_chat_owner_id"] = int(user["id"])
            st.session_state["recommendation_chat_error"] = ""
            st.session_state["recommendation_chat_used_fallback"] = False
            st.session_state["recommendation_chat_notice"] = ""

            recommendation_records: list[dict[str, Any]] = []
            assistant_text = ""
            backend_session_id = session_id

            try:
                api_response = send_recommendation_message(RECOMMENDATION_API_BASE_URL, message, session_id)
                backend_session_id = api_response.session_id
                st.session_state["recommendation_chat_session_id"] = backend_session_id
                assistant_text = api_response.assistant_message
                recommendation_records = build_backend_recommendation_records(api_response.recommendations, books_df)
                if api_response.had_partial_payload and not recommendation_records:
                    st.session_state["recommendation_chat_notice"] = "StoryShelf received part of the reply and is filling in the rest from your library."
                if not recommendation_records:
                    recommendation_records = generate_fallback_recommendations(profile, books_df, message)
                    if recommendation_records:
                        assistant_text = assistant_text or build_fallback_assistant_message(message, True)
                        st.session_state["recommendation_chat_used_fallback"] = True
                elif not assistant_text:
                    assistant_text = "I am still learning what fits best. Try one more detail like a topic, mood, or book length."
            except RecommendationAPIError as exc:
                if exc.should_reset_session:
                    old_session_id = st.session_state.get("recommendation_chat_session_id")
                    if old_session_id:
                        try:
                            delete_recommendation_session(RECOMMENDATION_API_BASE_URL, str(old_session_id))
                        except RecommendationAPIError:
                            LOGGER.warning("Unable to clear stale recommendation session %s", old_session_id)
                    st.session_state["recommendation_chat_session_id"] = None
                    st.session_state["recommendation_chat_owner_id"] = int(user["id"])
                recommendation_records = generate_fallback_recommendations(profile, books_df, message)
                if recommendation_records:
                    assistant_text = build_fallback_assistant_message(message, True)
                    st.session_state["recommendation_chat_used_fallback"] = True
                else:
                    assistant_text = build_fallback_assistant_message(message, False)
                    st.session_state["recommendation_chat_error"] = assistant_text
                if exc.should_reset_session:
                    st.session_state["recommendation_chat_notice"] = "StoryShelf started a fresh chat for you so the next message can continue smoothly."

            if assistant_text:
                current_messages = list(st.session_state.get("recommendation_chat_messages", []))
                current_messages.append({"role": "assistant", "content": assistant_text})
                st.session_state["recommendation_chat_messages"] = current_messages

            if recommendation_records:
                store_recommendation_records_for_student(
                    int(user["id"]),
                    profile,
                    recommendation_records,
                    source="backend_chat" if not st.session_state.get("recommendation_chat_used_fallback") else "backend_chat_fallback",
                    message=message,
                    backend_session_id=backend_session_id,
                )
            st.rerun()


def student_page() -> None:
    user = enforce_role({"student"})
    if not user:
        return
    render_student_journey_header(
        user=user,
        current_page=STUDENT_DISCOVER_PAGE,
        title="Discover Books",
        body="Chat with StoryShelf or use the quick path below to find books that match your interests, comfort level, and favorite topics.",
        kicker="Student journey",
    )
    books_df = fetch_all_books(DB_CONFIG)
    book_lookup = build_book_lookup(books_df)
    if books_df.empty:
        render_empty_state("No books are available yet", "Ask an admin to upload the school catalog so StoryShelf can start recommending books.", "📚")
        return

    profile = require_student_profile()
    if not profile:
        return
    student_dashboard = fetch_student_dashboard_data_for_user(DB_CONFIG, int(user["id"]))
    learning_profile = student_dashboard.get("learning_profile", {})
    profile = {**profile, "learning_profile": learning_profile}

    render_recommendation_chat(user, profile, books_df)

    finder_state = st.session_state.setdefault(
        "finder_preferences",
        {
            "book_type": "story",
            "topics": profile.get("favorite_topics", ""),
            "length_type": "any",
            "reading_level": profile.get("reading_level", "easy") or "easy",
        },
    )
    finder_state.setdefault("book_type", "story")
    finder_state.setdefault("topics", profile.get("favorite_topics", ""))
    finder_state.setdefault("length_type", "any")
    finder_state.setdefault("reading_level", profile.get("reading_level", "easy") or "easy")
    finder_step = int(st.session_state.get("finder_step", 1))

    render_chat_bubble("If you want a faster backup path, use the quick choices below and StoryShelf will build a short recommendation list for you.")
    render_progress_steps(
        ["Choose a style", "Share topics", "Pick a length", "Pick reading comfort", "See your books"],
        min(finder_step, 5),
    )

    with st.container(border=True):
        render_section_heading("Quick recommendation path", "Use this if you want simple pickers instead of the chat.")
        if profile.get("preferred_language"):
            st.caption(f"Preferred language: {profile['preferred_language']}")

        if finder_step == 1:
            choice = st.radio(
                "What kind of book feels right today?",
                ["story", "knowledge", "any"],
                horizontal=True,
                index=["story", "knowledge", "any"].index(finder_state.get("book_type", "story")),
                key="finder_book_type",
            )
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("Next: topics", type="primary", use_container_width=True):
                    finder_state["book_type"] = choice
                    st.session_state["finder_step"] = 2
                    st.rerun()
            with col2:
                st.button("Start over", disabled=True, use_container_width=True)
        elif finder_step == 2:
            topics = st.text_input(
                "What topics sound fun today?",
                value=finder_state.get("topics", profile.get("favorite_topics", "")),
                placeholder="animals, science, mystery, friendship, sports, space",
                key="finder_topics",
            )
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("Back", use_container_width=True):
                    st.session_state["finder_step"] = 1
                    st.rerun()
            with col2:
                if st.button("Next: book length", type="primary", use_container_width=True):
                    finder_state["topics"] = topics
                    st.session_state["finder_step"] = 3
                    st.rerun()
        elif finder_step == 3:
            length_choice = st.select_slider(
                "How long should the book feel?",
                options=["short", "medium", "long", "any"],
                value=finder_state.get("length_type", "any"),
                key="finder_length_type",
            )
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("Back", use_container_width=True):
                    st.session_state["finder_step"] = 2
                    st.rerun()
            with col2:
                if st.button("Next: reading comfort", type="primary", use_container_width=True):
                    finder_state["length_type"] = length_choice
                    st.session_state["finder_step"] = 4
                    st.rerun()
        elif finder_step == 4:
            reading_choice = st.radio(
                "How easy should the reading feel?",
                ["easy", "medium", "challenging", "any"],
                horizontal=True,
                index=["easy", "medium", "challenging", "any"].index(finder_state.get("reading_level", "easy")),
                key="finder_reading_level",
            )
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("Back", use_container_width=True):
                    st.session_state["finder_step"] = 3
                    st.rerun()
            with col2:
                if st.button("Show my book picks", type="primary", use_container_width=True):
                    finder_state["reading_level"] = reading_choice
                    st.session_state["finder_step"] = 5
                    st.rerun()

    preferences = build_student_recommendation_preferences(profile, finder_state, learning_profile)

    if finder_step >= 5:
        render_status_tip(
            "Your reading recipe",
            f"Grade {preferences['grade']} · {preferences['book_type'].title()} books · {preferences['length_type']} length · {preferences['reading_level']} reading",
        )
        if learning_profile.get("interest_topics") or learning_profile.get("preferred_genres"):
            profile_boost_bits = [
                *learning_profile.get("interest_topics", [])[:2],
                *learning_profile.get("preferred_genres", [])[:1],
            ]
            if profile_boost_bits:
                st.caption(f"Profile boost: StoryShelf is also using your recent interests like {', '.join(profile_boost_bits)}.")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("Change my answers", use_container_width=True):
                st.session_state["finder_step"] = 1
                st.rerun()
        with col2:
            st.button("Keep these choices", disabled=True, use_container_width=True)
        recommendation_signature = (
            int(user["id"]),
            tuple(sorted((str(key), str(value)) for key, value in preferences.items())),
        )
        refreshed_recommendations = False
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
            refreshed_recommendations = True
        st.session_state["student_profile"] = {
            "name": profile["full_name"],
            "grade": profile["class_grade"],
            "preferred_language": profile.get("preferred_language", ""),
            "favorite_topics": profile.get("favorite_topics", ""),
            "reading_level": profile.get("reading_level", ""),
        }
        if refreshed_recommendations:
            st.session_state["latest_lesson"] = None
            st.session_state["feedback_saved"] = False
            st.session_state["selected_book_id"] = None
            st.session_state["last_quiz_result"] = None
            st.session_state["quiz_saved"] = False

        if not recommendation_records:
            st.warning("No close match yet. Try broader choices such as Any, or use fewer topic words.")
        else:
            render_chat_bubble("Here are a few books that look like a good match. Save one, mark one as read, or jump straight into a lesson.")

    recommended_books = st.session_state.get("recommended_books", [])
    if not recommended_books:
        render_empty_state("Your next shelf is waiting", "Finish the guided choices above and the app will show 3 to 5 book recommendations.", "✨")
        return

    student_book_statuses = fetch_saved_book_statuses_for_user(DB_CONFIG, int(user["id"]))
    render_section_heading("Your book matches", "These cards are arranged from strongest match to lighter matches.")
    recommendation_df = pd.DataFrame(recommended_books)
    for _, row in recommendation_df.iterrows():
        book_id = int(row["id"])
        render_recommendation_card(row)
        status = student_book_statuses.get(book_id, {})
        col1, col2, col3 = st.columns(3)
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
        with col3:
            if st.button("Read with this book", key=f"use_book_{book_id}", type="primary", use_container_width=True):
                st.session_state["selected_book_id"] = book_id
                set_current_page(STUDENT_LEARN_PAGE)
                st.rerun()

    options = {book["id"]: book_label(book) for book in recommended_books}
    with st.container(border=True):
        render_section_heading("Keep one book ready", "Choose one book to carry into Learn whenever you are ready.")
        selected_book_id = st.selectbox(
            "Pick a book to continue",
            options=list(options.keys()),
            format_func=lambda value: options[value],
            key="finder_selected_book_id",
        )
        st.session_state["selected_book_id"] = selected_book_id
        st.success("Next step: open Learn to turn this story into a lesson and quiz.")


def story_learning_page() -> None:
    user = enforce_role({"student"})
    if not user:
        return
    render_student_journey_header(
        user=user,
        current_page=STUDENT_LEARN_PAGE,
        title="Learn",
        body="Turn a selected book into a guided learning sequence with teaching, reflection, practice, and a final pass check without losing your place.",
        kicker="Lesson builder",
    )
    books_df = fetch_all_books(DB_CONFIG)
    book_lookup = build_book_lookup(books_df)
    if books_df.empty:
        render_empty_state("No books are ready yet", "The catalog needs to be uploaded before story-based lessons can begin.", "🧩")
        return

    profile = require_student_profile()
    if not profile:
        return
    student_dashboard = fetch_student_dashboard_data_for_user(DB_CONFIG, int(user["id"]))
    learning_profile = student_dashboard.get("learning_profile", {})

    recommended_books = [
        book for book in st.session_state.get("recommended_books", [])
        if int(book.get("id", -1)) in book_lookup
    ]
    default_book_id = st.session_state.get("selected_book_id")
    if not default_book_id:
        persisted_resume_sequence = fetch_latest_lesson_sequence_for_user(DB_CONFIG, int(user["id"]))
        if persisted_resume_sequence and persisted_resume_sequence.get("book_id"):
            default_book_id = int(persisted_resume_sequence["book_id"])
            st.session_state["selected_book_id"] = default_book_id
    recommended_ids = [book["id"] for book in recommended_books]

    if recommended_ids:
        selectable_ids = recommended_ids
        help_text = "You are using books from the current recommendation session."
    else:
        selectable_ids = books_df["id"].tolist()
        help_text = "Choose a saved or recommended book first if you want a smoother learning journey."

    render_status_tip("Book source", help_text)
    if not recommended_ids and not st.session_state.get("selected_book_id"):
        render_empty_state("No lesson yet", "Pick a book from Discover Books or My Books first, then come back here to build a lesson.", "🧠")
        if st.button("Discover a Book", key="learn_empty_discover", type="primary", use_container_width=True):
            set_current_page(STUDENT_DISCOVER_PAGE)
            st.rerun()
        return

    left_col, right_col = st.columns([1.15, 1])
    with left_col:
        render_section_heading("Choose your book", "Start with one book, then connect it to a school concept.")
        selected_book_id = st.selectbox(
            "Choose a book",
            options=selectable_ids,
            index=selectable_ids.index(default_book_id) if default_book_id in selectable_ids else 0,
            format_func=lambda value: book_label(book_lookup.get(value, {})),
            key="story_learning_book_id",
        )
    st.session_state["selected_book_id"] = selected_book_id

    book = book_lookup.get(selected_book_id) or fetch_book_by_id(DB_CONFIG, selected_book_id)
    if not book:
        st.error("The selected book could not be loaded.")
        return

    restore_latest_sequence_state(int(user["id"]), int(selected_book_id), book, profile, learning_profile)

    with right_col:
        render_book_snapshot(book, "Selected book")

    render_chat_bubble(f"Nice choice, {profile['full_name']}. Pick a subject and concept, then move through Learn, Reflect, Practice, and Quiz.")
    with st.container(border=True):
        render_section_heading("Build the learning sequence", "Choose the subject first, then decide what you want to learn.")
        subject = st.selectbox("Which subject do you want to learn?", ["Math", "Science", "English", "Social Science", "Values"], key="story_learning_subject")
        concept_suggestions = suggest_concepts(book, subject)
        st.info("Possible concept ideas: " + ", ".join(concept_suggestions))
        quick_pick = st.selectbox(
            "Choose a suggested concept if you want",
            options=["I want to type my own concept"] + concept_suggestions,
            key="story_learning_quick_pick",
        )
        concept = st.text_input("Which concept do you want to learn?", placeholder=concept_suggestions[0], key="story_learning_concept")
        selected_concept = resolve_final_concept(concept, quick_pick, concept_suggestions)
        if selected_concept:
            st.caption(f"Final concept: {selected_concept}")
        adaptive_summary = []
        if profile.get("reading_level"):
            adaptive_summary.append(f"{profile['reading_level']} reading")
        if learning_profile.get("quiz_band"):
            adaptive_summary.append(f"{learning_profile['quiz_band']} quiz path")
        if learning_profile.get("weak_concepts"):
            adaptive_summary.append(f"extra support for {', '.join(learning_profile['weak_concepts'][:2])}")
        elif learning_profile.get("strongest_concepts"):
            adaptive_summary.append(f"builds on {', '.join(learning_profile['strongest_concepts'][:2])}")
        if adaptive_summary:
            st.caption("Adaptive lesson mode: " + " · ".join(adaptive_summary))

    if st.button("Create Learning Sequence", type="primary", use_container_width=True):
        with st.spinner("Building your learning sequence..."):
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

            sequence = generate_learning_sequence(
                book=book,
                subject=subject,
                concept=selected_concept,
                grade=profile["class_grade"],
                student_context={
                    "reading_level": profile.get("reading_level", ""),
                    "quiz_band": learning_profile.get("quiz_band", ""),
                    "strongest_concepts": learning_profile.get("strongest_concepts", []),
                    "weak_concepts": learning_profile.get("weak_concepts", []),
                },
            )

        lesson_text = sequence.get("sequence_text") or lesson_sections_to_text(sequence.get("teach_sections", []))
        log_selected_book(DB_CONFIG, session_id, selected_book_id, student_id=int(user["id"]))
        lesson_log_id = log_generated_lesson(
            DB_CONFIG,
            student_id=int(user["id"]),
            session_id=session_id,
            book_id=selected_book_id,
            grade=profile["class_grade"],
            subject=subject,
            concept=sequence.get("chosen_concept", selected_concept),
            generated_lesson=lesson_text,
        )
        sequence_id = create_lesson_sequence(
            DB_CONFIG,
            lesson_id=lesson_log_id,
            user_id=int(user["id"]),
            book_id=selected_book_id,
            subject=subject,
            concept=sequence.get("chosen_concept", selected_concept),
            fit_level=sequence.get("fit_result", {}).get("level", ""),
            lesson_content=lesson_text,
            reflect_question=(sequence.get("reflect_question") or {}).get("prompt"),
            activity_prompt=(sequence.get("activity") or {}).get("prompt"),
            quiz_payload=sequence.get("quiz_questions", []),
        )
        st.session_state["latest_lesson"] = {
            "book_id": selected_book_id,
            "subject": subject,
            "concept": sequence.get("chosen_concept", selected_concept),
            "requested_concept": selected_concept,
            "grade": profile["class_grade"],
            "generated_lesson": lesson_text,
            "warning": sequence.get("warning", ""),
            "sections": sequence.get("teach_sections", []),
            "teach_sections": sequence.get("teach_sections", []),
            "fit_result": sequence.get("fit_result", {}),
            "lesson_log_id": lesson_log_id,
            "sequence_id": sequence_id,
            "reflect_question": sequence.get("reflect_question"),
            "reflect_answer": "",
            "reflect_feedback": None,
            "activity": sequence.get("activity"),
            "activity_answer": "",
            "activity_feedback": None,
            "quiz_questions": sequence.get("quiz_questions", []),
            "quiz_result": None,
            "quiz_attempts": [],
            "retry_count": 0,
            "passed": False,
            "mode": sequence.get("mode", "lesson"),
            "adaptive_profile": sequence.get("adaptive_profile", {}),
        }
        st.session_state["feedback_saved"] = False
        st.session_state["last_quiz_result"] = None
        st.session_state["quiz_saved"] = False
        st.session_state["restored_sequence_id"] = sequence_id
        render_chat_bubble("Your learning sequence is ready below. Start at Stage 1 and work your way forward.")

    latest_lesson = st.session_state.get("latest_lesson")
    if (
        latest_lesson
        and latest_lesson.get("book_id") == selected_book_id
        and latest_lesson.get("subject") == subject
        and latest_lesson.get("requested_concept") == selected_concept
    ):
        lesson_mode = latest_lesson.get("mode", "lesson")
        fit_level = latest_lesson.get("fit_result", {}).get("level")
        if lesson_mode == "fit_warning":
            render_section_heading("Try a better concept", "This concept does not fit the book well enough for a full learning sequence yet.")
        else:
            render_section_heading("Your learning sequence", "Work through each stage in order to build understanding step by step.")
        st.write(f"**Lesson concept:** {latest_lesson.get('concept', selected_concept)}")
        adaptive_profile = latest_lesson.get("adaptive_profile", {})
        if adaptive_profile:
            support_mode = str(adaptive_profile.get("support_mode", "balanced")).replace("_", " ")
            if support_mode == "scaffolded":
                st.info("This lesson is using extra support mode so each step stays short and clear.")
            elif support_mode == "stretch":
                st.info("This lesson is using stretch mode so you can explain your thinking a little more deeply.")

        if latest_lesson["warning"]:
            st.warning(latest_lesson["warning"])
        elif fit_level == "medium":
            st.info("This concept is a good match, so the sequence uses the clearest ideas from the book.")
        elif fit_level == "weak":
            st.info("This is a lighter match, so the sequence keeps the learning simple and close to the title and abstract.")
        elif not latest_lesson.get("fit_result", {}).get("is_strong", True):
            suggested = latest_lesson.get("fit_result", {}).get("suggested_concepts", [])
            if suggested:
                st.info("Better concepts to try: " + ", ".join(suggested))

        stage_index = 1
        if latest_lesson.get("reflect_feedback"):
            stage_index = 2
        if latest_lesson.get("activity_feedback"):
            stage_index = 3
        if latest_lesson.get("quiz_questions") and lesson_mode != "fit_warning":
            stage_index = 4
        if latest_lesson.get("quiz_result"):
            stage_index = 5
        render_progress_steps(["Learn", "Reflect", "Practice", "Quiz", "Result"], stage_index)

        render_section_heading("Stage 1: Learn", "Start with the teaching and examples.")
        with st.container(border=True):
            render_lesson_sections(latest_lesson.get("teach_sections", latest_lesson["sections"]))

        if lesson_mode != "fit_warning":
            st.caption("This learning sequence can still be reviewed by an admin before wider classroom use.")

        reflect_question = latest_lesson.get("reflect_question")
        if lesson_mode != "fit_warning" and reflect_question:
            render_section_heading("Stage 2: Reflect", "Answer one short question to show what you understood.")
            with st.container(border=True):
                st.write(reflect_question["prompt"])
                with st.form(f"reflect_form_{latest_lesson['lesson_log_id']}"):
                    reflect_answer = st.text_area(
                        "Your answer",
                        value=latest_lesson.get("reflect_answer", ""),
                        placeholder="Write 2 or 3 simple sentences.",
                    )
                    reflect_submitted = st.form_submit_button("Get feedback", type="primary", use_container_width=True)
                if reflect_submitted:
                    latest_lesson["reflect_answer"] = reflect_answer
                    latest_lesson["reflect_feedback"] = evaluate_open_ended_feedback(
                        book,
                        subject,
                        latest_lesson.get("concept", selected_concept),
                        profile["class_grade"],
                        latest_lesson.get("fit_result", {}),
                        reflect_answer,
                        latest_lesson.get("adaptive_profile", {}),
                    )
                    if latest_lesson.get("sequence_id"):
                        update_lesson_sequence(
                            DB_CONFIG,
                            int(latest_lesson["sequence_id"]),
                            reflect_answer=reflect_answer,
                            reflect_feedback=latest_lesson["reflect_feedback"],
                            status="reflect_done",
                        )
                    st.session_state["latest_lesson"] = latest_lesson
                    st.rerun()

            if latest_lesson.get("reflect_feedback"):
                feedback = latest_lesson["reflect_feedback"]
                with st.container(border=True):
                    st.write(f"**What is correct:** {feedback['what_is_correct']}")
                    st.write(f"**What is missing:** {feedback['what_is_missing']}")
                    st.write(f"**Hint:** {feedback['hint']}")
                    st.success(feedback["encouragement"])

        activity = latest_lesson.get("activity")
        if lesson_mode != "fit_warning" and activity:
            render_section_heading("Stage 3: Practice", "Use the concept yourself in one short activity.")
            with st.container(border=True):
                st.write(activity["prompt"])
                with st.form(f"activity_form_{latest_lesson['lesson_log_id']}"):
                    activity_answer = st.text_area(
                        "Your activity answer",
                        value=latest_lesson.get("activity_answer", ""),
                        placeholder="Use the book context to show your thinking.",
                    )
                    activity_submitted = st.form_submit_button("Check activity", type="primary", use_container_width=True)
                if activity_submitted:
                    latest_lesson["activity_answer"] = activity_answer
                    latest_lesson["activity_feedback"] = evaluate_activity_feedback(
                        book,
                        subject,
                        latest_lesson.get("concept", selected_concept),
                        profile["class_grade"],
                        latest_lesson.get("fit_result", {}),
                        activity_answer,
                        latest_lesson.get("adaptive_profile", {}),
                    )
                    if latest_lesson.get("sequence_id"):
                        update_lesson_sequence(
                            DB_CONFIG,
                            int(latest_lesson["sequence_id"]),
                            activity_answer=activity_answer,
                            activity_feedback=latest_lesson["activity_feedback"],
                            status="practice_done",
                        )
                    st.session_state["latest_lesson"] = latest_lesson
                    st.rerun()

            if latest_lesson.get("activity_feedback"):
                feedback = latest_lesson["activity_feedback"]
                with st.container(border=True):
                    st.write(f"**What is correct:** {feedback['what_is_correct']}")
                    st.write(f"**What can improve:** {feedback['what_can_improve']}")
                    st.write(f"**Hint:** {feedback['hint']}")
                    st.success(feedback["encouragement"])

        quiz_questions = latest_lesson.get("quiz_questions", [])
        if quiz_questions and lesson_mode != "fit_warning":
            render_section_heading("Stage 4: Quiz", "Finish the final check to see whether you pass this learning sequence.")
            pass_threshold = quiz_questions[0].get("pass_threshold", 60.0) if quiz_questions else 60.0
            st.caption(f"Pass target: {pass_threshold:.0f}%")
            with st.container(border=True):
                with st.form(f"lesson_quiz_form_{latest_lesson['lesson_log_id']}_{latest_lesson.get('retry_count', 0)}"):
                    quiz_answers: list[str] = []
                    for index, question in enumerate(quiz_questions, start=1):
                        label = f"{index}. {question['question']}"
                        if question.get("question_type") == "short":
                            quiz_answers.append(
                                st.text_input(
                                    label,
                                    key=f"quiz_short_{latest_lesson['lesson_log_id']}_{latest_lesson.get('retry_count', 0)}_{index}",
                                )
                            )
                        else:
                            quiz_answers.append(
                                st.radio(
                                    label,
                                    question["options"],
                                    key=f"quiz_mcq_{latest_lesson['lesson_log_id']}_{latest_lesson.get('retry_count', 0)}_{index}",
                                )
                            )
                    quiz_submitted = st.form_submit_button("Finish quiz", type="primary", use_container_width=True)

            if quiz_submitted:
                quiz_result = score_sequence_quiz(quiz_questions, quiz_answers)
                latest_lesson["quiz_result"] = quiz_result
                latest_lesson["quiz_attempts"] = latest_lesson.get("quiz_attempts", []) + [quiz_result]
                latest_lesson["passed"] = bool(quiz_result.get("passed"))
                if latest_lesson.get("sequence_id"):
                    update_lesson_sequence(
                        DB_CONFIG,
                        int(latest_lesson["sequence_id"]),
                        quiz_payload=quiz_questions,
                        quiz_answers=quiz_answers,
                        quiz_score=quiz_result["score"],
                        total_questions=quiz_result["total_questions"],
                        passed=bool(quiz_result.get("passed")),
                        retry_count=int(latest_lesson.get("retry_count", 0)),
                        status="passed" if quiz_result.get("passed") else "quiz_failed",
                    )
                    log_lesson_sequence_attempt(
                        DB_CONFIG,
                        sequence_id=int(latest_lesson["sequence_id"]),
                        attempt_number=int(latest_lesson.get("retry_count", 0)) + 1,
                        reflect_answer=latest_lesson.get("reflect_answer"),
                        reflect_feedback=latest_lesson.get("reflect_feedback"),
                        activity_answer=latest_lesson.get("activity_answer"),
                        activity_feedback=latest_lesson.get("activity_feedback"),
                        quiz_payload=quiz_questions,
                        quiz_answers=quiz_answers,
                        quiz_score=quiz_result["score"],
                        total_questions=quiz_result["total_questions"],
                        passed=bool(quiz_result.get("passed")),
                    )
                st.session_state["latest_lesson"] = latest_lesson
                st.session_state["last_quiz_result"] = quiz_result
                save_quiz_result(
                    DB_CONFIG,
                    student_id=int(user["id"]),
                    book_id=selected_book_id,
                    lesson_log_id=latest_lesson.get("lesson_log_id"),
                    score=quiz_result["score"],
                    total_questions=quiz_result["total_questions"],
                    answers=quiz_result["results"],
                )
                st.rerun()
        elif lesson_mode != "fit_warning":
            render_empty_state("No quiz yet", "Try a stronger concept match to unlock a more complete quiz for this book.", "📝")

        if latest_lesson.get("quiz_result") and lesson_mode != "fit_warning":
            result = latest_lesson["quiz_result"]
            render_section_heading("Stage 5: Result", "See your score, review the answers, and retry if needed.")
            if result.get("passed"):
                st.success(f"You passed: {result['score']} / {result['total_questions']} ({result['percentage']}%)")
            else:
                st.warning(f"Not passed yet: {result['score']} / {result['total_questions']} ({result['percentage']}%)")
            st.caption(f"Pass target for this quiz: {result.get('pass_threshold', 60.0):.0f}%")
            st.write(result["summary"])
            st.write(result["review_summary"])
            for item in result["results"]:
                icon = "Correct" if item["is_correct"] else "Try again"
                with st.expander(f"{icon}: {item['question']}", expanded=not item["is_correct"]):
                    st.write(f"**Your answer:** {item['selected_answer'] or 'No answer'}")
                    st.write(f"**Model answer:** {item['correct_answer']}")
                    st.write(item["feedback"])

            if not result.get("passed"):
                if st.button("Retry with a simpler quiz", key=f"retry_quiz_{latest_lesson['lesson_log_id']}", use_container_width=True):
                    latest_lesson["retry_count"] = int(latest_lesson.get("retry_count", 0)) + 1
                    latest_lesson["quiz_questions"] = generate_sequence_quiz(
                        book,
                        subject,
                        latest_lesson.get("concept", selected_concept),
                        profile["class_grade"],
                        latest_lesson.get("fit_result", {}),
                        latest_lesson.get("adaptive_profile", {}),
                        simplified=True,
                    )
                    latest_lesson["quiz_result"] = None
                    latest_lesson["passed"] = False
                    if latest_lesson.get("sequence_id"):
                        update_lesson_sequence(
                            DB_CONFIG,
                            int(latest_lesson["sequence_id"]),
                            quiz_payload=latest_lesson["quiz_questions"],
                            quiz_answers=[],
                            quiz_score=None,
                            total_questions=None,
                            passed=False,
                            retry_count=int(latest_lesson["retry_count"]),
                            status="quiz_retry",
                            clear_quiz_result=True,
                        )
                    st.session_state["latest_lesson"] = latest_lesson
                    st.session_state["last_quiz_result"] = None
                    st.rerun()

        render_section_heading("Quick feedback", "A little feedback helps improve the next learning sequence.")
        if st.session_state.get("feedback_saved"):
            st.success("Thanks for the feedback.")

        with st.container(border=True):
            with st.form("feedback_form"):
                recommendation_useful = st.radio("Was the recommendation useful?", ["Yes", "No"], horizontal=True)
                lesson_understandable = st.radio("Was the lesson understandable?", ["Yes", "No"], horizontal=True)
                rating = st.slider("Overall rating", min_value=1, max_value=5, value=4)
                comment = st.text_input("Optional comment")
                feedback_submitted = st.form_submit_button("Send Feedback", type="primary", use_container_width=True)

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


def admin_dashboard_page() -> None:
    if not enforce_role({"admin"}):
        return
    render_brand_header("admin")
    render_hero(
        "Dashboard",
        "See library activity, recommendation sessions, catalog health, and feedback trends in one calm workspace.",
        kicker="Admin space",
    )

    metrics = fetch_dashboard_metrics(DB_CONFIG)
    render_metric_grid(
        [
            {"label": "Total uploads", "value": str(metrics["total_uploads"]), "note": "Catalog imports completed"},
            {"label": "Total books", "value": str(metrics["total_books"]), "note": "Books available in the catalog"},
            {"label": "Recommendation sessions", "value": str(metrics["total_recommendation_sessions"]), "note": "Student reading journeys launched"},
            {
                "label": "Average feedback",
                "value": f"{metrics['average_feedback_rating']:.2f}" if metrics["average_feedback_rating"] is not None else "No ratings yet",
                "note": "Student satisfaction snapshot",
            },
        ]
    )
    render_metric_grid(
        [
            {"label": "Guided lessons started", "value": str(metrics["guided_lessons_started"]), "note": "Learning sequences students began"},
            {"label": "Guided lessons completed", "value": str(metrics["guided_lessons_completed"]), "note": "Sequences that reached a scored quiz"},
            {
                "label": "Guided pass rate",
                "value": f"{metrics['guided_pass_rate']}%" if metrics["guided_pass_rate"] is not None else "No quiz results yet",
                "note": "Share of completed sequences that passed",
            },
            {"label": "Needs support", "value": str(metrics["support_needed_count"]), "note": "Sequences that were retried or did not pass yet"},
        ]
    )
    col1, col2 = st.columns(2)
    with col1:
        render_status_tip("Catalog focus", "Keep the book catalog fresh so recommendations stay meaningful for students.")
    with col2:
        render_status_tip("Admin focus", "Review lesson quality, watch student activity, and keep user access tidy.")
    attention_col1, attention_col2, attention_col3 = st.columns(3)
    with attention_col1:
        render_status_tip(
            "Needs attention",
            (
                f"{metrics['support_needed_count']} learning sequences need another try."
                if metrics["support_needed_count"] > 0
                else "No learning support hotspots are showing right now."
            ),
        )
    with attention_col2:
        render_status_tip(
            "Catalog status",
            "Catalog is ready for students." if metrics["total_books"] > 0 else "Upload a catalog so students can begin discovering books.",
        )
    with attention_col3:
        render_status_tip(
            "Feedback signal",
            (
                f"Average student rating is {metrics['average_feedback_rating']:.2f} out of 5."
                if metrics["average_feedback_rating"] is not None
                else "Feedback will appear after students finish lessons."
            ),
        )

    render_section_heading("Student interest signals", "See what students care about most so future catalog and lesson choices stay relevant.")
    interest_col1, interest_col2, interest_col3 = st.columns(3)
    with interest_col1:
        if metrics["remembered_topics"].empty:
            render_empty_state("No remembered topics yet", "StoryShelf will start remembering student interests after discovery and reading activity grows.", "📚")
        else:
            with st.container(border=True):
                st.caption("Remembered topics")
                st.dataframe(metrics["remembered_topics"], use_container_width=True, hide_index=True)
    with interest_col2:
        if metrics["recommendation_themes"].empty:
            render_empty_state("No recommendation themes yet", "Recommendation requests will appear here after students start discovering books.", "💬")
        else:
            with st.container(border=True):
                st.caption("Requested themes")
                st.dataframe(metrics["recommendation_themes"], use_container_width=True, hide_index=True)
    with interest_col3:
        if metrics["top_genres"].empty:
            render_empty_state("No genre trends yet", "Genre interest appears once students start selecting books.", "🏷️")
        else:
            with st.container(border=True):
                st.caption("Top genres")
                st.dataframe(metrics["top_genres"], use_container_width=True, hide_index=True)

    render_section_heading("Most selected books", "These are the titles students are choosing most often.")
    most_selected_books = metrics["most_selected_books"]
    if most_selected_books.empty:
        render_empty_state("No book selections yet", "Popular titles will appear here once students start choosing books.", "📈")
    else:
        with st.container(border=True):
            st.dataframe(most_selected_books, use_container_width=True, hide_index=True)


    render_section_heading("Most attempted concepts", "See which ideas students practice most often in guided learning.")
    if metrics["most_attempted_concepts"].empty:
        render_empty_state("No guided lessons yet", "Concept activity will appear here once students begin guided learning sequences.", "🧠")
    else:
        with st.container(border=True):
            st.dataframe(metrics["most_attempted_concepts"], use_container_width=True, hide_index=True)

    render_section_heading("Learning effectiveness", "These views show which books and concepts are turning into successful learning.")
    effectiveness_col1, effectiveness_col2 = st.columns(2)
    with effectiveness_col1:
        if metrics["lesson_effectiveness_books"].empty:
            render_empty_state("No lesson conversion data yet", "Books that lead to lessons and passed quizzes will appear here.", "🧠")
        else:
            with st.container(border=True):
                st.caption("Books leading to lessons")
                st.dataframe(metrics["lesson_effectiveness_books"], use_container_width=True, hide_index=True)
    with effectiveness_col2:
        if metrics["concept_effectiveness"].empty:
            render_empty_state("No concept effectiveness data yet", "Concept pass trends will appear here after guided learning begins.", "✅")
        else:
            with st.container(border=True):
                st.caption("Concept pass trends")
                st.dataframe(metrics["concept_effectiveness"], use_container_width=True, hide_index=True)

    render_section_heading("Support watch", "Use these views to spot where students need extra help.")
    support_col1, support_col2 = st.columns(2)
    with support_col1:
        if metrics["subject_scores"].empty:
            render_empty_state("No subject score trends yet", "Average subject scores will appear here after quiz results are saved.", "📊")
        else:
            with st.container(border=True):
                st.caption("Average score by subject")
                st.dataframe(metrics["subject_scores"], use_container_width=True, hide_index=True)
    with support_col2:
        if metrics["struggling_concepts"].empty:
            render_empty_state("No support hotspots yet", "Concepts that need retries or extra support will appear here.", "🛟")
        else:
            with st.container(border=True):
                st.caption("Concepts needing support")
                st.dataframe(metrics["struggling_concepts"], use_container_width=True, hide_index=True)

    render_section_heading("Mastery snapshot", "See how concept mastery is building across the student group.")
    if metrics["mastery_bands"].empty:
        render_empty_state("No mastery records yet", "Mastery levels will appear once students complete quizzes.", "🌱")
    else:
        with st.container(border=True):
            st.dataframe(metrics["mastery_bands"], use_container_width=True, hide_index=True)


def admin_user_management_page() -> None:
    current_admin = enforce_role({"admin"})
    if not current_admin:
        return

    render_brand_header("admin")
    render_hero(
        "User Management",
        "Create admin accounts, review users, change roles, and control who can enter the app.",
        kicker="Admin space",
    )

    render_section_heading("Create an admin account", "Use this for trusted school staff who need catalog, dashboard, and lesson review access.")
    with st.container(border=True):
        with st.form("create_staff_form"):
            full_name = st.text_input("Full name")
            email = st.text_input("Email")
            password = st.text_input("Temporary password", type="password")
            create_submitted = st.form_submit_button("Create Admin Account", type="primary", use_container_width=True)

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
                    try:
                        create_user(DB_CONFIG, full_name=full_name, email=email, password=password, role="admin")
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.success("Admin account created.")
                        st.rerun()

    users_df = fetch_all_users(DB_CONFIG)
    render_section_heading("All users", "Review the full list before making access changes.")
    if users_df.empty:
        render_empty_state("No users yet", "Create the first admin account or let students sign up to start building the user list.", "👥")
        return

    display_df = users_df.copy()
    display_df["role"] = display_df["role"].apply(lambda value: normalize_role(str(value)).title())
    display_df["is_active"] = display_df["is_active"].apply(lambda value: "Active" if bool(value) else "Inactive")
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    render_section_heading("Manage existing users", "Open a user card to update access or account status.")
    for _, row in users_df.iterrows():
        user_id = int(row["id"])
        is_self = user_id == int(current_admin["id"])
        role_value = normalize_role(str(row["role"]))
        is_active = bool(row["is_active"])
        with st.expander(f"{row['full_name']} · {row['email']} · {role_value.title()}", expanded=False):
            st.write(f"**User ID:** {user_id}")
            st.write(f"**Created at:** {row['created_at']}")
            if is_self:
                st.warning("This is your current admin account. You cannot change your own admin access here.")

            with st.form(f"user_manage_{user_id}"):
                new_role = st.selectbox(
                    "Role",
                    ["student", "admin"],
                    index=["student", "admin"].index(normalize_role(role_value) if normalize_role(role_value) in {"student", "admin"} else "student"),
                    key=f"role_select_{user_id}",
                )
                new_active = st.checkbox("Account is active", value=is_active, key=f"active_toggle_{user_id}")
                confirm_change = st.checkbox("I understand this will change this user's access", key=f"confirm_change_{user_id}")
                save_changes = st.form_submit_button("Save", use_container_width=True)

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
                        st.info("No changes to save.")


def admin_lesson_review_page() -> None:
    if not enforce_role({"admin"}):
        return
    render_brand_header("admin")
    render_hero(
        "Lesson Review",
        "Review the generated lesson, edit the final wording, save it, and export it for classroom use.",
        kicker="Admin space",
    )

    books_df = fetch_all_books(DB_CONFIG)
    book_lookup = build_book_lookup(books_df)
    if books_df.empty:
        render_empty_state("No books are ready for review", "Upload a catalog first so lessons can be reviewed and saved.", "📝")
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
        render_empty_state("No lesson to review yet", "Create a lesson from Learn first, then come here to review and save it.", "🪄")
        return

    render_section_heading(book["title"] or "Untitled Book", "Review the source book first, then compare the generated lesson with the edited version.")
    render_book_snapshot(book, "Book details")

    if lesson_context.get("warning"):
        st.warning(lesson_context["warning"])

    subject = lesson_context["subject"]
    concept = lesson_context["concept"]
    grade = lesson_context["grade"]
    generated_lesson = lesson_context["generated_lesson"]

    with st.container(border=True):
        render_section_heading("Generated lesson", "This is the lesson exactly as the app produced it.")
        st.text_area("Generated lesson text", value=generated_lesson, height=280, disabled=True)

    default_review = saved_review["reviewed_lesson"] if saved_review else generated_lesson
    with st.container(border=True):
        render_section_heading("Edited version", "Refine the wording, then save or download the polished lesson.")
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
            st.success("Reviewed lesson saved.")
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

    role = normalize_role(str(user.get("role", "student")))
    if role not in ALLOWED_ROLES:
        st.error("This account needs support. Please contact an administrator.")
        logout_user()
        st.rerun()
        return
    if not bool(user.get("is_active", True)):
        st.error("This account is inactive. Please contact an administrator.")
        logout_user()
        st.rerun()
        return

    if role == "admin":
        page = render_sidebar_navigation(role, str(user.get("full_name", "User")))
        if st.sidebar.button("Log Out", use_container_width=True):
            logout_user()
            st.rerun()
            return
    else:
        page = st.session_state.get("nav_page", default_page_for_role(role))

    allowed_pages = {
        "student": {STUDENT_DISCOVER_PAGE, STUDENT_BOOKS_PAGE, STUDENT_LEARN_PAGE, STUDENT_PROGRESS_PAGE},
        "admin": {ADMIN_DASHBOARD_PAGE, ADMIN_USERS_PAGE, ADMIN_CATALOG_PAGE, ADMIN_LESSON_REVIEW_PAGE},
    }
    if page not in allowed_pages.get(role, set()):
        st.error("That page is not available for your role.")
        set_current_page(default_page_for_role(role))
        st.rerun()
        return

    if page == STUDENT_PROGRESS_PAGE:
        student_dashboard_page()
    elif page == STUDENT_DISCOVER_PAGE:
        student_page()
    elif page == STUDENT_BOOKS_PAGE:
        my_books_page()
    elif page == ADMIN_CATALOG_PAGE:
        admin_page()
    elif page == STUDENT_LEARN_PAGE:
        story_learning_page()
    elif page == ADMIN_DASHBOARD_PAGE:
        admin_dashboard_page()
    elif page == ADMIN_USERS_PAGE:
        admin_user_management_page()
    elif page == ADMIN_LESSON_REVIEW_PAGE:
        admin_lesson_review_page()


if __name__ == "__main__":
    main()
