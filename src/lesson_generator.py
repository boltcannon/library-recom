from __future__ import annotations

import os
import re
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - depends on local environment
    OpenAI = None

from src.utils import SUBJECT_CONCEPTS

LESSON_HEADINGS = [
    "Story connection",
    "Concept explanation",
    "Step-by-step teaching",
    "Simple example",
    "Small activity",
    "3 practice questions",
    "Answers",
]

DEFAULT_SUBJECT_CONCEPTS = {
    "Math": "counting and comparison",
    "Science": "observation skills",
    "English": "main idea and sequencing",
    "Social Science": "community and people around us",
    "Values": "kindness and responsibility",
}

CONCEPT_RULES = {
    "Math": [
        (["sharing", "food", "money", "number", "count", "pattern", "shape"], ["Fractions", "Sharing", "Counting Patterns"]),
        (["team", "game", "score"], ["Scores and Comparison", "Addition in Games", "Simple Data"]),
    ],
    "Science": [
        (["plant", "water", "animal", "forest", "jungle", "bird"], ["Environment", "Living Things", "Habitats"]),
        (["space", "planet", "energy", "experiment"], ["Space", "Energy", "Observation and Experiments"]),
    ],
    "English": [
        (["character", "friendship", "kindness", "family", "school"], ["Character Traits", "Sequencing", "Main Idea"]),
        (["story", "adventure", "journey"], ["Setting and Plot", "Beginning-Middle-End", "Retelling"]),
    ],
    "Social Science": [
        (["family", "school", "community", "history", "past"], ["Community Helpers", "Family Roles", "Change Over Time"]),
    ],
    "Values": [
        (["friendship", "kindness", "sharing", "help", "care"], ["Moral", "Kindness", "Respect and Responsibility"]),
    ],
}


def normalize_text(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_book_source_text(book: dict[str, Any]) -> str:
    return normalize_text(f"{book.get('title', '')} {book.get('abstract', '')}")


def get_grade_profile(grade: str) -> dict[str, str]:
    try:
        grade_value = int(str(grade).strip())
    except (TypeError, ValueError):
        grade_value = 5

    if grade_value <= 3:
        return {
            "label": f"class {grade_value}",
            "tone": "very simple, short, and warm",
            "activity_style": "draw, circle, match, or say aloud",
        }
    if grade_value <= 6:
        return {
            "label": f"class {grade_value}",
            "tone": "simple, clear, and friendly",
            "activity_style": "write a short answer, discuss, or sort ideas",
        }
    return {
        "label": f"class {grade_value}",
        "tone": "clear, slightly more detailed, and age-appropriate",
        "activity_style": "explain reasoning, compare ideas, or write a short response",
    }


def extract_subject_keywords(subject: str) -> list[str]:
    keywords: list[str] = []
    for tag, concept in SUBJECT_CONCEPTS.get(subject, {}).items():
        keywords.extend(normalize_text(tag).split())
        keywords.extend(normalize_text(concept).split())
    return sorted(set(keyword for keyword in keywords if len(keyword) > 2))


def suggest_concept(book: dict[str, Any], subject: str) -> str:
    return suggest_concepts(book, subject)[0]


def suggest_concepts(book: dict[str, Any], subject: str) -> list[str]:
    subject_tags = [tag.strip() for tag in str(book.get("subject_tags", "")).split(",") if tag.strip()]
    genre_tags = [tag.strip() for tag in str(book.get("genre_tags", "")).split(",") if tag.strip()]
    combined_text = normalize_text(
        f"{book.get('title', '')} {book.get('abstract', '')} {book.get('subject_tags', '')} {book.get('genre_tags', '')}"
    )
    choices = SUBJECT_CONCEPTS.get(subject, {})
    suggestions: list[str] = []

    for tag in subject_tags + genre_tags:
        if tag in choices:
            suggestions.append(choices[tag])

    for keywords, concepts in CONCEPT_RULES.get(subject, []):
        if any(keyword in combined_text for keyword in keywords):
            suggestions.extend(concepts)

    suggestions.append(DEFAULT_SUBJECT_CONCEPTS.get(subject, "main idea"))

    unique_suggestions: list[str] = []
    for suggestion in suggestions:
        if suggestion and suggestion not in unique_suggestions:
            unique_suggestions.append(suggestion)

    return unique_suggestions[:3]


def score_concept_fit(book: dict[str, Any], subject: str, concept: str) -> dict[str, Any]:
    normalized_concept = normalize_text(concept)
    suggested_concepts = [normalize_text(item) for item in suggest_concepts(book, subject)]
    if not normalized_concept:
        return {
            "is_strong": True,
            "matched_terms": [],
            "warning": "",
            "suggested_concept": suggest_concept(book, subject),
        }

    source_text = get_book_source_text(book)
    source_tokens = set(source_text.split())
    concept_tokens = [token for token in normalized_concept.split() if len(token) > 2]
    subject_keywords = extract_subject_keywords(subject)
    candidate_terms = concept_tokens + [term for term in subject_keywords if term in normalized_concept]
    matched_terms = sorted({term for term in candidate_terms if term in source_tokens})
    strong_match = (
        normalized_concept in source_text
        or len(matched_terms) >= max(1, min(2, len(concept_tokens)))
        or normalized_concept in suggested_concepts
    )
    suggested = suggest_concept(book, subject)

    if strong_match:
        return {
            "is_strong": True,
            "matched_terms": matched_terms,
            "warning": "",
            "suggested_concept": suggested,
        }

    return {
        "is_strong": False,
        "matched_terms": matched_terms,
        "warning": (
            f"The connection between this book and '{concept}' looks weak based on the title and abstract. "
            f"A better concept may be '{suggested}'."
        ),
        "suggested_concept": suggested,
    }


def build_prompt(book: dict[str, Any], subject: str, concept: str, grade: str, fit_result: dict[str, Any]) -> str:
    grade_profile = get_grade_profile(grade)
    fit_note = (
        "The chosen concept fits the title and abstract reasonably well."
        if fit_result["is_strong"]
        else f"The chosen concept is weakly connected. Mention that clearly and suggest {fit_result['suggested_concept']}."
    )
    return f"""
You are creating a child-friendly classroom mini-lesson.

Rules:
- Use only the book title and abstract provided below.
- Do not invent new characters, events, places, or plot details.
- Keep the language {grade_profile["tone"]} for {grade_profile["label"]}.
- If the concept fit is weak, say so honestly.
- Make the lesson practical and safe for school students.
- End with: An admin may review this lesson before classroom use.

Book title: {book.get("title", "")}
Book abstract: {book.get("abstract", "")}
Subject: {subject}
Concept: {concept}
Concept fit note: {fit_note}

Return the lesson in this exact section order and keep each section concise:
1. Story connection
2. Concept explanation
3. Step-by-step teaching
4. Simple example
5. Small activity
6. 3 practice questions
7. Answers
"""


def build_missing_abstract_result() -> dict[str, Any]:
    return {
        "warning": "This book does not have enough story information for story-based teaching.",
        "sections": [
            ("Story connection", "This book does not have enough story information for story-based teaching."),
            ("Concept explanation", "Please choose another book with an abstract for a stronger lesson."),
            ("Step-by-step teaching", ["Check whether the catalog has a fuller abstract.", "Choose a book with more story information."]),
            ("Simple example", "A story-based example needs details from the abstract, and they are missing here."),
            ("Small activity", "Ask students to look at another book summary and find one that explains the story better."),
            ("3 practice questions", ["Why is the abstract important?", "What information is missing here?", "What should we do next?"]),
            ("Answers", ["It gives the story details we can teach from.", "Important story information is missing.", "Choose a book with a clearer abstract."]),
        ],
        "chosen_concept": "",
        "fit_result": {"is_strong": False, "matched_terms": [], "warning": "", "suggested_concept": ""},
    }


def build_fallback_lesson(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    fit_result: dict[str, Any],
) -> list[tuple[str, Any]]:
    title = book.get("title", "this book")
    abstract = str(book.get("abstract", "")).strip()
    grade_profile = get_grade_profile(grade)
    suggested_concept = fit_result["suggested_concept"]
    weak_note = (
        f"The link to {concept} is weak, so {suggested_concept} may be a better concept."
        if not fit_result["is_strong"]
        else f"The abstract gives enough support for learning about {concept}."
    )

    story_connection = (
        f"We will use the book {title} to think about {concept} in {subject}. "
        f"From the abstract, we know this much: {abstract}"
    )
    concept_explanation = (
        f"In {grade_profile['label']}, we can explain {concept} in {grade_profile['tone']} language. "
        f"{weak_note}"
    )
    step_by_step = [
        f"Read the title and abstract of {title} carefully.",
        f"Underline or say the words from the abstract that connect to {concept}.",
        f"Explain the idea in {subject} using simple words for {grade_profile['label']}.",
        "Check that every explanation comes from the title or abstract, not from a guessed story detail.",
    ]
    simple_example = (
        f"Use one detail from the abstract and connect it directly to {concept}. "
        "If the abstract does not clearly support the idea, say the connection is weak instead of making up details."
    )
    small_activity = (
        f"Ask students to {grade_profile['activity_style']} and point to one line from the abstract that supports the concept."
    )
    practice_questions = [
        f"What part of the abstract connects to {concept}?",
        f"How can we explain {concept} in {subject} using this book?",
        "Which idea in your lesson comes directly from the title or abstract?",
    ]
    answers = [
        "The best answer points to exact words or ideas from the abstract.",
        f"A good answer explains {concept} in simple {subject} language.",
        "A correct answer uses only supported details from the title or abstract.",
    ]

    return [
        ("Story connection", story_connection),
        ("Concept explanation", concept_explanation),
        ("Step-by-step teaching", step_by_step),
        ("Simple example", simple_example),
        ("Small activity", small_activity),
        ("3 practice questions", practice_questions),
        ("Answers", answers),
    ]


def split_lines_as_list(value: str) -> list[str]:
    items = [line.strip("- ").strip() for line in value.splitlines() if line.strip()]
    return items


def parse_lesson_text(content: str) -> list[tuple[str, Any]]:
    sections: list[tuple[str, Any]] = []
    current_heading = None
    current_lines: list[str] = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        normalized = line.lower().lstrip("1234567890. ").strip()
        matching_heading = next((heading for heading in LESSON_HEADINGS if heading.lower() == normalized), None)
        if matching_heading:
            if current_heading is not None:
                sections.append((current_heading, format_section_body(current_heading, "\n".join(current_lines).strip())))
            current_heading = matching_heading
            current_lines = []
        elif line:
            current_lines.append(line)

    if current_heading is not None:
        sections.append((current_heading, format_section_body(current_heading, "\n".join(current_lines).strip())))

    if not sections:
        return [("Story connection", content.strip() or "Lesson content could not be parsed.")]

    return ensure_lesson_structure(sections)


def format_section_body(section_title: str, body: str) -> Any:
    if section_title in {"Step-by-step teaching", "3 practice questions", "Answers"}:
        if not body:
            return []
        lines = split_lines_as_list(body)
        return lines or [body]
    return body


def ensure_lesson_structure(sections: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    section_map = {title: body for title, body in sections}
    ordered_sections: list[tuple[str, Any]] = []
    for heading in LESSON_HEADINGS:
        if heading in section_map:
            ordered_sections.append((heading, section_map[heading]))
        else:
            fallback_body: Any
            if heading in {"Step-by-step teaching", "3 practice questions", "Answers"}:
                fallback_body = ["This section was not returned, so please review manually."]
            else:
                fallback_body = "This section was not returned, so please review manually."
            ordered_sections.append((heading, fallback_body))
    return ordered_sections


def build_final_warning(fit_result: dict[str, Any], fallback_notice: str) -> str:
    parts = []
    if fit_result["warning"]:
        parts.append(fit_result["warning"])
    if fallback_notice:
        parts.append("Using standard lesson mode.")
    return " ".join(parts).strip()


def lesson_sections_to_text(sections: list[tuple[str, Any]]) -> str:
    blocks: list[str] = []
    for title, body in sections:
        if isinstance(body, list):
            body_text = "\n".join(f"- {item}" for item in body)
        else:
            body_text = str(body)
        blocks.append(f"{title}\n{body_text}".strip())
    blocks.append("An admin may review this lesson before classroom use.")
    return "\n\n".join(blocks)


def _extract_reference_phrase(book: dict[str, Any]) -> str:
    abstract = str(book.get("abstract", "")).strip()
    if not abstract:
        return str(book.get("title", "the book")).strip()
    parts = re.split(r"[.!?]", abstract)
    first = next((part.strip() for part in parts if part.strip()), abstract)
    words = first.split()
    return " ".join(words[:10]) if words else str(book.get("title", "the book")).strip()


def generate_quiz_questions(book: dict[str, Any], concept: str, grade: str) -> list[dict[str, Any]]:
    phrase = _extract_reference_phrase(book)
    title = str(book.get("title", "this book")).strip() or "this book"
    concept_text = concept or "the lesson idea"
    grade_profile = get_grade_profile(grade)
    return [
        {
            "question": f"What is this lesson mainly helping you learn from {title}?",
            "options": [concept_text, "A random made-up story", "Nothing from the book"],
            "answer": concept_text,
            "feedback": f"The lesson is built to teach {concept_text} using the book title and abstract.",
        },
        {
            "question": "Which source should we trust while learning from the story?",
            "options": ["The title and abstract", "Guessed extra story details", "Any imaginary event we like"],
            "answer": "The title and abstract",
            "feedback": f"We only use supported details from {title}'s title and abstract.",
        },
        {
            "question": f"Which detail best connects the lesson to the book?",
            "options": [phrase, "A different story not in the book", "A movie scene we imagined"],
            "answer": phrase,
            "feedback": f"The best answer points back to a real detail from the abstract: {phrase}.",
        },
    ]


def grade_quiz_answers(questions: list[dict[str, Any]], answers: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    score = 0
    for index, question in enumerate(questions):
        selected = answers[index] if index < len(answers) else ""
        correct = selected == question["answer"]
        if correct:
            score += 1
        results.append(
            {
                "question": question["question"],
                "selected_answer": selected,
                "correct_answer": question["answer"],
                "is_correct": correct,
                "feedback": question["feedback"],
            }
        )
    total = len(questions)
    if score == total:
        summary = "Great work. You understood the lesson very well."
    elif score >= max(1, total - 1):
        summary = "Nice work. You understood most of the lesson."
    else:
        summary = "Good try. Review the lesson once more and try again."
    return {"score": score, "total_questions": total, "results": results, "summary": summary}


def generate_openai_lesson(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    fit_result: dict[str, Any],
) -> tuple[list[tuple[str, Any]] | None, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, "Using standard lesson mode."
    if OpenAI is None:
        return None, "Using standard lesson mode."

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=build_prompt(book, subject, concept, grade, fit_result),
        )
        content = response.output_text.strip()
        return parse_lesson_text(content), ""
    except Exception as exc:  # noqa: BLE001
        return None, "Using standard lesson mode."


def generate_lesson(book: dict[str, Any], subject: str, concept: str, grade: str) -> dict[str, Any]:
    if not str(book.get("abstract", "")).strip():
        return build_missing_abstract_result()

    chosen_concept = concept.strip() or suggest_concept(book, subject)
    fit_result = score_concept_fit(book, subject, chosen_concept)
    sections, fallback_notice = generate_openai_lesson(book, subject, chosen_concept, grade, fit_result)

    if sections is None:
        sections = build_fallback_lesson(book, subject, chosen_concept, grade, fit_result)

    return {
        "warning": build_final_warning(fit_result, fallback_notice),
        "sections": ensure_lesson_structure(sections),
        "chosen_concept": chosen_concept,
        "fit_result": fit_result,
    }
