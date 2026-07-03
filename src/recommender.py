from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

import pandas as pd

from src.utils import TOPIC_KEYWORDS
from src.utils import safe_int

HIGH_WEIGHT = 6.0
MEDIUM_WEIGHT = 3.0
LOW_WEIGHT = 1.0
METADATA_FIELDS = ["author", "location", "accession_no", "item_type", "publisher", "isbn"]
TEXT_FIELDS = ["title", "abstract", "item_type", "genre_tags", "subject_tags"]


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_tokens(text: object) -> list[str]:
    normalized = normalize_text(text)
    return [token for token in normalized.split() if token]


def tokenize_topics(text: str) -> list[str]:
    raw_parts = re.split(r"[,/;]| and ", text or "")
    normalized_topics: list[str] = []
    for part in raw_parts:
        normalized = normalize_text(part)
        if normalized and normalized not in normalized_topics:
            normalized_topics.append(normalized)
    return normalized_topics


def expand_topic_keywords(topic: str) -> list[str]:
    keywords = [topic]
    topic_tokens = split_tokens(topic)
    keywords.extend(topic_tokens)

    if topic.endswith("s") and len(topic) > 3:
        keywords.append(topic[:-1])

    for tag, values in TOPIC_KEYWORDS.items():
        normalized_tag = normalize_text(tag)
        if (
            topic == normalized_tag
            or topic in normalized_tag
            or normalized_tag in topic
            or any(token in normalized_tag for token in topic_tokens)
            or any(topic in normalize_text(value) or normalize_text(value) in topic for value in values)
        ):
            keywords.extend(split_tokens(normalized_tag))
            keywords.extend(normalize_text(value) for value in values)

    unique_keywords: list[str] = []
    for keyword in keywords:
        normalized = normalize_text(keyword)
        if normalized and normalized not in unique_keywords:
            unique_keywords.append(normalized)
    return unique_keywords


def build_book_index(row: pd.Series) -> dict[str, list[str]]:
    return {field: split_tokens(row.get(field, "")) for field in TEXT_FIELDS}


def match_topic_to_book(topic: str, book_index: dict[str, list[str]]) -> dict[str, object]:
    keyword_pool = expand_topic_keywords(topic)
    field_matches: dict[str, list[str]] = defaultdict(list)

    for field, tokens in book_index.items():
        token_set = set(tokens)
        for keyword in keyword_pool:
            if " " in keyword:
                phrase_tokens = keyword.split()
                if all(token in token_set for token in phrase_tokens):
                    field_matches[field].append(keyword)
            elif keyword in token_set:
                field_matches[field].append(keyword)

    matched_terms = sorted({match for matches in field_matches.values() for match in matches})
    return {
        "topic": topic,
        "matched_terms": matched_terms,
        "field_matches": {
            field: sorted(set(matches))
            for field, matches in field_matches.items()
            if matches
        },
    }


def approximate_grade_band(grade: str) -> str:
    try:
        grade_num = int(str(grade).strip())
    except (TypeError, ValueError):
        grade_num = 5

    if grade_num <= 3:
        return "easy"
    if grade_num <= 7:
        return "medium"
    return "challenging"


def score_topic_matches(topic_results: list[dict[str, object]]) -> tuple[float, list[str], str]:
    matched_topics = [result for result in topic_results if result["matched_terms"]]
    if not matched_topics:
        return 0.0, [], "No strong topic match was found."

    score = 0.0
    details: list[str] = []
    field_weight_map = {
        "title": 1.5,
        "abstract": 1.2,
        "subject_tags": 1.0,
        "genre_tags": 0.9,
        "item_type": 0.5,
    }

    for result in matched_topics:
        field_matches = result["field_matches"]
        topic_score = 0.0
        fields_used: list[str] = []
        for field, weight in field_weight_map.items():
            if field in field_matches:
                topic_score += weight
                fields_used.append(field.replace("_", " "))
        topic_score += min(len(result["matched_terms"]) * 0.25, 1.0)
        score += min(topic_score, HIGH_WEIGHT)
        details.append(
            f"{result['topic']} matched via {', '.join(fields_used)} using words like {', '.join(result['matched_terms'][:4])}"
        )

    score = min(score, HIGH_WEIGHT * max(1, len(matched_topics)))
    summary = "; ".join(details[:3])
    return score, details, summary


def score_book_type(preferred_type: str, genre_tags: str, item_type: str) -> tuple[float, str]:
    if preferred_type == "any":
        return 0.0, "No book-type preference was applied."

    combined = normalize_text(f"{genre_tags} {item_type}")
    if preferred_type in combined:
        return MEDIUM_WEIGHT, f"It matches your {preferred_type} preference."
    return 0.0, f"It does not strongly match your {preferred_type} preference."


def score_length(preferred_length: str, length_type: str, pages: object) -> tuple[float, str]:
    pages_value = safe_int(pages)
    current_length = str(length_type or "unspecified").lower()
    if preferred_length == "any":
        return 0.0, f"This book is {current_length} with about {pages_value} pages."
    if preferred_length == current_length:
        return MEDIUM_WEIGHT, f"This {current_length} book has about {pages_value} pages, which fits your length choice."
    return 0.0, f"This book is {current_length} with about {pages_value} pages, so it is less aligned with your length choice."


def score_abstract(abstract: str) -> tuple[float, str]:
    if str(abstract or "").strip():
        return LOW_WEIGHT, "Abstract available for stronger topic matching and lesson generation."
    return 0.0, "No abstract is available, so topic matching and lesson generation are more limited."


def score_metadata(row: pd.Series) -> tuple[float, str]:
    present_fields = [field for field in METADATA_FIELDS if str(row.get(field, "")).strip()]
    completeness_ratio = len(present_fields) / len(METADATA_FIELDS)
    score = round(completeness_ratio * LOW_WEIGHT, 2)
    if not present_fields:
        return score, "Very little metadata is available for this book."
    return score, f"Metadata is fairly complete ({len(present_fields)}/{len(METADATA_FIELDS)} key fields present)."


def build_score_breakdown(
    topic_score: float,
    type_score: float,
    length_score: float,
    abstract_score: float,
    metadata_score: float,
) -> str:
    return (
        f"topic={topic_score:.2f}, "
        f"type={type_score:.2f}, "
        f"length={length_score:.2f}, "
        f"abstract={abstract_score:.2f}, "
        f"metadata={metadata_score:.2f}"
    )


def build_recommendation_reason(
    row: pd.Series,
    matched_topics: list[str],
    topic_summary: str,
    type_reason: str,
    length_reason: str,
    abstract_reason: str,
) -> str:
    title = row.get("title") or "This book"
    parts: list[str] = []

    def clean_clause(text: str) -> str:
        return text.strip().rstrip(".")

    if matched_topics:
        parts.append(f"it matches your topics: {', '.join(matched_topics)}")
    if "matches your" in type_reason.lower():
        parts.append(clean_clause(type_reason[0].lower() + type_reason[1:]))
    if "fits your length choice" in length_reason.lower():
        parts.append(clean_clause(length_reason[0].lower() + length_reason[1:]))
    if "abstract available" in abstract_reason.lower():
        parts.append("it has an abstract for stronger story and topic matching")

    if not parts:
        return f"{title} was recommended because it is the closest overall match from the current catalog."

    reason = f"{title} was recommended because " + "; ".join(parts) + "."
    if topic_summary and topic_summary != "No strong topic match was found.":
        reason += f" Topic evidence: {topic_summary}."
    return reason


def recommend_books(books_df: pd.DataFrame, preferences: dict[str, str], top_n: int = 5) -> pd.DataFrame:
    df = books_df.copy()
    if df.empty:
        return df

    preferred_topics = tokenize_topics(preferences.get("topics", ""))
    preferred_type = str(preferences.get("book_type", "any") or "any").lower()
    preferred_length = str(preferences.get("length_type", "any") or "any").lower()

    scores = []
    reasons = []

    for _, row in df.iterrows():
        row_index = row.name
        book_index = build_book_index(row)
        topic_results = [match_topic_to_book(topic, book_index) for topic in preferred_topics]
        topic_score, topic_details, topic_summary = score_topic_matches(topic_results)
        type_score, type_reason = score_book_type(preferred_type, str(row.get("genre_tags", "")), str(row.get("item_type", "")))
        length_score, length_reason = score_length(preferred_length, str(row.get("length_type", "")), row.get("pages", 0))
        abstract_score, abstract_reason = score_abstract(str(row.get("abstract", "")))
        metadata_score, metadata_reason = score_metadata(row)

        total_score = round(topic_score + type_score + length_score + abstract_score + metadata_score, 2)
        matched_topics = [result["topic"] for result in topic_results if result["matched_terms"]]
        matched_terms = sorted(
            {
                term
                for result in topic_results
                for term in result["matched_terms"]
            }
        )

        matched_preferences = []
        if matched_topics:
            matched_preferences.append(f"topics: {', '.join(matched_topics)}")
        if type_score > 0:
            matched_preferences.append(f"type: {preferred_type}")
        if length_score > 0:
            matched_preferences.append(f"length: {preferred_length}")

        scores.append(total_score)
        reasons.append(
            build_recommendation_reason(
                row,
                matched_topics,
                topic_summary,
                type_reason,
                length_reason,
                abstract_reason,
            )
        )
        df.at[row_index, "matched_preferences"] = ", ".join(matched_preferences) or "general fit"
        df.at[row_index, "matched_keywords"] = ", ".join(matched_terms) or "No exact keyword match"
        df.at[row_index, "length_reason"] = length_reason
        df.at[row_index, "abstract_status"] = (
            "Abstract available for both recommendation and story-based learning."
            if abstract_score > 0
            else "This book can be recommended, but story-based lesson generation may be weak because abstract is missing."
        )
        df.at[row_index, "recommendation_score_breakdown"] = build_score_breakdown(
            topic_score,
            type_score,
            length_score,
            abstract_score,
            metadata_score,
        )
        df.at[row_index, "topic_score"] = round(topic_score, 2)
        df.at[row_index, "type_score"] = round(type_score, 2)
        df.at[row_index, "length_score"] = round(length_score, 2)
        df.at[row_index, "abstract_score"] = round(abstract_score, 2)
        df.at[row_index, "metadata_score"] = round(metadata_score, 2)
        df.at[row_index, "topic_match_details"] = " | ".join(topic_details) if topic_details else "No strong topic match"
        df.at[row_index, "metadata_reason"] = metadata_reason
        df.at[row_index, "type_reason"] = type_reason

    df["recommendation_score"] = scores
    df["recommendation_reason"] = reasons
    df = df.sort_values(["recommendation_score", "title"], ascending=[False, True])
    return df.head(top_n)
