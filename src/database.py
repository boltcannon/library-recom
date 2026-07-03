from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

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
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

RECOMMENDATION_SESSION_COLUMN_TYPES = {
    "grade": "TEXT",
    "preferences_json": "TEXT NOT NULL",
    "recommended_books_json": "TEXT NOT NULL",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

SELECTED_BOOK_COLUMN_TYPES = {
    "session_id": "INTEGER NOT NULL",
    "book_id": "INTEGER NOT NULL",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

GENERATED_LESSON_COLUMN_TYPES = {
    "session_id": "INTEGER",
    "book_id": "INTEGER NOT NULL",
    "grade": "TEXT",
    "subject": "TEXT NOT NULL",
    "concept": "TEXT NOT NULL",
    "generated_lesson": "TEXT NOT NULL",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

FEEDBACK_COLUMN_TYPES = {
    "session_id": "INTEGER",
    "recommendation_useful": "INTEGER NOT NULL",
    "lesson_understandable": "INTEGER NOT NULL",
    "story_help_learning": "INTEGER NOT NULL",
    "rating": "INTEGER NOT NULL",
    "comment": "TEXT",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

CATALOG_UPLOAD_COLUMN_TYPES = {
    "imported_count": "INTEGER NOT NULL",
    "columns_json": "TEXT NOT NULL",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_table_columns(conn: sqlite3.Connection, table_name: str, expected_columns: dict[str, str]) -> None:
    existing_columns = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column, column_type in expected_columns.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {column_type}")


def init_db(db_path: str | Path) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            """
        )
        ensure_table_columns(conn, "books", BOOK_COLUMN_TYPES)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviewed_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                concept TEXT NOT NULL,
                grade TEXT NOT NULL,
                generated_lesson TEXT NOT NULL,
                reviewed_lesson TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id)
            )
            """
        )
        ensure_table_columns(conn, "reviewed_lessons", REVIEWED_LESSON_COLUMN_TYPES)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grade TEXT,
                preferences_json TEXT NOT NULL,
                recommended_books_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        ensure_table_columns(conn, "recommendation_sessions", RECOMMENDATION_SESSION_COLUMN_TYPES)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selected_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                book_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES recommendation_sessions(id),
                FOREIGN KEY (book_id) REFERENCES books(id)
            )
            """
        )
        ensure_table_columns(conn, "selected_books", SELECTED_BOOK_COLUMN_TYPES)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generated_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                book_id INTEGER NOT NULL,
                grade TEXT,
                subject TEXT NOT NULL,
                concept TEXT NOT NULL,
                generated_lesson TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES recommendation_sessions(id),
                FOREIGN KEY (book_id) REFERENCES books(id)
            )
            """
        )
        ensure_table_columns(conn, "generated_lessons", GENERATED_LESSON_COLUMN_TYPES)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                recommendation_useful INTEGER NOT NULL,
                lesson_understandable INTEGER NOT NULL,
                story_help_learning INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES recommendation_sessions(id)
            )
            """
        )
        ensure_table_columns(conn, "feedback", FEEDBACK_COLUMN_TYPES)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                imported_count INTEGER NOT NULL,
                columns_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        ensure_table_columns(conn, "catalog_uploads", CATALOG_UPLOAD_COLUMN_TYPES)
        conn.commit()


def replace_books(db_path: str | Path, books_df: pd.DataFrame) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM reviewed_lessons")
        conn.execute("DELETE FROM selected_books")
        conn.execute("DELETE FROM generated_lessons")
        conn.execute("DELETE FROM books")
        books_df.to_sql("books", conn, if_exists="append", index=False)
        conn.commit()
    return len(books_df)


def fetch_all_books(db_path: str | Path) -> pd.DataFrame:
    init_db(db_path)
    with get_connection(db_path) as conn:
        books_df = pd.read_sql_query("SELECT * FROM books ORDER BY title COLLATE NOCASE", conn)
        for column in BOOK_COLUMNS:
            if column not in books_df.columns:
                books_df[column] = "" if column != "pages" else 0
        return books_df


def fetch_book_by_id(db_path: str | Path, book_id: int) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return dict(row) if row else None


def save_reviewed_lesson(
    db_path: str | Path,
    book_id: int,
    subject: str,
    concept: str,
    grade: str,
    generated_lesson: str,
    reviewed_lesson: str,
) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO reviewed_lessons (
                book_id, subject, concept, grade, generated_lesson, reviewed_lesson
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (book_id, subject, concept, grade, generated_lesson, reviewed_lesson),
        )
        conn.commit()
        return int(cursor.lastrowid)


def fetch_latest_reviewed_lesson(db_path: str | Path, book_id: int) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM reviewed_lessons
            WHERE book_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 1
            """,
            (book_id,),
        ).fetchone()
        return dict(row) if row else None


def log_catalog_upload(db_path: str | Path, imported_count: int, columns: list[str]) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO catalog_uploads (imported_count, columns_json)
            VALUES (?, ?)
            """,
            (imported_count, json.dumps(columns)),
        )
        conn.commit()
        return int(cursor.lastrowid)


def create_recommendation_session(
    db_path: str | Path,
    grade: str,
    preferences: dict[str, Any],
    recommended_books: list[dict[str, Any]],
) -> int:
    init_db(db_path)
    compact_books = [
        {
            "id": book.get("id"),
            "title": book.get("title"),
            "author": book.get("author"),
            "score": book.get("recommendation_score"),
        }
        for book in recommended_books
    ]
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO recommendation_sessions (grade, preferences_json, recommended_books_json)
            VALUES (?, ?, ?)
            """,
            (str(grade or ""), json.dumps(preferences), json.dumps(compact_books)),
        )
        conn.commit()
        return int(cursor.lastrowid)


def log_selected_book(db_path: str | Path, session_id: int | None, book_id: int) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO selected_books (session_id, book_id)
            VALUES (?, ?)
            """,
            (session_id, book_id),
        )
        conn.commit()
        return int(cursor.lastrowid)


def log_generated_lesson(
    db_path: str | Path,
    session_id: int | None,
    book_id: int,
    grade: str,
    subject: str,
    concept: str,
    generated_lesson: str,
) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO generated_lessons (session_id, book_id, grade, subject, concept, generated_lesson)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, book_id, grade, subject, concept, generated_lesson),
        )
        conn.commit()
        return int(cursor.lastrowid)


def save_feedback(
    db_path: str | Path,
    session_id: int | None,
    recommendation_useful: bool,
    lesson_understandable: bool,
    rating: int,
    comment: str = "",
) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO feedback (
                session_id, recommendation_useful, lesson_understandable, story_help_learning, rating, comment
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                int(bool(recommendation_useful)),
                int(bool(lesson_understandable)),
                int(bool(lesson_understandable)),
                int(rating),
                comment.strip(),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def fetch_dashboard_metrics(db_path: str | Path) -> dict[str, Any]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        total_uploads = conn.execute("SELECT COUNT(*) FROM catalog_uploads").fetchone()[0]
        total_books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        total_sessions = conn.execute("SELECT COUNT(*) FROM recommendation_sessions").fetchone()[0]
        avg_rating = conn.execute("SELECT AVG(rating) FROM feedback").fetchone()[0]
        selected_books_df = pd.read_sql_query(
            """
            SELECT
                books.title,
                books.author,
                COUNT(selected_books.id) AS selection_count
            FROM selected_books
            JOIN books ON books.id = selected_books.book_id
            GROUP BY selected_books.book_id, books.title, books.author
            ORDER BY selection_count DESC, books.title COLLATE NOCASE
            LIMIT 5
            """,
            conn,
        )
    return {
        "total_uploads": int(total_uploads or 0),
        "total_books": int(total_books or 0),
        "total_recommendation_sessions": int(total_sessions or 0),
        "average_feedback_rating": round(float(avg_rating), 2) if avg_rating is not None else None,
        "most_selected_books": selected_books_df,
    }
