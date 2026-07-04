from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import re
from typing import Any, Iterator, Sequence

import pandas as pd

from src.config import DatabaseConfig

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional for local SQLite-only runs
    psycopg = None
    dict_row = None

BOOK_COLUMNS = [
    "accession_no",
    "call_no",
    "location",
    "item_type",
    "isbn",
    "publisher",
    "pages",
    "place",
    "author",
    "title",
    "abstract",
    "gennote",
    "reading_level",
    "genre_tags",
    "subject_tags",
    "length_type",
]

BOOK_COLUMN_TYPES = {
    "accession_no": "TEXT",
    "call_no": "TEXT",
    "location": "TEXT",
    "item_type": "TEXT",
    "isbn": "TEXT",
    "publisher": "TEXT",
    "pages": "INTEGER",
    "place": "TEXT",
    "author": "TEXT",
    "title": "TEXT",
    "abstract": "TEXT",
    "gennote": "TEXT",
    "reading_level": "TEXT",
    "genre_tags": "TEXT",
    "subject_tags": "TEXT",
    "length_type": "TEXT",
}

REVIEWED_LESSON_COLUMN_TYPES = {
    "book_id": "INTEGER NOT NULL",
    "subject": "TEXT NOT NULL",
    "concept": "TEXT NOT NULL",
    "grade": "TEXT NOT NULL",
    "generated_lesson": "TEXT NOT NULL",
    "reviewed_lesson": "TEXT NOT NULL",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

RECOMMENDATION_SESSION_COLUMN_TYPES = {
    "student_id": "INTEGER",
    "grade": "TEXT",
    "preferences_json": "TEXT NOT NULL",
    "recommended_books_json": "TEXT NOT NULL",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

SELECTED_BOOK_COLUMN_TYPES = {
    "student_id": "INTEGER",
    "session_id": "INTEGER NOT NULL",
    "book_id": "INTEGER NOT NULL",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

GENERATED_LESSON_COLUMN_TYPES = {
    "student_id": "INTEGER",
    "session_id": "INTEGER",
    "book_id": "INTEGER NOT NULL",
    "grade": "TEXT",
    "subject": "TEXT NOT NULL",
    "concept": "TEXT NOT NULL",
    "generated_lesson": "TEXT NOT NULL",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

FEEDBACK_COLUMN_TYPES = {
    "student_id": "INTEGER",
    "session_id": "INTEGER",
    "recommendation_useful": "INTEGER NOT NULL",
    "lesson_understandable": "INTEGER NOT NULL",
    "story_help_learning": "INTEGER NOT NULL",
    "rating": "INTEGER NOT NULL",
    "comment": "TEXT",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

CATALOG_UPLOAD_COLUMN_TYPES = {
    "imported_count": "INTEGER NOT NULL",
    "columns_json": "TEXT NOT NULL",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

STUDENT_COLUMN_TYPES = {
    "name": "TEXT NOT NULL",
    "grade": "TEXT NOT NULL",
    "preferred_language": "TEXT",
    "favorite_topics": "TEXT",
    "reading_comfort_level": "TEXT",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

STUDENT_PROFILE_COLUMN_TYPES = {
    "student_id": "INTEGER NOT NULL UNIQUE",
    "name": "TEXT NOT NULL",
    "grade": "TEXT NOT NULL",
    "preferred_language": "TEXT",
    "favorite_topics": "TEXT",
    "reading_comfort_level": "TEXT",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

STUDENT_BOOK_COLUMN_TYPES = {
    "student_id": "INTEGER NOT NULL",
    "book_id": "INTEGER NOT NULL",
    "saved_for_later": "INTEGER NOT NULL DEFAULT 0",
    "marked_as_read": "INTEGER NOT NULL DEFAULT 0",
    "saved_at": "TIMESTAMP",
    "read_at": "TIMESTAMP",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

SAVED_BOOK_COLUMN_TYPES = {
    "student_id": "INTEGER NOT NULL",
    "book_id": "INTEGER NOT NULL",
    "saved_for_later": "INTEGER NOT NULL DEFAULT 0",
    "marked_as_read": "INTEGER NOT NULL DEFAULT 0",
    "saved_at": "TIMESTAMP",
    "read_at": "TIMESTAMP",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

QUIZ_RESULT_COLUMN_TYPES = {
    "student_id": "INTEGER NOT NULL",
    "book_id": "INTEGER NOT NULL",
    "lesson_log_id": "INTEGER",
    "score": "INTEGER NOT NULL",
    "total_questions": "INTEGER NOT NULL",
    "answers_json": "TEXT NOT NULL",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

READING_HISTORY_COLUMN_TYPES = {
    "student_id": "INTEGER",
    "book_id": "INTEGER",
    "activity_type": "TEXT NOT NULL",
    "activity_note": "TEXT",
    "lesson_log_id": "INTEGER",
    "quiz_result_id": "INTEGER",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

USER_COLUMN_TYPES = {
    "name": "TEXT",
    "email": "TEXT UNIQUE",
    "role": "TEXT",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}


def _id_column(config: DatabaseConfig) -> str:
    return "SERIAL PRIMARY KEY" if config.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _normalize_params(params: Sequence[Any] | None) -> tuple[Any, ...]:
    if params is None:
        return ()
    return tuple(params)


def _prepare_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value


def _prepare_params(params: Sequence[Any] | None) -> tuple[Any, ...]:
    return tuple(_prepare_value(value) for value in _normalize_params(params))


def _adapt_query(query: str, config: DatabaseConfig) -> str:
    return query if config.is_postgres else query.replace("%s", "?")


def _fetchall_dicts(cursor: Any, config: DatabaseConfig) -> list[dict[str, Any]]:
    rows = cursor.fetchall()
    if not rows:
        return []

    if config.is_postgres:
        return [dict(row) for row in rows]

    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in rows]


def _fetchone_dict(cursor: Any, config: DatabaseConfig) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None

    if config.is_postgres:
        return dict(row)

    columns = [column[0] for column in cursor.description]
    return dict(zip(columns, row, strict=False))


@contextmanager
def get_connection(config: DatabaseConfig) -> Iterator[Any]:
    if config.is_postgres:
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set, but psycopg is not installed.")
        conn = psycopg.connect(config.database_url, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    if not config.sqlite_path:
        raise RuntimeError("SQLite configuration is missing a database path.")

    config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute_query(
    config: DatabaseConfig,
    query: str,
    params: Sequence[Any] | None = None,
    *,
    many: bool = False,
    param_sets: Sequence[Sequence[Any]] | None = None,
) -> None:
    with get_connection(config) as conn:
        cursor = conn.cursor()
        adapted_query = _adapt_query(query, config)
        if many:
            if not param_sets:
                return
            cursor.executemany(adapted_query, [_prepare_params(item) for item in param_sets])
        else:
            cursor.execute(adapted_query, _prepare_params(params))


def fetch_all(config: DatabaseConfig, query: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    with get_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute(_adapt_query(query, config), _prepare_params(params))
        return _fetchall_dicts(cursor, config)


def fetch_one(config: DatabaseConfig, query: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
    with get_connection(config) as conn:
        cursor = conn.cursor()
        cursor.execute(_adapt_query(query, config), _prepare_params(params))
        return _fetchone_dict(cursor, config)


def insert_and_get_id(config: DatabaseConfig, query: str, params: Sequence[Any] | None = None) -> int:
    with get_connection(config) as conn:
        cursor = conn.cursor()
        adapted_query = _adapt_query(query, config)
        if config.is_sqlite:
            adapted_query = re.sub(r"\s+RETURNING\s+id\s*$", "", adapted_query, flags=re.IGNORECASE)
        cursor.execute(adapted_query, _prepare_params(params))
        if config.is_postgres:
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("Insert did not return an id.")
            return int(row["id"])
        return int(cursor.lastrowid)


def ensure_table_columns(config: DatabaseConfig, table_name: str, expected_columns: dict[str, str]) -> None:
    if config.is_postgres:
        rows = fetch_all(
            config,
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        existing_columns = {row["column_name"] for row in rows}
    else:
        rows = fetch_all(config, f"PRAGMA table_info({table_name})")
        existing_columns = {row["name"] for row in rows}

    for column, column_type in expected_columns.items():
        if column not in existing_columns:
            execute_query(config, f"ALTER TABLE {table_name} ADD COLUMN {column} {column_type}")


def _upsert_student_profile_shadow(
    config: DatabaseConfig,
    student_id: int,
    name: str,
    grade: str,
    preferred_language: str,
    favorite_topics: str,
    reading_comfort_level: str,
) -> None:
    execute_query(
        config,
        """
        INSERT INTO student_profiles (
            student_id, name, grade, preferred_language, favorite_topics, reading_comfort_level
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT(student_id) DO UPDATE SET
            name = EXCLUDED.name,
            grade = EXCLUDED.grade,
            preferred_language = EXCLUDED.preferred_language,
            favorite_topics = EXCLUDED.favorite_topics,
            reading_comfort_level = EXCLUDED.reading_comfort_level,
            updated_at = CURRENT_TIMESTAMP
        """,
        (student_id, name, grade, preferred_language, favorite_topics, reading_comfort_level),
    )


def _upsert_saved_book_shadow(
    config: DatabaseConfig,
    student_id: int,
    book_id: int,
    saved_for_later: int,
    marked_as_read: int,
) -> None:
    execute_query(
        config,
        """
        INSERT INTO saved_books (
            student_id, book_id, saved_for_later, marked_as_read, saved_at, read_at
        )
        VALUES (
            %s, %s, %s, %s,
            CASE WHEN %s = 1 THEN CURRENT_TIMESTAMP ELSE NULL END,
            CASE WHEN %s = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
        )
        ON CONFLICT(student_id, book_id) DO UPDATE SET
            saved_for_later = EXCLUDED.saved_for_later,
            marked_as_read = EXCLUDED.marked_as_read,
            saved_at = CASE
                WHEN EXCLUDED.saved_for_later = 1 THEN COALESCE(saved_books.saved_at, CURRENT_TIMESTAMP)
                ELSE NULL
            END,
            read_at = CASE
                WHEN EXCLUDED.marked_as_read = 1 THEN COALESCE(saved_books.read_at, CURRENT_TIMESTAMP)
                ELSE NULL
            END,
            updated_at = CURRENT_TIMESTAMP
        """,
        (student_id, book_id, saved_for_later, marked_as_read, saved_for_later, marked_as_read),
    )


def log_reading_history(
    config: DatabaseConfig,
    student_id: int | None,
    activity_type: str,
    activity_note: str,
    *,
    book_id: int | None = None,
    lesson_log_id: int | None = None,
    quiz_result_id: int | None = None,
) -> int:
    return insert_and_get_id(
        config,
        """
        INSERT INTO reading_history (
            student_id, book_id, activity_type, activity_note, lesson_log_id, quiz_result_id
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (student_id, book_id, activity_type, activity_note, lesson_log_id, quiz_result_id),
    )


def init_db(config: DatabaseConfig) -> None:
    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS users (
            id {_id_column(config)},
            name TEXT,
            email TEXT UNIQUE,
            role TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    ensure_table_columns(config, "users", USER_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS books (
            id {_id_column(config)},
            accession_no TEXT,
            call_no TEXT,
            location TEXT,
            item_type TEXT,
            isbn TEXT,
            publisher TEXT,
            pages INTEGER,
            place TEXT,
            author TEXT,
            title TEXT,
            abstract TEXT,
            gennote TEXT,
            reading_level TEXT,
            genre_tags TEXT,
            subject_tags TEXT,
            length_type TEXT
        )
        """,
    )
    ensure_table_columns(config, "books", BOOK_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS students (
            id {_id_column(config)},
            name TEXT NOT NULL,
            grade TEXT NOT NULL,
            preferred_language TEXT,
            favorite_topics TEXT,
            reading_comfort_level TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    ensure_table_columns(config, "students", STUDENT_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS student_profiles (
            id {_id_column(config)},
            student_id INTEGER NOT NULL UNIQUE,
            name TEXT NOT NULL,
            grade TEXT NOT NULL,
            preferred_language TEXT,
            favorite_topics TEXT,
            reading_comfort_level TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
        """,
    )
    ensure_table_columns(config, "student_profiles", STUDENT_PROFILE_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS recommendation_sessions (
            id {_id_column(config)},
            student_id INTEGER,
            grade TEXT,
            preferences_json TEXT NOT NULL,
            recommended_books_json TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
        """,
    )
    ensure_table_columns(config, "recommendation_sessions", RECOMMENDATION_SESSION_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS selected_books (
            id {_id_column(config)},
            student_id INTEGER,
            session_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (session_id) REFERENCES recommendation_sessions(id),
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
        """,
    )
    ensure_table_columns(config, "selected_books", SELECTED_BOOK_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS generated_lessons (
            id {_id_column(config)},
            student_id INTEGER,
            session_id INTEGER,
            book_id INTEGER NOT NULL,
            grade TEXT,
            subject TEXT NOT NULL,
            concept TEXT NOT NULL,
            generated_lesson TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (session_id) REFERENCES recommendation_sessions(id),
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
        """,
    )
    ensure_table_columns(config, "generated_lessons", GENERATED_LESSON_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS feedback (
            id {_id_column(config)},
            student_id INTEGER,
            session_id INTEGER,
            recommendation_useful INTEGER NOT NULL,
            lesson_understandable INTEGER NOT NULL,
            story_help_learning INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (session_id) REFERENCES recommendation_sessions(id)
        )
        """,
    )
    ensure_table_columns(config, "feedback", FEEDBACK_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS reviewed_lessons (
            id {_id_column(config)},
            book_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            concept TEXT NOT NULL,
            grade TEXT NOT NULL,
            generated_lesson TEXT NOT NULL,
            reviewed_lesson TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
        """,
    )
    ensure_table_columns(config, "reviewed_lessons", REVIEWED_LESSON_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS student_books (
            id {_id_column(config)},
            student_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            saved_for_later INTEGER NOT NULL DEFAULT 0,
            marked_as_read INTEGER NOT NULL DEFAULT 0,
            saved_at TIMESTAMP,
            read_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (book_id) REFERENCES books(id),
            UNIQUE(student_id, book_id)
        )
        """,
    )
    ensure_table_columns(config, "student_books", STUDENT_BOOK_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS saved_books (
            id {_id_column(config)},
            student_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            saved_for_later INTEGER NOT NULL DEFAULT 0,
            marked_as_read INTEGER NOT NULL DEFAULT 0,
            saved_at TIMESTAMP,
            read_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (book_id) REFERENCES books(id),
            UNIQUE(student_id, book_id)
        )
        """,
    )
    ensure_table_columns(config, "saved_books", SAVED_BOOK_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS quiz_results (
            id {_id_column(config)},
            student_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            lesson_log_id INTEGER,
            score INTEGER NOT NULL,
            total_questions INTEGER NOT NULL,
            answers_json TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (book_id) REFERENCES books(id),
            FOREIGN KEY (lesson_log_id) REFERENCES generated_lessons(id)
        )
        """,
    )
    ensure_table_columns(config, "quiz_results", QUIZ_RESULT_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS reading_history (
            id {_id_column(config)},
            student_id INTEGER,
            book_id INTEGER,
            activity_type TEXT NOT NULL,
            activity_note TEXT,
            lesson_log_id INTEGER,
            quiz_result_id INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (book_id) REFERENCES books(id),
            FOREIGN KEY (lesson_log_id) REFERENCES generated_lessons(id),
            FOREIGN KEY (quiz_result_id) REFERENCES quiz_results(id)
        )
        """,
    )
    ensure_table_columns(config, "reading_history", READING_HISTORY_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS catalog_uploads (
            id {_id_column(config)},
            imported_count INTEGER NOT NULL,
            columns_json TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    ensure_table_columns(config, "catalog_uploads", CATALOG_UPLOAD_COLUMN_TYPES)


def replace_books(config: DatabaseConfig, books_df: pd.DataFrame) -> int:
    init_db(config)
    delete_statements = [
        "DELETE FROM reading_history",
        "DELETE FROM reviewed_lessons",
        "DELETE FROM feedback",
        "DELETE FROM quiz_results",
        "DELETE FROM generated_lessons",
        "DELETE FROM selected_books",
        "DELETE FROM saved_books",
        "DELETE FROM student_books",
        "DELETE FROM recommendation_sessions",
        "DELETE FROM books",
    ]
    for statement in delete_statements:
        execute_query(config, statement)

    insert_query = f"""
        INSERT INTO books ({", ".join(BOOK_COLUMNS)})
        VALUES ({", ".join(["%s"] * len(BOOK_COLUMNS))})
    """
    param_sets = [
        tuple(_prepare_value(row[column]) for column in BOOK_COLUMNS)
        for _, row in books_df.iterrows()
    ]
    execute_query(config, insert_query, many=True, param_sets=param_sets)
    return len(books_df)


def fetch_all_books(config: DatabaseConfig) -> pd.DataFrame:
    init_db(config)
    rows = fetch_all(
        config,
        """
        SELECT *
        FROM books
        ORDER BY LOWER(COALESCE(title, ''))
        """,
    )
    books_df = pd.DataFrame(rows)
    if books_df.empty:
        books_df = pd.DataFrame(columns=["id", *BOOK_COLUMNS])
    for column in BOOK_COLUMNS:
        if column not in books_df.columns:
            books_df[column] = "" if column != "pages" else 0
    return books_df


def fetch_book_by_id(config: DatabaseConfig, book_id: int) -> dict[str, Any] | None:
    init_db(config)
    return fetch_one(config, "SELECT * FROM books WHERE id = %s", (book_id,))


def save_reviewed_lesson(
    config: DatabaseConfig,
    book_id: int,
    subject: str,
    concept: str,
    grade: str,
    generated_lesson: str,
    reviewed_lesson: str,
) -> int:
    init_db(config)
    return insert_and_get_id(
        config,
        """
        INSERT INTO reviewed_lessons (
            book_id, subject, concept, grade, generated_lesson, reviewed_lesson
        ) VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (book_id, subject, concept, grade, generated_lesson, reviewed_lesson),
    )


def fetch_latest_reviewed_lesson(config: DatabaseConfig, book_id: int) -> dict[str, Any] | None:
    init_db(config)
    return fetch_one(
        config,
        """
        SELECT *
        FROM reviewed_lessons
        WHERE book_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (book_id,),
    )


def log_catalog_upload(config: DatabaseConfig, imported_count: int, columns: list[str]) -> int:
    init_db(config)
    return insert_and_get_id(
        config,
        """
        INSERT INTO catalog_uploads (imported_count, columns_json)
        VALUES (%s, %s)
        RETURNING id
        """,
        (imported_count, json.dumps(columns)),
    )


def create_recommendation_session(
    config: DatabaseConfig,
    student_id: int | None,
    grade: str,
    preferences: dict[str, Any],
    recommended_books: list[dict[str, Any]],
) -> int:
    init_db(config)
    compact_books = [
        {
            "id": book.get("id"),
            "title": book.get("title"),
            "author": book.get("author"),
            "score": book.get("recommendation_score"),
        }
        for book in recommended_books
    ]
    session_id = insert_and_get_id(
        config,
        """
        INSERT INTO recommendation_sessions (student_id, grade, preferences_json, recommended_books_json)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (student_id, str(grade or ""), json.dumps(preferences), json.dumps(compact_books)),
    )
    log_reading_history(
        config,
        student_id,
        "recommendation_session",
        f"Received {len(compact_books)} book recommendations.",
    )
    return session_id


def log_selected_book(config: DatabaseConfig, session_id: int | None, book_id: int, student_id: int | None = None) -> int:
    init_db(config)
    selected_id = insert_and_get_id(
        config,
        """
        INSERT INTO selected_books (student_id, session_id, book_id)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (student_id, session_id, book_id),
    )
    log_reading_history(config, student_id, "selected_book", "Selected a book for lesson generation.", book_id=book_id)
    return selected_id


def log_generated_lesson(
    config: DatabaseConfig,
    student_id: int | None,
    session_id: int | None,
    book_id: int,
    grade: str,
    subject: str,
    concept: str,
    generated_lesson: str,
) -> int:
    init_db(config)
    lesson_id = insert_and_get_id(
        config,
        """
        INSERT INTO generated_lessons (student_id, session_id, book_id, grade, subject, concept, generated_lesson)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (student_id, session_id, book_id, grade, subject, concept, generated_lesson),
    )
    log_reading_history(
        config,
        student_id,
        "generated_lesson",
        f"Generated a {subject} lesson about {concept}.",
        book_id=book_id,
        lesson_log_id=lesson_id,
    )
    return lesson_id


def save_feedback(
    config: DatabaseConfig,
    student_id: int | None,
    session_id: int | None,
    recommendation_useful: bool,
    lesson_understandable: bool,
    rating: int,
    comment: str = "",
) -> int:
    init_db(config)
    return insert_and_get_id(
        config,
        """
        INSERT INTO feedback (
            student_id, session_id, recommendation_useful, lesson_understandable, story_help_learning, rating, comment
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            student_id,
            session_id,
            int(bool(recommendation_useful)),
            int(bool(lesson_understandable)),
            int(bool(lesson_understandable)),
            int(rating),
            comment.strip(),
        ),
    )


def save_student_profile(
    config: DatabaseConfig,
    name: str,
    grade: str,
    preferred_language: str,
    favorite_topics: str,
    reading_comfort_level: str,
    student_id: int | None = None,
) -> int:
    init_db(config)
    clean_name = name.strip()
    clean_grade = grade.strip()
    clean_language = preferred_language.strip()
    clean_topics = favorite_topics.strip()
    clean_level = reading_comfort_level.strip()

    if student_id:
        execute_query(
            config,
            """
            UPDATE students
            SET name = %s, grade = %s, preferred_language = %s, favorite_topics = %s,
                reading_comfort_level = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (clean_name, clean_grade, clean_language, clean_topics, clean_level, student_id),
        )
        _upsert_student_profile_shadow(config, student_id, clean_name, clean_grade, clean_language, clean_topics, clean_level)
        return student_id

    new_student_id = insert_and_get_id(
        config,
        """
        INSERT INTO students (name, grade, preferred_language, favorite_topics, reading_comfort_level)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (clean_name, clean_grade, clean_language, clean_topics, clean_level),
    )
    _upsert_student_profile_shadow(config, new_student_id, clean_name, clean_grade, clean_language, clean_topics, clean_level)
    return new_student_id


def fetch_students(config: DatabaseConfig) -> pd.DataFrame:
    init_db(config)
    return pd.DataFrame(
        fetch_all(
            config,
            """
            SELECT *
            FROM students
            ORDER BY updated_at DESC, LOWER(COALESCE(name, ''))
            """,
        )
    )


def fetch_student_profile(config: DatabaseConfig, student_id: int) -> dict[str, Any] | None:
    init_db(config)
    return fetch_one(config, "SELECT * FROM students WHERE id = %s", (student_id,))


def update_student_book_status(
    config: DatabaseConfig,
    student_id: int,
    book_id: int,
    *,
    saved_for_later: bool | None = None,
    marked_as_read: bool | None = None,
) -> int:
    init_db(config)
    existing = fetch_one(
        config,
        """
        SELECT id, saved_for_later, marked_as_read
        FROM student_books
        WHERE student_id = %s AND book_id = %s
        """,
        (student_id, book_id),
    )
    save_value = int(saved_for_later) if saved_for_later is not None else int(existing["saved_for_later"]) if existing else 0
    read_value = int(marked_as_read) if marked_as_read is not None else int(existing["marked_as_read"]) if existing else 0

    if existing:
        execute_query(
            config,
            """
            UPDATE student_books
            SET saved_for_later = %s, marked_as_read = %s,
                saved_at = CASE WHEN %s = 1 THEN COALESCE(saved_at, CURRENT_TIMESTAMP) ELSE NULL END,
                read_at = CASE WHEN %s = 1 THEN COALESCE(read_at, CURRENT_TIMESTAMP) ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (save_value, read_value, save_value, read_value, int(existing["id"])),
        )
        record_id = int(existing["id"])
    else:
        record_id = insert_and_get_id(
            config,
            """
            INSERT INTO student_books (
                student_id, book_id, saved_for_later, marked_as_read, saved_at, read_at
            )
            VALUES (
                %s, %s, %s, %s,
                CASE WHEN %s = 1 THEN CURRENT_TIMESTAMP ELSE NULL END,
                CASE WHEN %s = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
            )
            RETURNING id
            """,
            (student_id, book_id, save_value, read_value, save_value, read_value),
        )

    _upsert_saved_book_shadow(config, student_id, book_id, save_value, read_value)
    if saved_for_later is not None:
        log_reading_history(
            config,
            student_id,
            "saved_book" if save_value else "unsaved_book",
            "Saved a book for later." if save_value else "Removed a book from saved books.",
            book_id=book_id,
        )
    if marked_as_read is not None:
        log_reading_history(
            config,
            student_id,
            "marked_read" if read_value else "unmarked_read",
            "Marked a book as read." if read_value else "Removed a book from read history.",
            book_id=book_id,
        )
    return record_id


def fetch_student_book_statuses(config: DatabaseConfig, student_id: int) -> dict[int, dict[str, Any]]:
    init_db(config)
    rows = fetch_all(config, "SELECT * FROM student_books WHERE student_id = %s", (student_id,))
    return {int(row["book_id"]): row for row in rows}


def save_quiz_result(
    config: DatabaseConfig,
    student_id: int,
    book_id: int,
    lesson_log_id: int | None,
    score: int,
    total_questions: int,
    answers: list[dict[str, Any]],
) -> int:
    init_db(config)
    quiz_result_id = insert_and_get_id(
        config,
        """
        INSERT INTO quiz_results (student_id, book_id, lesson_log_id, score, total_questions, answers_json)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (student_id, book_id, lesson_log_id, score, total_questions, json.dumps(answers)),
    )
    log_reading_history(
        config,
        student_id,
        "quiz_completed",
        f"Completed a quiz with score {score}/{total_questions}.",
        book_id=book_id,
        lesson_log_id=lesson_log_id,
        quiz_result_id=quiz_result_id,
    )
    return quiz_result_id


def fetch_student_dashboard_data(config: DatabaseConfig, student_id: int) -> dict[str, Any]:
    init_db(config)
    books_saved_row = fetch_one(
        config,
        "SELECT COUNT(*) AS count FROM student_books WHERE student_id = %s AND saved_for_later = 1",
        (student_id,),
    )
    books_read_row = fetch_one(
        config,
        "SELECT COUNT(*) AS count FROM student_books WHERE student_id = %s AND marked_as_read = 1",
        (student_id,),
    )
    lessons_generated_row = fetch_one(
        config,
        "SELECT COUNT(*) AS count FROM generated_lessons WHERE student_id = %s",
        (student_id,),
    )
    favorite_topics_row = fetch_one(
        config,
        "SELECT favorite_topics FROM students WHERE id = %s",
        (student_id,),
    )
    recommendation_sessions_rows = fetch_all(
        config,
        """
        SELECT id, created_at, recommended_books_json
        FROM recommendation_sessions
        WHERE student_id = %s
        ORDER BY created_at DESC
        """,
        (student_id,),
    )
    recent_activity = pd.DataFrame(
        fetch_all(
            config,
            """
            SELECT activity_type, activity_note AS description, created_at
            FROM reading_history
            WHERE student_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 8
            """,
            (student_id,),
        )
    )
    selected_history = pd.DataFrame(
        fetch_all(
            config,
            """
            SELECT sb.book_id, sb.created_at, books.title, books.author
            FROM selected_books sb
            JOIN books ON books.id = sb.book_id
            WHERE sb.student_id = %s
            ORDER BY sb.created_at DESC, sb.id DESC
            LIMIT 20
            """,
            (student_id,),
        )
    )
    lesson_history = pd.DataFrame(
        fetch_all(
            config,
            """
            SELECT gl.book_id, gl.created_at, books.title, gl.subject, gl.concept
            FROM generated_lessons gl
            JOIN books ON books.id = gl.book_id
            WHERE gl.student_id = %s
            ORDER BY gl.created_at DESC, gl.id DESC
            LIMIT 20
            """,
            (student_id,),
        )
    )
    reading_history = pd.DataFrame(
        fetch_all(
            config,
            """
            SELECT
                student_books.book_id,
                books.title,
                books.author,
                student_books.saved_for_later,
                student_books.marked_as_read,
                student_books.saved_at,
                student_books.read_at
            FROM student_books
            JOIN books ON books.id = student_books.book_id
            WHERE student_books.student_id = %s
            ORDER BY COALESCE(student_books.read_at, student_books.saved_at, student_books.created_at) DESC, student_books.id DESC
            """,
            (student_id,),
        )
    )

    recommended_rows: list[dict[str, Any]] = []
    explored_ids: set[int] = set()
    for session_row in recommendation_sessions_rows:
        try:
            recommended_books = json.loads(session_row["recommended_books_json"])
        except (TypeError, json.JSONDecodeError):
            recommended_books = []
        for item in recommended_books:
            book_id = item.get("id")
            if isinstance(book_id, int):
                explored_ids.add(book_id)
            recommended_rows.append(
                {
                    "created_at": session_row["created_at"],
                    "title": item.get("title", "Unknown title"),
                    "author": item.get("author", "Unknown author"),
                }
            )
    if not reading_history.empty and "book_id" in reading_history.columns:
        explored_ids.update(int(book_id) for book_id in reading_history["book_id"].dropna().tolist())
    if not selected_history.empty and "book_id" in selected_history.columns:
        explored_ids.update(int(book_id) for book_id in selected_history["book_id"].dropna().tolist())
    if not lesson_history.empty and "book_id" in lesson_history.columns:
        explored_ids.update(int(book_id) for book_id in lesson_history["book_id"].dropna().tolist())

    recommended_history = pd.DataFrame(recommended_rows).head(20)
    for frame in (reading_history, selected_history, lesson_history):
        if not frame.empty and "book_id" in frame.columns:
            frame.drop(columns=["book_id"], inplace=True)

    return {
        "total_books_explored": len(explored_ids),
        "total_books_saved": int(books_saved_row["count"]) if books_saved_row else 0,
        "total_books_marked_as_read": int(books_read_row["count"]) if books_read_row else 0,
        "total_lessons_generated": int(lessons_generated_row["count"]) if lessons_generated_row else 0,
        "favorite_topics": favorite_topics_row["favorite_topics"] if favorite_topics_row and favorite_topics_row.get("favorite_topics") else "",
        "recent_activity": recent_activity,
        "recommended_history": recommended_history,
        "selected_history": selected_history,
        "lesson_history": lesson_history,
        "reading_history": reading_history,
    }


def fetch_dashboard_metrics(config: DatabaseConfig) -> dict[str, Any]:
    init_db(config)
    total_uploads_row = fetch_one(config, "SELECT COUNT(*) AS count FROM catalog_uploads")
    total_books_row = fetch_one(config, "SELECT COUNT(*) AS count FROM books")
    total_sessions_row = fetch_one(config, "SELECT COUNT(*) AS count FROM recommendation_sessions")
    avg_rating_row = fetch_one(config, "SELECT AVG(rating) AS avg_rating FROM feedback")
    selected_books_df = pd.DataFrame(
        fetch_all(
            config,
            """
            SELECT
                books.title,
                books.author,
                COUNT(selected_books.id) AS selection_count
            FROM selected_books
            JOIN books ON books.id = selected_books.book_id
            GROUP BY selected_books.book_id, books.title, books.author
            ORDER BY selection_count DESC, LOWER(COALESCE(books.title, ''))
            LIMIT 5
            """,
        )
    )
    return {
        "total_uploads": int(total_uploads_row["count"]) if total_uploads_row else 0,
        "total_books": int(total_books_row["count"]) if total_books_row else 0,
        "total_recommendation_sessions": int(total_sessions_row["count"]) if total_sessions_row else 0,
        "average_feedback_rating": round(float(avg_rating_row["avg_rating"]), 2) if avg_rating_row and avg_rating_row["avg_rating"] is not None else None,
        "most_selected_books": selected_books_df,
    }
