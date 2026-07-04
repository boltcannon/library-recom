from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import re
from typing import Any, Iterator, Sequence

import pandas as pd
import streamlit as st

from src.auth import hash_password, normalize_email, verify_password
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
    "user_id": "INTEGER NOT NULL UNIQUE",
    "class_grade": "TEXT NOT NULL",
    "preferred_language": "TEXT",
    "favorite_topics": "TEXT",
    "reading_level": "TEXT",
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
    "user_id": "INTEGER NOT NULL",
    "book_id": "INTEGER NOT NULL",
    "status": "TEXT NOT NULL DEFAULT 'saved'",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "completed_at": "TIMESTAMP",
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
    "user_id": "INTEGER NOT NULL",
    "book_id": "INTEGER",
    "opened_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "completed_at": "TIMESTAMP",
}

USER_COLUMN_TYPES = {
    "full_name": "TEXT NOT NULL",
    "email": "TEXT UNIQUE NOT NULL",
    "password_hash": "TEXT NOT NULL",
    "role": "TEXT NOT NULL DEFAULT 'student'",
    "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
    "created_at": "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

USER_FEEDBACK_COLUMN_TYPES = {
    "user_id": "INTEGER NOT NULL",
    "lesson_id": "INTEGER",
    "recommendation_useful": "INTEGER NOT NULL",
    "lesson_understandable": "INTEGER NOT NULL",
    "rating": "INTEGER NOT NULL",
    "comment": "TEXT",
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
    existing_columns = get_existing_columns(config, table_name)

    for column, column_type in expected_columns.items():
        if column not in existing_columns:
            execute_query(config, f"ALTER TABLE {table_name} ADD COLUMN {column} {column_type}")


def ensure_index(config: DatabaseConfig, index_name: str, table_name: str, columns: str, *, unique: bool = False) -> None:
    unique_sql = "UNIQUE " if unique else ""
    execute_query(
        config,
        f"CREATE {unique_sql}INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns})",
    )


def get_existing_columns(config: DatabaseConfig, table_name: str) -> set[str]:
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
        return {row["column_name"] for row in rows}
    rows = fetch_all(config, f"PRAGMA table_info({table_name})")
    return {row["name"] for row in rows}


def _migrate_legacy_student_profiles(config: DatabaseConfig) -> None:
    existing_columns = get_existing_columns(config, "student_profiles")
    if not existing_columns:
        return

    if "user_id" not in existing_columns:
        execute_query(config, "ALTER TABLE student_profiles ADD COLUMN user_id INTEGER")
        existing_columns.add("user_id")
    if "class_grade" not in existing_columns:
        execute_query(config, "ALTER TABLE student_profiles ADD COLUMN class_grade TEXT")
        existing_columns.add("class_grade")
    if "reading_level" not in existing_columns:
        execute_query(config, "ALTER TABLE student_profiles ADD COLUMN reading_level TEXT")
        existing_columns.add("reading_level")

    if "student_id" in existing_columns:
        execute_query(
            config,
            """
            UPDATE student_profiles
            SET user_id = COALESCE(user_id, student_id, id)
            WHERE user_id IS NULL
            """,
        )
    if "grade" in existing_columns:
        execute_query(
            config,
            """
            UPDATE student_profiles
            SET class_grade = COALESCE(class_grade, grade)
            WHERE class_grade IS NULL
            """,
        )
    if "reading_comfort_level" in existing_columns:
        execute_query(
            config,
            """
            UPDATE student_profiles
            SET reading_level = COALESCE(reading_level, reading_comfort_level)
            WHERE reading_level IS NULL
            """,
        )


def _migrate_legacy_users(config: DatabaseConfig) -> None:
    existing_columns = get_existing_columns(config, "users")
    if not existing_columns:
        return

    if "full_name" not in existing_columns:
        execute_query(config, "ALTER TABLE users ADD COLUMN full_name TEXT")
        existing_columns.add("full_name")
    if "password_hash" not in existing_columns:
        execute_query(config, "ALTER TABLE users ADD COLUMN password_hash TEXT")
        existing_columns.add("password_hash")
    if "is_active" not in existing_columns:
        execute_query(config, "ALTER TABLE users ADD COLUMN is_active BOOLEAN")
        existing_columns.add("is_active")

    if "name" in existing_columns:
        execute_query(
            config,
            """
            UPDATE users
            SET full_name = COALESCE(full_name, name, email, 'User')
            WHERE full_name IS NULL
            """,
        )
    else:
        execute_query(
            config,
            """
            UPDATE users
            SET full_name = COALESCE(full_name, email, 'User')
            WHERE full_name IS NULL
            """,
        )

    execute_query(
        config,
        """
        UPDATE users
        SET role = COALESCE(role, 'student')
        WHERE role IS NULL
        """,
    )
    execute_query(
        config,
        """
        UPDATE users
        SET is_active = COALESCE(is_active, TRUE)
        WHERE is_active IS NULL
        """,
    )
    execute_query(
        config,
        """
        UPDATE users
        SET password_hash = COALESCE(password_hash, '')
        WHERE password_hash IS NULL
        """,
    )


def _migrate_legacy_saved_books(config: DatabaseConfig) -> None:
    existing_columns = get_existing_columns(config, "saved_books")
    if not existing_columns:
        return

    if "user_id" not in existing_columns:
        execute_query(config, "ALTER TABLE saved_books ADD COLUMN user_id INTEGER")
        existing_columns.add("user_id")
    if "status" not in existing_columns:
        execute_query(config, "ALTER TABLE saved_books ADD COLUMN status TEXT")
        existing_columns.add("status")
    if "created_at" not in existing_columns:
        execute_query(config, "ALTER TABLE saved_books ADD COLUMN created_at TIMESTAMP")
        existing_columns.add("created_at")
    if "completed_at" not in existing_columns:
        execute_query(config, "ALTER TABLE saved_books ADD COLUMN completed_at TIMESTAMP")
        existing_columns.add("completed_at")

    if "student_id" in existing_columns:
        execute_query(
            config,
            """
            UPDATE saved_books
            SET user_id = COALESCE(user_id, student_id)
            WHERE user_id IS NULL
            """,
        )

    if "saved_for_later" in existing_columns or "marked_as_read" in existing_columns:
        execute_query(
            config,
            """
            UPDATE saved_books
            SET status = COALESCE(
                status,
                CASE
                    WHEN COALESCE(marked_as_read, 0) = 1 AND COALESCE(saved_for_later, 0) = 1 THEN 'saved_read'
                    WHEN COALESCE(marked_as_read, 0) = 1 THEN 'read'
                    WHEN COALESCE(saved_for_later, 0) = 1 THEN 'saved'
                    ELSE 'removed'
                END
            )
            WHERE status IS NULL
            """,
        )
    else:
        execute_query(
            config,
            """
            UPDATE saved_books
            SET status = COALESCE(status, 'saved')
            WHERE status IS NULL
            """,
        )

    if "saved_at" in existing_columns:
        execute_query(
            config,
            """
            UPDATE saved_books
            SET created_at = COALESCE(created_at, saved_at, CURRENT_TIMESTAMP)
            WHERE created_at IS NULL
            """,
        )
    else:
        execute_query(
            config,
            """
            UPDATE saved_books
            SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
            WHERE created_at IS NULL
            """,
        )

    if "read_at" in existing_columns:
        execute_query(
            config,
            """
            UPDATE saved_books
            SET completed_at = COALESCE(completed_at, read_at)
            WHERE completed_at IS NULL
            """,
        )


def _migrate_legacy_reading_history(config: DatabaseConfig) -> None:
    existing_columns = get_existing_columns(config, "reading_history")
    if not existing_columns:
        return

    if "user_id" not in existing_columns:
        execute_query(config, "ALTER TABLE reading_history ADD COLUMN user_id INTEGER")
        existing_columns.add("user_id")
    if "opened_at" not in existing_columns:
        execute_query(config, "ALTER TABLE reading_history ADD COLUMN opened_at TIMESTAMP")
        existing_columns.add("opened_at")
    if "completed_at" not in existing_columns:
        execute_query(config, "ALTER TABLE reading_history ADD COLUMN completed_at TIMESTAMP")
        existing_columns.add("completed_at")

    if "student_id" in existing_columns:
        execute_query(
            config,
            """
            UPDATE reading_history
            SET user_id = COALESCE(user_id, student_id)
            WHERE user_id IS NULL
            """,
        )

    if "created_at" in existing_columns:
        execute_query(
            config,
            """
            UPDATE reading_history
            SET opened_at = COALESCE(opened_at, created_at, CURRENT_TIMESTAMP)
            WHERE opened_at IS NULL
            """,
        )
    else:
        execute_query(
            config,
            """
            UPDATE reading_history
            SET opened_at = COALESCE(opened_at, CURRENT_TIMESTAMP)
            WHERE opened_at IS NULL
            """,
        )

    if "activity_type" in existing_columns:
        execute_query(
            config,
            """
            UPDATE reading_history
            SET completed_at = COALESCE(
                completed_at,
                CASE
                    WHEN activity_type IN ('marked_read', 'quiz_completed') THEN COALESCE(opened_at, CURRENT_TIMESTAMP)
                    ELSE completed_at
                END
            )
            WHERE completed_at IS NULL
            """,
        )


def _upsert_student_profile_shadow(
    config: DatabaseConfig,
    user_id: int,
    class_grade: str,
    preferred_language: str,
    favorite_topics: str,
    reading_level: str,
) -> None:
    existing_columns = get_existing_columns(config, "student_profiles")
    if not existing_columns:
        return

    profile_values: dict[str, Any] = {}
    if "user_id" in existing_columns:
        profile_values["user_id"] = user_id
    if "student_id" in existing_columns:
        profile_values["student_id"] = user_id
    if "class_grade" in existing_columns:
        profile_values["class_grade"] = class_grade
    if "grade" in existing_columns:
        profile_values["grade"] = class_grade
    if "preferred_language" in existing_columns:
        profile_values["preferred_language"] = preferred_language
    if "favorite_topics" in existing_columns:
        profile_values["favorite_topics"] = favorite_topics
    if "reading_level" in existing_columns:
        profile_values["reading_level"] = reading_level
    if "reading_comfort_level" in existing_columns:
        profile_values["reading_comfort_level"] = reading_level

    lookup_column = "user_id" if "user_id" in existing_columns else "student_id" if "student_id" in existing_columns else None
    if lookup_column is None:
        return

    existing_profile = fetch_one(
        config,
        f"SELECT id FROM student_profiles WHERE {lookup_column} = %s",
        (user_id,),
    )

    if existing_profile:
        set_clauses = [f"{column} = %s" for column in profile_values]
        params = list(profile_values.values())
        if "updated_at" in existing_columns:
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        params.append(int(existing_profile["id"]))
        execute_query(
            config,
            f"""
            UPDATE student_profiles
            SET {", ".join(set_clauses)}
            WHERE id = %s
            """,
            params,
        )
        return

    insert_columns = list(profile_values.keys())
    bound_values = list(profile_values.values())
    value_placeholders = ["%s"] * len(bound_values)
    if "created_at" in existing_columns:
        insert_columns.append("created_at")
        value_placeholders.append("CURRENT_TIMESTAMP")
    if "updated_at" in existing_columns:
        insert_columns.append("updated_at")
        value_placeholders.append("CURRENT_TIMESTAMP")
    execute_query(
        config,
        f"""
        INSERT INTO student_profiles ({", ".join(insert_columns)})
        VALUES ({", ".join(value_placeholders)})
        """,
        bound_values,
    )


def _upsert_saved_book_shadow(
    config: DatabaseConfig,
    user_id: int,
    book_id: int,
    status: str,
    completed_at: str | None = None,
) -> None:
    execute_query(
        config,
        """
        INSERT INTO saved_books (
            user_id, book_id, status, created_at, completed_at
        )
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP, %s)
        ON CONFLICT(user_id, book_id) DO UPDATE SET
            status = EXCLUDED.status,
            completed_at = EXCLUDED.completed_at
        """,
        (user_id, book_id, status, completed_at),
    )


def log_book_opened(
    config: DatabaseConfig,
    user_id: int,
    book_id: int,
) -> int:
    return insert_and_get_id(
        config,
        """
        INSERT INTO reading_history (user_id, book_id, opened_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (user_id, book_id),
    )


def mark_book_completed(
    config: DatabaseConfig,
    user_id: int,
    book_id: int,
) -> None:
    execute_query(
        config,
        """
        UPDATE reading_history
        SET completed_at = CURRENT_TIMESTAMP
        WHERE id = (
            SELECT id
            FROM reading_history
            WHERE user_id = %s AND book_id = %s
            ORDER BY opened_at DESC, id DESC
            LIMIT 1
        )
        """,
        (user_id, book_id),
    )


def _init_db_schema(config: DatabaseConfig) -> None:
    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS users (
            id {_id_column(config)},
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _migrate_legacy_users(config)
    ensure_table_columns(config, "users", USER_COLUMN_TYPES)
    ensure_index(config, "idx_users_email_unique", "users", "email", unique=True)

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
            user_id INTEGER NOT NULL UNIQUE,
            class_grade TEXT NOT NULL,
            preferred_language TEXT,
            favorite_topics TEXT,
            reading_level TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """,
    )
    _migrate_legacy_student_profiles(config)
    ensure_table_columns(config, "student_profiles", STUDENT_PROFILE_COLUMN_TYPES)
    ensure_index(config, "idx_student_profiles_user_id_unique", "student_profiles", "user_id", unique=True)

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
            user_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'saved',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (book_id) REFERENCES books(id),
            UNIQUE(user_id, book_id)
        )
        """,
    )
    _migrate_legacy_saved_books(config)
    ensure_table_columns(config, "saved_books", SAVED_BOOK_COLUMN_TYPES)
    ensure_index(config, "idx_saved_books_user_book_unique", "saved_books", "user_id, book_id", unique=True)

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
            user_id INTEGER NOT NULL,
            book_id INTEGER,
            opened_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
        """,
    )
    _migrate_legacy_reading_history(config)
    ensure_table_columns(config, "reading_history", READING_HISTORY_COLUMN_TYPES)

    execute_query(
        config,
        f"""
        CREATE TABLE IF NOT EXISTS user_feedback (
            id {_id_column(config)},
            user_id INTEGER NOT NULL,
            lesson_id INTEGER,
            recommendation_useful INTEGER NOT NULL,
            lesson_understandable INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (lesson_id) REFERENCES generated_lessons(id)
        )
        """,
    )
    ensure_table_columns(config, "user_feedback", USER_FEEDBACK_COLUMN_TYPES)

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


@st.cache_resource(show_spinner=False)
def _init_db_resource(config: DatabaseConfig) -> bool:
    _init_db_schema(config)
    return True


def init_db(config: DatabaseConfig) -> None:
    _init_db_resource(config)


@st.cache_data(show_spinner=False)
def fetch_user_by_email(config: DatabaseConfig, email: str) -> dict[str, Any] | None:
    init_db(config)
    return fetch_one(config, "SELECT * FROM users WHERE email = %s", (normalize_email(email),))


@st.cache_data(show_spinner=False)
def fetch_user_by_id(config: DatabaseConfig, user_id: int) -> dict[str, Any] | None:
    init_db(config)
    return fetch_one(config, "SELECT * FROM users WHERE id = %s", (user_id,))


@st.cache_data(show_spinner=False)
def fetch_all_users(config: DatabaseConfig) -> pd.DataFrame:
    init_db(config)
    return pd.DataFrame(
        fetch_all(
            config,
            """
            SELECT id, full_name, email, role, is_active, created_at
            FROM users
            ORDER BY created_at DESC, LOWER(COALESCE(full_name, ''))
            """,
        )
    )


@st.cache_data(show_spinner=False)
def fetch_admin_user_count(config: DatabaseConfig) -> int:
    init_db(config)
    row = fetch_one(config, "SELECT COUNT(*) AS count FROM users WHERE role = %s", ("admin",))
    return int(row["count"]) if row and row.get("count") is not None else 0


def create_user(
    config: DatabaseConfig,
    full_name: str,
    email: str,
    password: str,
    role: str = "student",
) -> int:
    init_db(config)
    user_id = insert_and_get_id(
        config,
        """
        INSERT INTO users (full_name, email, password_hash, role, is_active)
        VALUES (%s, %s, %s, %s, TRUE)
        RETURNING id
        """,
        (full_name.strip(), normalize_email(email), hash_password(password), role.strip().lower()),
    )
    if role.strip().lower() == "student":
        execute_query(
            config,
            """
            INSERT INTO students (id, name, grade, preferred_language, favorite_topics, reading_comfort_level)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_id, full_name.strip(), "", "", "", ""),
        )
    clear_data_caches()
    return user_id


def update_user_role(
    config: DatabaseConfig,
    user_id: int,
    new_role: str,
) -> None:
    init_db(config)
    execute_query(
        config,
        """
        UPDATE users
        SET role = %s
        WHERE id = %s
        """,
        (new_role.strip().lower(), user_id),
    )
    clear_data_caches()


def update_user_active_status(
    config: DatabaseConfig,
    user_id: int,
    is_active: bool,
) -> None:
    init_db(config)
    execute_query(
        config,
        """
        UPDATE users
        SET is_active = %s
        WHERE id = %s
        """,
        (bool(is_active), user_id),
    )
    clear_data_caches()


def authenticate_user(config: DatabaseConfig, email: str, password: str) -> dict[str, Any] | None:
    user = fetch_user_by_email(config, email)
    if not user:
        return None
    if not bool(user.get("is_active", True)):
        return None
    password_hash = str(user.get("password_hash", "") or "")
    if not password_hash or not verify_password(password, password_hash):
        return None
    return user


def ensure_admin_account(
    config: DatabaseConfig,
    *,
    full_name: str,
    email: str,
    password: str,
) -> int:
    existing = fetch_user_by_email(config, email)
    if existing:
        execute_query(
            config,
            """
            UPDATE users
            SET full_name = %s, password_hash = %s, role = 'admin'
            WHERE id = %s
            """,
            (full_name.strip(), hash_password(password), int(existing["id"])),
        )
        clear_data_caches()
        return int(existing["id"])
    return create_user(config, full_name=full_name, email=email, password=password, role="admin")


@st.cache_data(show_spinner=False)
def fetch_student_profile_for_user(config: DatabaseConfig, user_id: int) -> dict[str, Any] | None:
    init_db(config)
    return fetch_one(config, "SELECT * FROM student_profiles WHERE user_id = %s", (user_id,))


def save_student_profile_for_user(
    config: DatabaseConfig,
    user_id: int,
    full_name: str,
    class_grade: str,
    preferred_language: str,
    favorite_topics: str,
    reading_level: str,
) -> int:
    init_db(config)
    execute_query(
        config,
        """
        UPDATE users
        SET full_name = %s
        WHERE id = %s
        """,
        (full_name.strip(), user_id),
    )
    execute_query(
        config,
        """
        INSERT INTO students (id, name, grade, preferred_language, favorite_topics, reading_comfort_level)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT(id) DO UPDATE SET
            name = EXCLUDED.name,
            grade = EXCLUDED.grade,
            preferred_language = EXCLUDED.preferred_language,
            favorite_topics = EXCLUDED.favorite_topics,
            reading_comfort_level = EXCLUDED.reading_comfort_level,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, full_name.strip(), class_grade.strip(), preferred_language.strip(), favorite_topics.strip(), reading_level.strip()),
    )
    _upsert_student_profile_shadow(
        config,
        user_id,
        class_grade.strip(),
        preferred_language.strip(),
        favorite_topics.strip(),
        reading_level.strip(),
    )
    clear_data_caches()
    profile = fetch_student_profile_for_user(config, user_id)
    return int(profile["id"]) if profile else user_id


def update_saved_book_status_for_user(
    config: DatabaseConfig,
    user_id: int,
    book_id: int,
    *,
    saved_for_later: bool | None = None,
    marked_as_read: bool | None = None,
) -> int:
    init_db(config)
    existing = fetch_one(
        config,
        "SELECT * FROM saved_books WHERE user_id = %s AND book_id = %s",
        (user_id, book_id),
    )
    current_status = str(existing.get("status", "")) if existing else ""
    is_saved = current_status in {"saved", "saved_read"}
    is_read = current_status in {"read", "saved_read"}
    save_value = bool(saved_for_later) if saved_for_later is not None else is_saved
    read_value = bool(marked_as_read) if marked_as_read is not None else is_read
    if save_value and read_value:
        status = "saved_read"
    elif read_value:
        status = "read"
    elif save_value:
        status = "saved"
    else:
        status = "removed"

    completed_at = "CURRENT_TIMESTAMP" if read_value else None
    if existing:
        execute_query(
            config,
            """
            UPDATE saved_books
            SET status = %s, completed_at = CASE WHEN %s IN ('read', 'saved_read') THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE id = %s
            """,
            (status, status, int(existing["id"])),
        )
        record_id = int(existing["id"])
    else:
        record_id = insert_and_get_id(
            config,
            """
            INSERT INTO saved_books (user_id, book_id, status, created_at, completed_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CASE WHEN %s IN ('read', 'saved_read') THEN CURRENT_TIMESTAMP ELSE NULL END)
            RETURNING id
            """,
            (user_id, book_id, status, status),
        )

    _upsert_saved_book_shadow(config, user_id, book_id, status, None)
    log_book_opened(config, user_id, book_id)
    if read_value:
        mark_book_completed(config, user_id, book_id)
    clear_data_caches()
    return record_id


@st.cache_data(show_spinner=False)
def fetch_saved_book_statuses_for_user(config: DatabaseConfig, user_id: int) -> dict[int, dict[str, Any]]:
    init_db(config)
    rows = fetch_all(config, "SELECT * FROM saved_books WHERE user_id = %s", (user_id,))
    status_map: dict[int, dict[str, Any]] = {}
    for row in rows:
        status = str(row.get("status", ""))
        status_map[int(row["book_id"])] = {
            **row,
            "saved_for_later": status in {"saved", "saved_read"},
            "marked_as_read": status in {"read", "saved_read"},
        }
    return status_map


def save_user_feedback(
    config: DatabaseConfig,
    user_id: int,
    lesson_id: int | None,
    recommendation_useful: bool,
    lesson_understandable: bool,
    rating: int,
    comment: str = "",
) -> int:
    init_db(config)
    feedback_id = insert_and_get_id(
        config,
        """
        INSERT INTO user_feedback (
            user_id, lesson_id, recommendation_useful, lesson_understandable, rating, comment
        ) VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (user_id, lesson_id, int(bool(recommendation_useful)), int(bool(lesson_understandable)), int(rating), comment.strip()),
    )
    clear_data_caches()
    return feedback_id

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
    clear_data_caches()
    return len(books_df)


@st.cache_data(show_spinner=False)
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


@st.cache_data(show_spinner=False)
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
    reviewed_lesson_id = insert_and_get_id(
        config,
        """
        INSERT INTO reviewed_lessons (
            book_id, subject, concept, grade, generated_lesson, reviewed_lesson
        ) VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (book_id, subject, concept, grade, generated_lesson, reviewed_lesson),
    )
    clear_data_caches()
    return reviewed_lesson_id


@st.cache_data(show_spinner=False)
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
    upload_id = insert_and_get_id(
        config,
        """
        INSERT INTO catalog_uploads (imported_count, columns_json)
        VALUES (%s, %s)
        RETURNING id
        """,
        (imported_count, json.dumps(columns)),
    )
    clear_data_caches()
    return upload_id


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
    clear_data_caches()
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
    if student_id is not None:
        log_book_opened(config, int(student_id), book_id)
    clear_data_caches()
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
    clear_data_caches()
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
    feedback_id = insert_and_get_id(
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
    clear_data_caches()
    return feedback_id


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
        _upsert_student_profile_shadow(config, student_id, clean_grade, clean_language, clean_topics, clean_level)
        clear_data_caches()
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
    _upsert_student_profile_shadow(config, new_student_id, clean_grade, clean_language, clean_topics, clean_level)
    clear_data_caches()
    return new_student_id


@st.cache_data(show_spinner=False)
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


@st.cache_data(show_spinner=False)
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

    status = "saved_read" if save_value and read_value else "read" if read_value else "saved" if save_value else "removed"
    _upsert_saved_book_shadow(config, student_id, book_id, status)
    log_book_opened(config, student_id, book_id)
    if read_value:
        mark_book_completed(config, student_id, book_id)
    clear_data_caches()
    return record_id


@st.cache_data(show_spinner=False)
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
    mark_book_completed(config, student_id, book_id)
    clear_data_caches()
    return quiz_result_id


@st.cache_data(show_spinner=False)
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


@st.cache_data(show_spinner=False)
def fetch_student_dashboard_data_for_user(config: DatabaseConfig, user_id: int) -> dict[str, Any]:
    init_db(config)
    books_saved_row = fetch_one(
        config,
        "SELECT COUNT(*) AS count FROM saved_books WHERE user_id = %s AND status IN ('saved', 'saved_read')",
        (user_id,),
    )
    books_read_row = fetch_one(
        config,
        "SELECT COUNT(*) AS count FROM saved_books WHERE user_id = %s AND status IN ('read', 'saved_read')",
        (user_id,),
    )
    lessons_generated_row = fetch_one(
        config,
        "SELECT COUNT(*) AS count FROM generated_lessons WHERE student_id = %s",
        (user_id,),
    )
    profile_row = fetch_one(
        config,
        "SELECT favorite_topics FROM student_profiles WHERE user_id = %s",
        (user_id,),
    )
    recommendation_sessions_rows = fetch_all(
        config,
        """
        SELECT created_at, recommended_books_json
        FROM recommendation_sessions
        WHERE student_id = %s
        ORDER BY created_at DESC
        """,
        (user_id,),
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
            (user_id,),
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
            (user_id,),
        )
    )
    reading_history = pd.DataFrame(
        fetch_all(
            config,
            """
            SELECT
                saved_books.book_id,
                books.title,
                books.author,
                saved_books.status,
                reading_history.opened_at,
                reading_history.completed_at
            FROM saved_books
            JOIN books ON books.id = saved_books.book_id
            LEFT JOIN reading_history
                ON reading_history.user_id = saved_books.user_id
                AND reading_history.book_id = saved_books.book_id
            WHERE saved_books.user_id = %s
            ORDER BY COALESCE(reading_history.completed_at, reading_history.opened_at, saved_books.created_at) DESC
            """,
            (user_id,),
        )
    )

    recent_activity_rows: list[dict[str, Any]] = []
    for _, row in reading_history.head(8).iterrows():
        status = str(row.get("status", ""))
        description = "Opened a book"
        if status in {"saved", "saved_read"}:
            description = "Saved a book"
        if status in {"read", "saved_read"}:
            description = "Marked a book as read"
        recent_activity_rows.append(
            {
                "activity_type": "Reading",
                "description": description,
                "created_at": row.get("completed_at") or row.get("opened_at"),
            }
        )
    recent_activity = pd.DataFrame(recent_activity_rows)

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
        "favorite_topics": profile_row["favorite_topics"] if profile_row and profile_row.get("favorite_topics") else "",
        "recent_activity": recent_activity,
        "recommended_history": recommended_history,
        "selected_history": selected_history,
        "lesson_history": lesson_history,
        "reading_history": reading_history,
    }


@st.cache_data(show_spinner=False)
def fetch_dashboard_metrics(config: DatabaseConfig) -> dict[str, Any]:
    init_db(config)
    total_uploads_row = fetch_one(config, "SELECT COUNT(*) AS count FROM catalog_uploads")
    total_books_row = fetch_one(config, "SELECT COUNT(*) AS count FROM books")
    total_sessions_row = fetch_one(config, "SELECT COUNT(*) AS count FROM recommendation_sessions")
    avg_rating_row = fetch_one(config, "SELECT AVG(rating) AS avg_rating FROM user_feedback")
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


def clear_data_caches() -> None:
    fetch_all_users.clear()
    fetch_admin_user_count.clear()
    fetch_user_by_email.clear()
    fetch_user_by_id.clear()
    fetch_student_profile_for_user.clear()
    fetch_saved_book_statuses_for_user.clear()
    fetch_student_dashboard_data_for_user.clear()
    fetch_all_books.clear()
    fetch_book_by_id.clear()
    fetch_latest_reviewed_lesson.clear()
    fetch_students.clear()
    fetch_student_profile.clear()
    fetch_student_book_statuses.clear()
    fetch_student_dashboard_data.clear()
    fetch_dashboard_metrics.clear()
