from __future__ import annotations

import math
import re
from typing import Iterable

import pandas as pd

EXPECTED_COLUMNS = {
    "accession_no": "accession_no",
    "accession no": "accession_no",
    "call_no": "call_no",
    "call no": "call_no",
    "location": "location",
    "item_type": "item_type",
    "item type": "item_type",
    "isbn": "isbn",
    "publisher": "publisher",
    "pages": "pages",
    "place": "place",
    "author": "author",
    "title": "title",
    "abstract": "abstract",
    "gennote": "gennote",
}

TOPIC_KEYWORDS = {
    "animals/nature": ["animal", "forest", "bird", "dog", "cat", "jungle", "nature", "wildlife"],
    "science": ["science", "experiment", "plant", "water", "energy", "space"],
    "social/emotional": ["friendship", "family", "school", "sharing", "kindness"],
    "math": ["number", "counting", "shapes", "pattern", "money"],
    "sports": ["sports", "football", "cricket", "game", "team"],
    "history": ["history", "freedom", "past", "king", "ancient"],
    "mystery": ["mystery", "secret", "detective", "clue"],
}

SUBJECT_CONCEPTS = {
    "Math": {
        "math": "counting and patterns",
        "animals/nature": "comparing quantities",
        "sports": "scores and numbers",
    },
    "Science": {
        "science": "observation and simple experiments",
        "animals/nature": "living things and habitats",
        "space": "space and the solar system",
    },
    "English": {
        "story": "characters, setting, and sequence",
        "knowledge": "main idea and key facts",
    },
    "Social Science": {
        "history": "community and change over time",
        "social/emotional": "roles in family and school",
    },
    "Values": {
        "social/emotional": "kindness and empathy",
        "story": "making good choices",
    },
}


def normalize_column_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", str(name).strip().lower()).strip()
    return EXPECTED_COLUMNS.get(cleaned, cleaned.replace(" ", "_"))


def clean_catalog_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(columns={column: normalize_column_name(column) for column in df.columns})

    for column in EXPECTED_COLUMNS.values():
        if column not in renamed.columns:
            renamed[column] = ""

    renamed = renamed.loc[:, ~renamed.columns.duplicated()]
    renamed = renamed.fillna("")

    if "pages" in renamed.columns:
        renamed["pages"] = renamed["pages"].apply(parse_pages)
    else:
        renamed["pages"] = 0

    text_columns = [column for column in renamed.columns if column != "pages"]
    for column in text_columns:
        renamed[column] = renamed[column].astype(str).str.strip()

    return renamed


def parse_pages(value: object) -> int:
    if value is None or value == "":
        return 0

    if isinstance(value, (int, float)) and not math.isnan(value):
        return int(value)

    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else 0


def infer_length_type(pages: int) -> str:
    if pages <= 40:
        return "short"
    if pages <= 120:
        return "medium"
    return "long"


def infer_reading_level(pages: int, text: str) -> str:
    word_count = len(text.split())
    if pages <= 40 and word_count < 120:
        return "easy"
    if pages <= 120 and word_count < 250:
        return "medium"
    return "challenging"


def detect_tags(title: str, abstract: str, item_type: str) -> tuple[list[str], list[str]]:
    combined = " ".join([title, abstract, item_type]).lower()
    subject_tags: list[str] = []
    genre_tags: list[str] = []

    for tag, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in combined for keyword in keywords):
            subject_tags.append(tag)

    if any(keyword in combined for keyword in ["story", "tale", "novel", "picture book", "fiction"]):
        genre_tags.append("story")
    if any(keyword in combined for keyword in ["reference", "textbook", "facts", "encyclopedia", "knowledge"]):
        genre_tags.append("knowledge")

    if not genre_tags:
        genre_tags.append("story" if "fiction" in combined else "knowledge" if "non-fiction" in combined else "general")

    return sorted(set(genre_tags)), sorted(set(subject_tags))


def shorten_text(text: str, max_words: int = 50) -> str:
    words = str(text).split()
    if not words:
        return "No abstract available."
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "..."


def book_label(book: dict) -> str:
    title = book.get("title") or "Untitled Book"
    author = book.get("author") or "Unknown Author"
    return f"{title} by {author}"


def list_to_text(items: Iterable[str]) -> str:
    cleaned = [item for item in items if item]
    return ", ".join(sorted(set(cleaned)))


def safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
