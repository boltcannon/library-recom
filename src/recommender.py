from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict

import pandas as pd

from src.utils import TOPIC_KEYWORDS
from src.utils import safe_int

HIGH_WEIGHT = 6.0
MEDIUM_WEIGHT = 3.0
LOW_WEIGHT = 1.0
PERSONALIZATION_WEIGHT = 2.5
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


def tokenize_csv_values(text: str) -> list[str]:
    return [normalize_text(part) for part in str(text or "").split(",") if normalize_text(part)]


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


def parse_profile_values(preferences: dict[str, str], key: str) -> list[str]:
    value = str(preferences.get(key, "") or "")
    return tokenize_csv_values(value)


def parse_weighted_preferences(preferences: dict[str, str], key: str) -> list[dict[str, object]]:
    raw_value = preferences.get(key, "[]")
    if isinstance(raw_value, list):
        candidate_items = raw_value
    else:
        try:
            candidate_items = json.loads(str(raw_value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    parsed_items: list[dict[str, object]] = []
    for item in candidate_items:
        if not isinstance(item, dict):
            continue
        normalized_value = normalize_text(item.get("value", ""))
        if not normalized_value:
            continue
        parsed_items.append(
            {
                "value": normalized_value,
                "weighted_score": float(item.get("weighted_score", 0) or 0),
                "confidence": normalize_text(item.get("confidence", "emerging")) or "emerging",
            }
        )
    return parsed_items


def confidence_multiplier(confidence: str) -> float:
    normalized = normalize_text(confidence)
    if normalized == "high":
        return 1.0
    if normalized == "medium":
        return 0.8
    return 0.6


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


def score_reading_level(preferred_level: str, reading_level: str) -> tuple[float, str]:
    current_level = normalize_text(reading_level or "mixed")
    preferred = normalize_text(preferred_level or "any")
    if preferred in {"", "any"}:
        return 0.0, f"This book has a {current_level or 'mixed'} reading level."
    ordered_levels = ["easy", "medium", "challenging"]
    if preferred == current_level:
        return 2.0, f"It matches your reading comfort level with a {current_level} reading level."
    if preferred in ordered_levels and current_level in ordered_levels:
        if abs(ordered_levels.index(preferred) - ordered_levels.index(current_level)) == 1:
            return 0.8, f"It is close to your reading comfort level with a {current_level} reading level."
    return 0.0, f"This book has a {current_level or 'mixed'} reading level, which is a lighter fit for your comfort level."


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


def score_profile_alignment(
    preferences: dict[str, str],
    row: pd.Series,
) -> tuple[float, list[str]]:
    profile_topics = parse_profile_values(preferences, "profile_topics")
    profile_genres = parse_profile_values(preferences, "profile_genres")
    profile_lengths = parse_profile_values(preferences, "profile_lengths")
    profile_subjects = parse_profile_values(preferences, "profile_subjects")
    current_subject_tags = tokenize_csv_values(str(row.get("subject_tags", "")))
    current_genres = tokenize_csv_values(str(row.get("genre_tags", "")))
    current_length = normalize_text(str(row.get("length_type", "")))

    score = 0.0
    notes: list[str] = []

    matched_profile_topics = [topic for topic in profile_topics if topic in current_subject_tags]
    if matched_profile_topics:
        score += 1.2
        notes.append(f"it lines up with your usual topics like {', '.join(matched_profile_topics[:2])}")

    matched_profile_subjects = [subject for subject in profile_subjects if subject in current_subject_tags]
    if matched_profile_subjects:
        score += 0.7
        notes.append(f"it supports subjects you return to, like {', '.join(matched_profile_subjects[:2])}")

    matched_profile_genres = [genre for genre in profile_genres if genre in current_genres]
    if matched_profile_genres:
        score += 0.6
        notes.append(f"it matches the kinds of books you usually pick: {', '.join(matched_profile_genres[:2])}")

    if profile_lengths and current_length and current_length in profile_lengths:
        score += 0.4
        notes.append(f"it fits the book length you often enjoy")

    weighted_topics = parse_weighted_preferences(preferences, "weighted_topics_json")
    weighted_genres = parse_weighted_preferences(preferences, "weighted_genres_json")
    weighted_lengths = parse_weighted_preferences(preferences, "weighted_lengths_json")
    book_index = build_book_index(row)

    topic_memory_matches: list[str] = []
    topic_memory_strength = 0.0
    for memory in weighted_topics[:4]:
        topic_match = match_topic_to_book(str(memory["value"]), book_index)
        if topic_match["matched_terms"]:
            memory_boost = min(float(memory["weighted_score"]) / 7.0, 1.2) * confidence_multiplier(str(memory["confidence"]))
            topic_memory_strength += memory_boost
            topic_memory_matches.append(str(memory["value"]))
    if topic_memory_matches:
        score += min(topic_memory_strength, 1.25)
        notes.append(f"it matches the topics you have been choosing lately, like {', '.join(topic_memory_matches[:2])}")

    genre_memory_matches: list[str] = []
    genre_memory_strength = 0.0
    for memory in weighted_genres[:3]:
        if str(memory["value"]) in current_genres:
            memory_boost = min(float(memory["weighted_score"]) / 8.0, 0.9) * confidence_multiplier(str(memory["confidence"]))
            genre_memory_strength += memory_boost
            genre_memory_matches.append(str(memory["value"]))
    if genre_memory_matches:
        score += min(genre_memory_strength, 0.8)
        notes.append(f"it feels close to the kinds of books you keep returning to, like {', '.join(genre_memory_matches[:2])}")

    length_memory_match = next(
        (
            memory
            for memory in weighted_lengths[:2]
            if current_length and current_length == str(memory["value"])
        ),
        None,
    )
    if length_memory_match:
        score += min(float(length_memory_match["weighted_score"]) / 12.0, 0.45)
        notes.append("it fits the reading length you have been comfortable with recently")

    return min(score, PERSONALIZATION_WEIGHT), notes


def score_exploration_value(
    preferences: dict[str, str],
    row: pd.Series,
    topic_score: float,
    personalization_score: float,
) -> tuple[float, str]:
    if topic_score <= 0:
        return 0.0, ""

    weighted_topics = parse_weighted_preferences(preferences, "weighted_topics_json")
    weighted_genres = parse_weighted_preferences(preferences, "weighted_genres_json")
    known_topics = {str(item["value"]) for item in weighted_topics[:4]}
    known_genres = {str(item["value"]) for item in weighted_genres[:3]}
    current_subject_tags = set(tokenize_csv_values(str(row.get("subject_tags", ""))))
    current_genres = set(tokenize_csv_values(str(row.get("genre_tags", ""))))

    introduces_new_topic = bool(current_subject_tags and not current_subject_tags.intersection(known_topics))
    introduces_new_genre = bool(current_genres and not current_genres.intersection(known_genres))

    if personalization_score >= 1.9:
        return 0.0, ""
    if introduces_new_topic and topic_score >= 1.8:
        return 0.65, "It gives you a chance to explore a new topic while staying close to what you asked for."
    if introduces_new_genre and topic_score >= 2.0:
        return 0.45, "It adds a slightly new kind of book without moving too far away from your interests."
    return 0.0, ""


def build_score_breakdown(
    topic_score: float,
    type_score: float,
    length_score: float,
    reading_score: float,
    abstract_score: float,
    metadata_score: float,
    personalization_score: float,
) -> str:
    return (
        f"topic={topic_score:.2f}, "
        f"type={type_score:.2f}, "
        f"length={length_score:.2f}, "
        f"reading={reading_score:.2f}, "
        f"abstract={abstract_score:.2f}, "
        f"metadata={metadata_score:.2f}, "
        f"profile={personalization_score:.2f}"
    )


def build_recommendation_reason(
    row: pd.Series,
    matched_topics: list[str],
    topic_summary: str,
    type_reason: str,
    length_reason: str,
    reading_reason: str,
    abstract_reason: str,
    profile_notes: list[str],
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
    if "matches your reading comfort level" in reading_reason.lower() or "close to your reading comfort level" in reading_reason.lower():
        parts.append(clean_clause(reading_reason[0].lower() + reading_reason[1:]))
    if profile_notes:
        parts.extend(profile_notes[:2])
    if "abstract available" in abstract_reason.lower():
        parts.append("it has an abstract for stronger story and topic matching")

    if not parts:
        return f"{title} was recommended because it is the closest overall match from the current catalog."

    reason = f"{title} was recommended because " + "; ".join(parts) + "."
    if topic_summary and topic_summary != "No strong topic match was found.":
        reason += f" Topic evidence: {topic_summary}."
    return reason


def build_simple_recommendation_reason(
    matched_topics: list[str],
    length_matched: bool,
    preferred_length: str,
    type_matched: bool,
    preferred_type: str,
    profile_notes: list[str],
    recommendation_mode: str,
    exploration_note: str,
) -> str:
    parts: list[str] = []
    if matched_topics:
        parts.append(f"it matches your interest in {', '.join(matched_topics[:2])}")
    if length_matched and preferred_length != "any":
        parts.append(f"it is a {preferred_length} book")
    elif type_matched and preferred_type != "any":
        parts.append(f"it matches your preference for {preferred_type} books")
    elif profile_notes:
        parts.append(profile_notes[0])

    if recommendation_mode == "Explore Pick" and exploration_note:
        parts.append("it also helps you explore something a little new")
    elif recommendation_mode == "Familiar Favorite" and profile_notes:
        parts.append("it fits the kinds of books you usually enjoy")

    if not parts:
        return "Recommended because it is a good overall match."
    return "Recommended because " + " and ".join(parts) + "."


def confidence_label_for_score(total_score: float, topic_score: float, personalization_score: float) -> str:
    if total_score >= 10 or (topic_score >= 5 and personalization_score >= 1):
        return "Strong Match"
    if total_score >= 6:
        return "Good Match"
    return "Explore More"


def track_label_for_row(row: pd.Series) -> str:
    genre_text = normalize_text(str(row.get("genre_tags", "")))
    if "story" in genre_text:
        return "Story Path"
    if "knowledge" in genre_text:
        return "Knowledge Path"
    return "Reading Path"


def recommendation_mode_for_scores(personalization_score: float, exploration_score: float) -> str:
    if exploration_score >= 0.55 and personalization_score < 1.9:
        return "Explore Pick"
    if personalization_score >= 1.15:
        return "Familiar Favorite"
    return "Balanced Pick"


def diversify_recommendations(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if df.empty:
        return df

    working_df = df.copy()
    selected_indices: list[int] = []
    used_subjects: set[str] = set()
    used_genres: set[str] = set()
    has_explore_pick = False

    top_explore = (
        working_df[working_df["recommendation_mode"] == "Explore Pick"]
        if "recommendation_mode" in working_df.columns
        else pd.DataFrame()
    )
    explore_seed_index = None
    if not top_explore.empty:
        explore_seed_index = top_explore.sort_values(["recommendation_score", "title"], ascending=[False, True]).index[0]

    while len(selected_indices) < min(top_n, len(working_df)):
        best_index = None
        best_value = float("-inf")
        for row_index, row in working_df.iterrows():
            if row_index in selected_indices:
                continue
            adjusted_score = float(row.get("recommendation_score", 0))
            subject_tags = tokenize_csv_values(str(row.get("subject_tags", "")))
            genre_tags = tokenize_csv_values(str(row.get("genre_tags", "")))
            recommendation_mode = str(row.get("recommendation_mode", ""))
            if subject_tags and any(tag in used_subjects for tag in subject_tags[:2]):
                adjusted_score -= 0.75
            if genre_tags and any(tag in used_genres for tag in genre_tags[:1]):
                adjusted_score -= 0.35
            if len(selected_indices) == 1 and not has_explore_pick and explore_seed_index is not None:
                if row_index == explore_seed_index:
                    adjusted_score += 0.55
                elif recommendation_mode != "Explore Pick":
                    adjusted_score -= 0.3
            if adjusted_score > best_value:
                best_value = adjusted_score
                best_index = row_index
        if best_index is None:
            break
        selected_indices.append(best_index)
        selected_row = working_df.loc[best_index]
        if str(selected_row.get("recommendation_mode", "")) == "Explore Pick":
            has_explore_pick = True
        used_subjects.update(tokenize_csv_values(str(selected_row.get("subject_tags", "")))[:2])
        used_genres.update(tokenize_csv_values(str(selected_row.get("genre_tags", "")))[:1])

    return working_df.loc[selected_indices]


def recommend_books(books_df: pd.DataFrame, preferences: dict[str, str], top_n: int = 5) -> pd.DataFrame:
    df = books_df.copy()
    if df.empty:
        return df

    preferred_topics = tokenize_topics(preferences.get("topics", ""))
    preferred_type = str(preferences.get("book_type", "any") or "any").lower()
    preferred_length = str(preferences.get("length_type", "any") or "any").lower()
    preferred_reading_level = str(preferences.get("reading_level", "any") or "any").lower()

    scores = []
    reasons = []

    for _, row in df.iterrows():
        row_index = row.name
        book_index = build_book_index(row)
        topic_results = [match_topic_to_book(topic, book_index) for topic in preferred_topics]
        topic_score, topic_details, topic_summary = score_topic_matches(topic_results)
        type_score, type_reason = score_book_type(preferred_type, str(row.get("genre_tags", "")), str(row.get("item_type", "")))
        length_score, length_reason = score_length(preferred_length, str(row.get("length_type", "")), row.get("pages", 0))
        reading_score, reading_reason = score_reading_level(preferred_reading_level, str(row.get("reading_level", "")))
        abstract_score, abstract_reason = score_abstract(str(row.get("abstract", "")))
        metadata_score, metadata_reason = score_metadata(row)
        personalization_score, profile_notes = score_profile_alignment(preferences, row)
        exploration_score, exploration_note = score_exploration_value(preferences, row, topic_score, personalization_score)

        total_score = round(
            topic_score + type_score + length_score + reading_score + abstract_score + metadata_score + personalization_score + exploration_score,
            2,
        )
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
        if reading_score > 0:
            matched_preferences.append(f"reading: {preferred_reading_level}")

        recommendation_mode = recommendation_mode_for_scores(personalization_score, exploration_score)

        scores.append(total_score)
        reasons.append(
            build_recommendation_reason(
                row,
                matched_topics,
                topic_summary,
                type_reason,
                length_reason,
                reading_reason,
                abstract_reason,
                profile_notes,
            )
        )
        df.at[row_index, "simple_recommendation_reason"] = build_simple_recommendation_reason(
            matched_topics,
            length_score > 0,
            preferred_length,
            type_score > 0,
            preferred_type,
            profile_notes,
            recommendation_mode,
            exploration_note,
        )
        df.at[row_index, "matched_preferences"] = ", ".join(matched_preferences) or "general fit"
        df.at[row_index, "matched_keywords"] = ", ".join(matched_terms) or "No exact keyword match"
        df.at[row_index, "length_reason"] = length_reason
        df.at[row_index, "reading_reason"] = reading_reason
        df.at[row_index, "abstract_status"] = (
            "Abstract available for both recommendation and story-based learning."
            if abstract_score > 0
            else "This book can be recommended, but story-based lesson generation may be weak because abstract is missing."
        )
        df.at[row_index, "recommendation_score_breakdown"] = build_score_breakdown(
            topic_score,
            type_score,
            length_score,
            reading_score,
            abstract_score,
            metadata_score,
            personalization_score,
        )
        df.at[row_index, "topic_score"] = round(topic_score, 2)
        df.at[row_index, "type_score"] = round(type_score, 2)
        df.at[row_index, "length_score"] = round(length_score, 2)
        df.at[row_index, "reading_score"] = round(reading_score, 2)
        df.at[row_index, "abstract_score"] = round(abstract_score, 2)
        df.at[row_index, "metadata_score"] = round(metadata_score, 2)
        df.at[row_index, "personalization_score"] = round(personalization_score, 2)
        df.at[row_index, "exploration_score"] = round(exploration_score, 2)
        df.at[row_index, "topic_match_details"] = " | ".join(topic_details) if topic_details else "No strong topic match"
        df.at[row_index, "metadata_reason"] = metadata_reason
        df.at[row_index, "type_reason"] = type_reason
        df.at[row_index, "profile_match_reason"] = "; ".join(profile_notes) if profile_notes else (exploration_note or "This is a balanced recommendation.")
        df.at[row_index, "confidence_label"] = confidence_label_for_score(total_score, topic_score, personalization_score)
        df.at[row_index, "recommendation_track"] = track_label_for_row(row)
        df.at[row_index, "recommendation_mode"] = recommendation_mode

    df["recommendation_score"] = scores
    df["recommendation_reason"] = reasons
    df = df.sort_values(["recommendation_score", "title"], ascending=[False, True])
    return diversify_recommendations(df, top_n).reset_index(drop=True)
