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
    "student_id": "INTEGER",
    "grade": "TEXT",
    "preferences_json": "TEXT NOT NULL",
    "recommended_books_json": "TEXT NOT NULL",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

SELECTED_BOOK_COLUMN_TYPES = {
    "student_id": "INTEGER",
    "session_id": "INTEGER NOT NULL",
    "book_id": "INTEGER NOT NULL",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

GENERATED_LESSON_COLUMN_TYPES = {
    "student_id": "INTEGER",
    "session_id": "INTEGER",
    "book_id": "INTEGER NOT NULL",
    "grade": "TEXT",
    "subject": "TEXT NOT NULL",
    "concept": "TEXT NOT NULL",
    "generated_lesson": "TEXT NOT NULL",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

FEEDBACK_COLUMN_TYPES = {
    "student_id": "INTEGER",
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

STUDENT_COLUMN_TYPES = {
    "name": "TEXT NOT NULL",
    "grade": "TEXT NOT NULL",
    "preferred_language": "TEXT",
    "favorite_topics": "TEXT",
    "reading_comfort_level": "TEXT",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

STUDENT_BOOK_COLUMN_TYPES = {
    "student_id": "INTEGER NOT NULL",
    "book_id": "INTEGER NOT NULL",
    "saved_for_later": "INTEGER NOT NULL DEFAULT 0",
    "marked_as_read": "INTEGER NOT NULL DEFAULT 0",
    "saved_at": "TEXT",
    "read_at": "TEXT",
    "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
}

QUIZ_RESULT_COLUMN_TYPES = {
    "student_id": "INTEGER NOT NULL",
    "book_id": "INTEGER NOT NULL",
    "lesson_log_id": "INTEGER",
    "score": "INTEGER NOT NULL",
    "total_questions": "INTEGER NOT NULL",
    "answers_json": "TEXT NOT NULL",
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
                student_id INTEGER,
                grade TEXT,
                preferences_json TEXT NOT NULL,
                recommended_books_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
            """
        )
        ensure_table_columns(conn, "recommendation_sessions", RECOMMENDATION_SESSION_COLUMN_TYPES)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selected_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                session_id INTEGER NOT NULL,
                book_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
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
                student_id INTEGER,
                session_id INTEGER,
                book_id INTEGER NOT NULL,
                grade TEXT,
                subject TEXT NOT NULL,
                concept TEXT NOT NULL,
                generated_lesson TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
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
                student_id INTEGER,
                session_id INTEGER,
                recommendation_useful INTEGER NOT NULL,
                lesson_understandable INTEGER NOT NULL,
                story_help_learning INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                grade TEXT NOT NULL,
                preferred_language TEXT,
                favorite_topics TEXT,
                reading_comfort_level TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        ensure_table_columns(conn, "students", STUDENT_COLUMN_TYPES)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS student_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                book_id INTEGER NOT NULL,
                saved_for_later INTEGER NOT NULL DEFAULT 0,
                marked_as_read INTEGER NOT NULL DEFAULT 0,
                saved_at TEXT,
                read_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
                FOREIGN KEY (book_id) REFERENCES books(id),
                UNIQUE(student_id, book_id)
            )
            """
        )
        ensure_table_columns(conn, "student_books", STUDENT_BOOK_COLUMN_TYPES)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                book_id INTEGER NOT NULL,
                lesson_log_id INTEGER,
                score INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                answers_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
                FOREIGN KEY (book_id) REFERENCES books(id),
                FOREIGN KEY (lesson_log_id) REFERENCES generated_lessons(id)
            )
            """
        )
        ensure_table_columns(conn, "quiz_results", QUIZ_RESULT_COLUMN_TYPES)
        conn.commit()


def replace_books(db_path: str | Path, books_df: pd.DataFrame) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM reviewed_lessons")
        conn.execute("DELETE FROM selected_books")
        conn.execute("DELETE FROM generated_lessons")
        conn.execute("DELETE FROM student_books")
        conn.execute("DELETE FROM quiz_results")
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
    student_id: int | None,
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
            INSERT INTO recommendation_sessions (student_id, grade, preferences_json, recommended_books_json)
            VALUES (?, ?, ?, ?)
            """,
            (student_id, str(grade or ""), json.dumps(preferences), json.dumps(compact_books)),
        )
        conn.commit()
        return int(cursor.lastrowid)


def log_selected_book(db_path: str | Path, session_id: int | None, book_id: int, student_id: int | None = None) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO selected_books (student_id, session_id, book_id)
            VALUES (?, ?, ?)
            """,
            (student_id, session_id, book_id),
        )
        conn.commit()
        return int(cursor.lastrowid)


def log_generated_lesson(
    db_path: str | Path,
    student_id: int | None,
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
            INSERT INTO generated_lessons (student_id, session_id, book_id, grade, subject, concept, generated_lesson)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (student_id, session_id, book_id, grade, subject, concept, generated_lesson),
        )
        conn.commit()
        return int(cursor.lastrowid)


def save_feedback(
    db_path: str | Path,
    student_id: int | None,
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
                student_id, session_id, recommendation_useful, lesson_understandable, story_help_learning, rating, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
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
        conn.commit()
        return int(cursor.lastrowid)


def save_student_profile(
    db_path: str | Path,
    name: str,
    grade: str,
    preferred_language: str,
    favorite_topics: str,
    reading_comfort_level: str,
    student_id: int | None = None,
) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        if student_id:
            conn.execute(
                """
                UPDATE students
                SET name = ?, grade = ?, preferred_language = ?, favorite_topics = ?,
                    reading_comfort_level = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (name.strip(), grade.strip(), preferred_language.strip(), favorite_topics.strip(), reading_comfort_level.strip(), student_id),
            )
            conn.commit()
            return student_id

        cursor = conn.execute(
            """
            INSERT INTO students (name, grade, preferred_language, favorite_topics, reading_comfort_level)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name.strip(), grade.strip(), preferred_language.strip(), favorite_topics.strip(), reading_comfort_level.strip()),
        )
        conn.commit()
        return int(cursor.lastrowid)


def fetch_students(db_path: str | Path) -> pd.DataFrame:
    init_db(db_path)
    with get_connection(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT *
            FROM students
            ORDER BY datetime(updated_at) DESC, name COLLATE NOCASE
            """,
            conn,
        )


def fetch_student_profile(db_path: str | Path, student_id: int) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        return dict(row) if row else None


def update_student_book_status(
    db_path: str | Path,
    student_id: int,
    book_id: int,
    *,
    saved_for_later: bool | None = None,
    marked_as_read: bool | None = None,
) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id, saved_for_later, marked_as_read FROM student_books WHERE student_id = ? AND book_id = ?",
            (student_id, book_id),
        ).fetchone()
        save_value = int(saved_for_later) if saved_for_later is not None else int(existing[1]) if existing else 0
        read_value = int(marked_as_read) if marked_as_read is not None else int(existing[2]) if existing else 0

        if existing:
            conn.execute(
                """
                UPDATE student_books
                SET saved_for_later = ?, marked_as_read = ?,
                    saved_at = CASE WHEN ? = 1 THEN COALESCE(saved_at, CURRENT_TIMESTAMP) ELSE NULL END,
                    read_at = CASE WHEN ? = 1 THEN COALESCE(read_at, CURRENT_TIMESTAMP) ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (save_value, read_value, save_value, read_value, existing[0]),
            )
            conn.commit()
            return int(existing[0])

        cursor = conn.execute(
            """
            INSERT INTO student_books (
                student_id, book_id, saved_for_later, marked_as_read, saved_at, read_at
            )
            VALUES (
                ?, ?, ?, ?,
                CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END,
                CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
            )
            """,
            (student_id, book_id, save_value, read_value, save_value, read_value),
        )
        conn.commit()
        return int(cursor.lastrowid)


def fetch_student_book_statuses(db_path: str | Path, student_id: int) -> dict[int, dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM student_books WHERE student_id = ?",
            (student_id,),
        ).fetchall()
        return {
            int(row["book_id"]): dict(row)
            for row in rows
        }


def save_quiz_result(
    db_path: str | Path,
    student_id: int,
    book_id: int,
    lesson_log_id: int | None,
    score: int,
    total_questions: int,
    answers: list[dict[str, Any]],
) -> int:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO quiz_results (student_id, book_id, lesson_log_id, score, total_questions, answers_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (student_id, book_id, lesson_log_id, score, total_questions, json.dumps(answers)),
        )
        conn.commit()
        return int(cursor.lastrowid)


def fetch_student_dashboard_data(db_path: str | Path, student_id: int) -> dict[str, Any]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        books_saved = conn.execute(
            "SELECT COUNT(*) FROM student_books WHERE student_id = ? AND saved_for_later = 1",
            (student_id,),
        ).fetchone()[0]
        books_read = conn.execute(
            "SELECT COUNT(*) FROM student_books WHERE student_id = ? AND marked_as_read = 1",
            (student_id,),
        ).fetchone()[0]
        lessons_generated = conn.execute(
            "SELECT COUNT(*) FROM generated_lessons WHERE student_id = ?",
            (student_id,),
        ).fetchone()[0]
        favorite_topics = conn.execute(
            "SELECT favorite_topics FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
        recommendation_sessions_df = pd.read_sql_query(
            """
            SELECT id, created_at, recommended_books_json
            FROM recommendation_sessions
            WHERE student_id = ?
            ORDER BY datetime(created_at) DESC
            """,
            conn,
            params=(student_id,),
        )

        recent_activity = pd.read_sql_query(
            """
            SELECT activity_type, description, created_at
            FROM (
                SELECT
                    'Recommendation' AS activity_type,
                    'Received book recommendations' AS description,
                    created_at
                FROM recommendation_sessions
                WHERE student_id = ?
                UNION ALL
                SELECT
                    'Book saved' AS activity_type,
                    'Saved a book for later' AS description,
                    COALESCE(saved_at, created_at) AS created_at
                FROM student_books
                WHERE student_id = ? AND saved_for_later = 1
                UNION ALL
                SELECT
                    'Book read' AS activity_type,
                    'Marked a book as read' AS description,
                    COALESCE(read_at, created_at) AS created_at
                FROM student_books
                WHERE student_id = ? AND marked_as_read = 1
                UNION ALL
                SELECT
                    'Lesson' AS activity_type,
                    'Generated a lesson' AS description,
                    created_at
                FROM generated_lessons
                WHERE student_id = ?
                UNION ALL
                SELECT
                    'Quiz' AS activity_type,
                    'Completed a quiz' AS description,
                    created_at
                FROM quiz_results
                WHERE student_id = ?
            )
            ORDER BY datetime(created_at) DESC
            LIMIT 8
            """,
            conn,
            params=(student_id, student_id, student_id, student_id, student_id),
        )
        selected_history = pd.read_sql_query(
            """
            SELECT sb.book_id, sb.created_at, books.title, books.author
            FROM selected_books sb
            JOIN books ON books.id = sb.book_id
            WHERE sb.student_id = ?
            ORDER BY datetime(sb.created_at) DESC
            LIMIT 20
            """,
            conn,
            params=(student_id,),
        )
        lesson_history = pd.read_sql_query(
            """
            SELECT gl.book_id, gl.created_at, books.title, gl.subject, gl.concept
            FROM generated_lessons gl
            JOIN books ON books.id = gl.book_id
            WHERE gl.student_id = ?
            ORDER BY datetime(gl.created_at) DESC
            LIMIT 20
            """,
            conn,
            params=(student_id,),
        )
        reading_history = pd.read_sql_query(
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
            WHERE student_books.student_id = ?
            ORDER BY datetime(COALESCE(student_books.read_at, student_books.saved_at, student_books.created_at)) DESC
            """,
            conn,
            params=(student_id,),
        )

    recommended_rows: list[dict[str, Any]] = []
    explored_ids: set[int] = set()
    for _, session_row in recommendation_sessions_df.iterrows():
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
                    "session_id": session_row["id"],
                    "created_at": session_row["created_at"],
                    "title": item.get("title", "Unknown title"),
                    "author": item.get("author", "Unknown author"),
                }
            )
    if not reading_history.empty:
        explored_ids.update(
            int(book_id)
            for book_id in reading_history["book_id"].dropna().tolist()
        )
    if not selected_history.empty:
        explored_ids.update(
            int(book_id)
            for book_id in selected_history["book_id"].dropna().tolist()
        )
    if not lesson_history.empty:
        explored_ids.update(
            int(book_id)
            for book_id in lesson_history["book_id"].dropna().tolist()
        )

    recommended_history = pd.DataFrame(recommended_rows).head(20)
    for frame in (reading_history, selected_history, lesson_history):
        if "book_id" in frame.columns:
            frame.drop(columns=["book_id"], inplace=True)
    if "session_id" in recommended_history.columns:
        recommended_history.drop(columns=["session_id"], inplace=True)

    return {
        "total_books_explored": len(explored_ids),
        "total_books_saved": int(books_saved or 0),
        "total_books_marked_as_read": int(books_read or 0),
        "total_lessons_generated": int(lessons_generated or 0),
        "favorite_topics": favorite_topics[0] if favorite_topics and favorite_topics[0] else "",
        "recent_activity": recent_activity,
        "recommended_history": recommended_history,
        "selected_history": selected_history,
        "lesson_history": lesson_history,
        "reading_history": reading_history,
    }


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
