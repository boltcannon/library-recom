from __future__ import annotations

import os
import re
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - depends on local environment
    OpenAI = None

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "book",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "with",
}

LESSON_HEADINGS = [
    "Why this concept fits this book",
    "Simple concept explanation",
    "Examples from this book",
    "Quick reminder",
    "Try it yourself",
    "3 practice questions",
    "Answers",
]

FALLBACK_NOTICE = "Using standard lesson mode."

DEFAULT_SUBJECT_CONCEPTS = {
    "Math": "counting and comparison",
    "Science": "observation and living things",
    "English": "main idea and summarizing",
    "Social Science": "change over time",
    "Values": "courage and responsibility",
}

CONCEPT_PROFILES: dict[str, list[dict[str, Any]]] = {
    "Math": [
        {"concept": "counting", "keywords": ["count", "number", "many", "total", "hundred", "facts", "first", "second", "third"]},
        {"concept": "comparison", "keywords": ["more", "less", "compare", "greater", "smaller", "most", "least", "difference"]},
        {"concept": "percentages", "keywords": ["hundred", "percent", "whole", "share", "ratio", "out of 100"]},
        {"concept": "fractions", "keywords": ["share", "equal", "half", "quarter", "divide"]},
        {"concept": "data handling", "keywords": ["list", "group", "record", "count", "compare", "total", "survey", "facts", "chart", "table"]},
        {"concept": "classification", "keywords": ["group", "sort", "classify", "category", "type", "facts", "list"]},
        {"concept": "patterns", "keywords": ["pattern", "repeat", "sequence", "order"]},
    ],
    "Science": [
        {"concept": "living things", "keywords": ["animal", "plant", "bird", "tree", "life", "living", "grow"]},
        {"concept": "environment", "keywords": ["forest", "river", "water", "earth", "climate", "nature", "environment"]},
        {"concept": "habitats", "keywords": ["habitat", "home", "jungle", "forest", "sea", "nest"]},
        {"concept": "space", "keywords": ["space", "planet", "star", "moon", "sun", "solar"]},
        {"concept": "observation", "keywords": ["notice", "observe", "look", "discover", "find", "explore"]},
    ],
    "English": [
        {"concept": "main idea", "keywords": ["idea", "message", "about", "theme", "focus"]},
        {"concept": "summarizing", "keywords": ["life", "story", "journey", "history", "events", "summary"]},
        {"concept": "biography", "keywords": ["biography", "life", "born", "history", "leader", "person"]},
        {"concept": "sequencing", "keywords": ["first", "next", "then", "after", "before", "journey"]},
        {"concept": "character traits", "keywords": ["friendship", "kindness", "brave", "courage", "leader", "helpful"]},
        {"concept": "key ideas", "keywords": ["important", "main", "key", "facts", "history"]},
    ],
    "Social Science": [
        {"concept": "women in history", "keywords": ["women", "woman", "history", "world", "leader", "change"]},
        {"concept": "change over time", "keywords": ["history", "past", "change", "today", "before", "after"]},
        {"concept": "contribution", "keywords": ["shaped", "built", "helped", "contribution", "influence", "impact"]},
        {"concept": "leadership", "keywords": ["leader", "leadership", "courage", "movement", "voice"]},
        {"concept": "community and society", "keywords": ["community", "people", "society", "roles", "work"]},
    ],
    "Values": [
        {"concept": "courage", "keywords": ["courage", "brave", "risk", "stand", "voice"]},
        {"concept": "leadership", "keywords": ["leader", "leadership", "guide", "change", "inspire"]},
        {"concept": "perseverance", "keywords": ["keep", "continue", "struggle", "effort", "try", "overcome"]},
        {"concept": "kindness", "keywords": ["kind", "care", "help", "share", "friendship"]},
        {"concept": "responsibility", "keywords": ["responsibility", "duty", "work", "serve", "care"]},
    ],
}

SUBJECT_DEFAULT_SUGGESTIONS = {
    "Math": ["counting", "comparison", "data handling"],
    "Science": ["living things", "environment", "observation"],
    "English": ["main idea", "summarizing", "key ideas"],
    "Social Science": ["change over time", "contribution", "community and society"],
    "Values": ["courage", "leadership", "responsibility"],
}


def normalize_text(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_tokens(value: object) -> list[str]:
    return [token for token in normalize_text(value).split() if token and token not in STOPWORDS]


def get_book_source_text(book: dict[str, Any]) -> str:
    return normalize_text(f"{book.get('title', '')} {book.get('abstract', '')}")


def get_grade_profile(grade: str) -> dict[str, str]:
    try:
        grade_value = int(str(grade).strip())
    except (TypeError, ValueError):
        grade_value = 5

    if grade_value <= 3:
        return {"label": f"class {grade_value}", "tone": "very simple, short, and warm"}
    if grade_value <= 6:
        return {"label": f"class {grade_value}", "tone": "simple, clear, and friendly"}
    return {"label": f"class {grade_value}", "tone": "clear, slightly more detailed, and age-appropriate"}


def build_student_adaptive_profile(
    grade: str,
    student_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    grade_profile = get_grade_profile(grade)
    context = student_context or {}
    reading_level = normalize_text(context.get("reading_level", "") or "easy")
    quiz_band = normalize_text(context.get("quiz_band", "") or "growing")
    strongest_concepts = [str(item) for item in context.get("strongest_concepts", []) if str(item).strip()]
    weak_concepts = [str(item) for item in context.get("weak_concepts", []) if str(item).strip()]

    support_mode = "balanced"
    pass_threshold = 60.0
    quiz_depth = "standard"
    reflect_min_words = 6
    activity_min_words = 8

    if quiz_band in {"needs support", "just getting started"} or reading_level == "easy":
        support_mode = "scaffolded"
        pass_threshold = 50.0
        quiz_depth = "guided"
        reflect_min_words = 4
        activity_min_words = 6
    elif quiz_band == "confident" and reading_level in {"medium", "challenging"}:
        support_mode = "stretch"
        pass_threshold = 70.0
        quiz_depth = "stretch"
        reflect_min_words = 8
        activity_min_words = 10

    tone = grade_profile["tone"]
    if support_mode == "scaffolded":
        tone = f"{tone}, with short steps and very direct language"
    elif support_mode == "stretch":
        tone = f"{tone}, with slightly deeper reasoning and clearer subject vocabulary"

    return {
        "grade_profile": grade_profile,
        "reading_level": reading_level,
        "quiz_band": quiz_band or "growing",
        "support_mode": support_mode,
        "pass_threshold": pass_threshold,
        "quiz_depth": quiz_depth,
        "reflect_min_words": reflect_min_words,
        "activity_min_words": activity_min_words,
        "strongest_concepts": strongest_concepts,
        "weak_concepts": weak_concepts,
        "tone": tone,
    }


def extract_numbers(text: str) -> list[int]:
    return [int(value) for value in re.findall(r"\b\d+\b", text)]


def extract_theme_terms(book: dict[str, Any], limit: int = 6) -> list[str]:
    title_tokens = split_tokens(book.get("title", ""))
    abstract_tokens = split_tokens(book.get("abstract", ""))
    ordered = title_tokens + abstract_tokens
    unique_terms: list[str] = []
    for token in ordered:
        if len(token) > 2 and token not in unique_terms:
            unique_terms.append(token)
    return unique_terms[:limit]


def extract_reference_sentence(book: dict[str, Any]) -> str:
    abstract = str(book.get("abstract", "")).strip()
    if not abstract:
        return str(book.get("title", "this book")).strip() or "this book"
    parts = re.split(r"(?<=[.!?])\s+", abstract)
    for part in parts:
        clean = part.strip()
        if clean:
            return clean
    return abstract


def build_book_context_phrase(book: dict[str, Any], limit: int = 3) -> str:
    terms = extract_theme_terms(book, limit=limit)
    if terms:
        return ", ".join(terms)
    return str(book.get("title", "the book")).strip() or "the book"


def get_subject_profiles(subject: str) -> list[dict[str, Any]]:
    return CONCEPT_PROFILES.get(subject, [])


def find_best_profile(subject: str, concept: str) -> dict[str, Any] | None:
    normalized_concept = normalize_text(concept)
    concept_tokens = set(split_tokens(concept))
    best_profile = None
    best_score = -1
    for profile in get_subject_profiles(subject):
        profile_tokens = set(split_tokens(profile["concept"]))
        overlap = len(concept_tokens & profile_tokens)
        contains = 2 if profile["concept"] in normalized_concept or normalized_concept in profile["concept"] else 0
        score = overlap + contains
        if score > best_score:
            best_profile = profile
            best_score = score
    return best_profile


def suggest_concept(book: dict[str, Any], subject: str) -> str:
    return suggest_concepts(book, subject)[0]


def suggest_concepts(book: dict[str, Any], subject: str) -> list[str]:
    source_text = get_book_source_text(book)
    source_tokens = set(split_tokens(source_text))
    numbers = extract_numbers(source_text)
    subject_tags = [normalize_text(tag) for tag in str(book.get("subject_tags", "")).split(",") if tag.strip()]
    suggestions_with_score: list[tuple[int, str]] = []

    for profile in get_subject_profiles(subject):
        keyword_hits = sum(1 for keyword in profile["keywords"] if normalize_text(keyword) in source_text)
        concept_hits = sum(1 for token in split_tokens(profile["concept"]) if token in source_tokens)
        number_bonus = 2 if subject == "Math" and numbers and profile["concept"] in {"counting", "comparison", "percentages", "data handling"} else 0
        tag_bonus = 1 if any(tag in profile["concept"] or profile["concept"] in tag for tag in subject_tags) else 0
        score = keyword_hits * 3 + concept_hits * 2 + number_bonus + tag_bonus
        if score > 0:
            suggestions_with_score.append((score, profile["concept"].title()))

    for fallback in SUBJECT_DEFAULT_SUGGESTIONS.get(subject, []):
        suggestions_with_score.append((0, fallback.title()))

    unique_suggestions: list[str] = []
    for _, suggestion in sorted(suggestions_with_score, key=lambda item: (-item[0], item[1])):
        if suggestion not in unique_suggestions:
            unique_suggestions.append(suggestion)

    if not unique_suggestions:
        return [DEFAULT_SUBJECT_CONCEPTS.get(subject, "Main Idea").title()]
    return unique_suggestions[:3]


def score_concept_fit(book: dict[str, Any], subject: str, concept: str) -> dict[str, Any]:
    source_text = get_book_source_text(book)
    source_tokens = set(split_tokens(source_text))
    chosen_concept = concept.strip() or suggest_concept(book, subject)
    normalized_concept = normalize_text(chosen_concept)
    concept_tokens = split_tokens(chosen_concept)
    suggestions = suggest_concepts(book, subject)
    normalized_suggestions = [normalize_text(item) for item in suggestions]
    profile = find_best_profile(subject, chosen_concept)

    matched_terms = sorted({token for token in concept_tokens if token in source_tokens})
    matched_keywords: list[str] = []
    keyword_hits = 0
    if profile:
        matched_keywords = sorted({keyword for keyword in profile["keywords"] if normalize_text(keyword) in source_text})
        keyword_hits = len(matched_keywords)

    exact_suggestion_match = normalized_concept in normalized_suggestions
    direct_phrase_match = normalized_concept in source_text if normalized_concept else False

    score = 0
    score += 4 if direct_phrase_match else 0
    score += 3 if exact_suggestion_match else 0
    score += min(len(matched_terms), 2) * 2
    score += min(keyword_hits, 3) * 2
    numbers = extract_numbers(source_text)

    title = normalize_text(book.get("title", ""))
    abstract = normalize_text(book.get("abstract", ""))
    biography_history_markers = {"history", "biography", "women", "world", "leader", "leaders", "life", "lives", "past", "change"}
    reference_markers = {"fact", "facts", "list", "record", "table", "information", "ancient", "history", "civilization", "greece"}
    quant_markers = {"number", "count", "share", "half", "quarter", "percent", "compare", "comparison", "data", "total", "hundred", "classify", "group", "sort"}
    source_marker_tokens = source_tokens | set(title.split()) | set(abstract.split())
    concept_profile_bonus_targets = {"counting", "comparison", "data handling", "percentages", "classification"}
    if (
        subject == "Math"
        and profile
        and profile["concept"] in concept_profile_bonus_targets
        and (numbers or source_marker_tokens & reference_markers)
    ):
        score += 3
        if profile["concept"] in {"comparison", "data handling", "classification"} and source_marker_tokens & {"facts", "list", "record", "group", "history", "ancient"}:
            score += 2

    if subject == "Math" and not matched_terms and not matched_keywords and source_marker_tokens & biography_history_markers and not (source_marker_tokens & quant_markers or numbers):
        score -= 2

    if not normalized_concept:
        level = "strong"
    elif score >= 8:
        level = "strong"
    elif score >= 3:
        level = "medium"
    elif score >= 0:
        level = "weak"
    else:
        level = "bad"

    better_concepts = [item for item in suggestions if normalize_text(item) != normalized_concept][:3]
    support_terms = matched_terms + [term for term in matched_keywords if term not in matched_terms]
    support_terms = support_terms[:5]
    fit_reason = ""
    if level in {"strong", "medium"}:
        if support_terms:
            fit_reason = f"This concept connects to words and ideas such as {', '.join(support_terms)}."
        else:
            fit_reason = "This concept fits the main idea of the title and abstract."
        warning = ""
    elif level == "weak":
        if support_terms:
            fit_reason = f"This concept is possible because the book still gives some support through {', '.join(support_terms)}."
        else:
            fit_reason = f"This concept is a lighter match, but the title and abstract still give enough context to teach it simply."
        warning = f"Light match for {chosen_concept}. " + (f"Better choices: {', '.join(better_concepts)}." if better_concepts else "You can still continue.")
    else:
        mismatch_reason = f"The title and abstract point in a different direction, so {chosen_concept} would feel forced here."
        if better_concepts:
            warning = f"{mismatch_reason} Better choices: {', '.join(better_concepts)}."
        else:
            warning = mismatch_reason
        fit_reason = mismatch_reason

    return {
        "level": level,
        "score": score,
        "is_strong": level in {"strong", "medium"},
        "matched_terms": matched_terms,
        "matched_keywords": matched_keywords,
        "fit_reason": fit_reason,
        "warning": warning,
        "suggested_concept": better_concepts[0] if better_concepts else (suggestions[0] if suggestions else chosen_concept),
        "suggested_concepts": better_concepts or suggestions[:3],
    }


def build_prompt(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    fit_result: dict[str, Any],
    student_context: dict[str, Any] | None = None,
) -> str:
    adaptive_profile = build_student_adaptive_profile(grade, student_context)
    grade_profile = adaptive_profile["grade_profile"]
    reference_sentence = extract_reference_sentence(book)
    return f"""
You are creating student-facing learning material.

Rules:
- Use only the book title and abstract below.
- Do not invent extra characters, events, or facts.
- Write directly to the student, not to a teacher.
- Do not say things like "ask students to", "underline the words", or "explain the idea".
- Make the content educationally strong and concrete.
- Keep the language {adaptive_profile["tone"]} for {grade_profile["label"]}.
- The concept fit is {fit_result["level"]}. Support terms: {", ".join(fit_result["matched_terms"] + fit_result["matched_keywords"][:3]) or "none"}.
- Use the book context meaningfully.
- Learning support mode: {adaptive_profile["support_mode"]}.
- Quiz confidence band: {adaptive_profile["quiz_band"]}.

Book title: {book.get("title", "")}
Book abstract: {book.get("abstract", "")}
Reference sentence: {reference_sentence}
Subject: {subject}
Concept: {concept}

Return the lesson in this exact section order:
1. Why this concept fits this book
2. Simple concept explanation
3. Examples from this book
4. Quick reminder
5. Try it yourself
6. 3 practice questions
7. Answers

Requirements:
- Give 2 or 3 real examples.
- Keep practice questions subject-based, not meta.
- Keep answers clear and specific.
""".strip()


def build_missing_abstract_result(book: dict[str, Any], subject: str) -> dict[str, Any]:
    suggestions = suggest_concepts(book, subject)
    warning = "This book does not have enough summary information for a strong story-based lesson."
    sections = [
        ("Why this concept fits this book", "This book does not give enough summary detail to build a strong concept lesson yet."),
        ("Simple concept explanation", "Choose a book with a clearer abstract so the lesson can connect to real book ideas."),
        ("Examples from this book", ["No reliable examples can be created because the abstract is missing."]),
        ("Quick reminder", "A useful lesson needs a book summary that gives real support for the concept."),
        ("Try it yourself", "Pick another book that has a fuller abstract and try again."),
        ("3 practice questions", ["Why is the abstract important?", "What is missing here?", "What should you choose next?"]),
        ("Answers", ["The abstract gives the lesson real support.", "Important summary details are missing.", "Choose a book with a clearer abstract."]),
    ]
    return {
        "warning": f"{warning} Better choices may be: {', '.join(suggestions)}." if suggestions else warning,
        "sections": sections,
        "chosen_concept": "",
        "fit_result": {
            "level": "bad",
            "score": 0,
            "is_strong": False,
            "matched_terms": [],
            "matched_keywords": [],
            "fit_reason": warning,
            "warning": warning,
            "suggested_concept": suggestions[0] if suggestions else "",
            "suggested_concepts": suggestions,
        },
        "mode": "fit_warning",
    }


def _build_math_examples(book: dict[str, Any], concept: str) -> tuple[list[str], list[str], list[str]]:
    source_text = get_book_source_text(book)
    title = str(book.get("title", "this book")).strip() or "this book"
    numbers = extract_numbers(source_text)
    terms = extract_theme_terms(book, limit=4)
    concept_lower = normalize_text(concept)
    examples: list[str] = []
    questions: list[str] = []
    answers: list[str] = []

    main_number = numbers[0] if numbers else max(2, len(terms))
    support_number = numbers[1] if len(numbers) > 1 else max(1, main_number // 2)

    if "percent" in concept_lower:
        percent_value = 25 if main_number >= 25 else 50
        examples = [
            f"The title gives us a total of {main_number}. {percent_value}% of {main_number} means {main_number * percent_value // 100}.",
            f"If half of the group in {title} is studied, that means {main_number // 2} out of {main_number}.",
            f"You can compare {percent_value}% and 50% to decide which part of the whole is larger.",
        ]
        questions = [
            f"What is 50% of {main_number}?",
            f"What is 25% of {main_number}?",
            f"Which is greater: 25% of {main_number} or 50% of {main_number}?",
        ]
        answers = [
            f"50% of {main_number} is {main_number // 2}.",
            f"25% of {main_number} is {main_number * 25 // 100}.",
            f"50% of {main_number} is greater because it is {main_number // 2}, while 25% is {main_number * 25 // 100}.",
        ]
    elif "fraction" in concept_lower or "share" in concept_lower:
        examples = [
            f"If {main_number} items from {title} are shared equally between 2 groups, each group gets {main_number // 2}.",
            f"Half of {main_number} is {main_number // 2}. One quarter of {main_number} is {main_number // 4 if main_number >= 4 else 1}.",
            f"A fraction shows part of a whole. In {title}, the whole group can be thought of as {main_number} items.",
        ]
        questions = [
            f"What is half of {main_number}?",
            f"What is one quarter of {main_number}?",
            f"If {main_number} things are shared between 2 groups, how many are in each group?",
        ]
        answers = [
            f"Half of {main_number} is {main_number // 2}.",
            f"One quarter of {main_number} is {main_number // 4 if main_number >= 4 else 1}.",
            f"Each group gets {main_number // 2}.",
        ]
    elif "data" in concept_lower:
        term_list = terms[:3] or ["idea one", "idea two", "idea three"]
        examples = [
            f"The abstract gives information we can sort into a simple data list: {', '.join(term_list)}.",
            f"If you make one tally mark for each main idea in the abstract, you can compare which kind of idea appears most often.",
            f"Data handling means collecting, organizing, and comparing information from the book.",
        ]
        questions = [
            f"Name one piece of information from the book that could go in a chart.",
            f"How many main ideas are listed here: {', '.join(term_list)}?",
            "Why is a chart useful when we want to compare information?",
        ]
        answers = [
            f"One correct answer is {term_list[0]}.",
            f"There are {len(term_list)} main ideas listed.",
            "A chart helps us organize and compare information clearly.",
        ]
    else:
        examples = [
            f"The title or abstract gives us a total of {main_number}, which we can count and compare.",
            f"If one group has {support_number} and the whole group has {main_number}, then {support_number} is smaller than {main_number}.",
            f"Counting and comparison help us understand how many and which amount is greater or smaller.",
        ]
        questions = [
            f"Which number is greater: {support_number} or {main_number}?",
            f"How many items are in the whole group if the book gives us {main_number}?",
            f"What is the difference between {main_number} and {support_number}?",
        ]
        answers = [
            f"{main_number} is greater.",
            f"The whole group has {main_number} items.",
            f"The difference is {main_number - support_number}.",
        ]

    return examples[:3], questions[:3], answers[:3]


def _build_science_examples(book: dict[str, Any], concept: str) -> tuple[list[str], list[str], list[str]]:
    sentence = extract_reference_sentence(book)
    terms = extract_theme_terms(book, limit=4)
    concept_text = concept.title()
    term_a = terms[0] if terms else "the main science idea"
    term_b = terms[1] if len(terms) > 1 else term_a
    examples = [
        f"The abstract points to science ideas like {', '.join(terms[:3]) or 'the main topic of the book'}. Those ideas help you study {concept_text}.",
        f"When you use {concept_text}, you stay close to this real book detail: {sentence}",
        f"This means your science thinking should explain what you notice, not add facts that the book never gave.",
    ]
    questions = [
        f"What science idea from the abstract connects best to {concept_text}?",
        f"Name one word from the abstract that helps explain {concept_text}.",
        "Why should a science explanation stay close to the book summary?",
    ]
    answers = [
        f"One possible answer is {term_a}, because it comes straight from the abstract and connects to {concept_text}.",
        f"One possible answer is {term_a}. Another good choice could be {term_b}.",
        "It keeps the explanation accurate and based on real information.",
    ]
    return examples, questions, answers


def _build_english_examples(book: dict[str, Any], concept: str) -> tuple[list[str], list[str], list[str]]:
    title = str(book.get("title", "this book")).strip() or "this book"
    sentence = extract_reference_sentence(book)
    concept_lower = normalize_text(concept)
    if "biography" in concept_lower:
        explanation = f"{title} looks like a biography or informational text because it focuses on real people or real events."
    elif "summary" in concept_lower or "main idea" in concept_lower:
        explanation = f"The main idea of {title} comes from the most important message in the abstract."
    else:
        explanation = f"The abstract of {title} gives enough language clues to study {concept}."

    examples = [
        explanation,
        f"A clear sentence from the abstract is: {sentence}",
        f"That detail helps you show {concept} without changing the meaning of the book.",
    ]
    questions = [
        f"What is the main idea of {title}?",
        "Which sentence gives the clearest short summary?",
        "What important information should a good summary keep?",
    ]
    answers = [
        f"A strong answer gives the most important idea in the book, such as: {sentence}",
        f"A good short summary could be: {sentence}",
        "A good summary keeps the main people, topic, or message without adding made-up details.",
    ]
    return examples, questions, answers


def _build_social_science_examples(book: dict[str, Any], concept: str) -> tuple[list[str], list[str], list[str]]:
    sentence = extract_reference_sentence(book)
    title = str(book.get("title", "this book")).strip() or "this book"
    concept_text = concept.title()
    examples = [
        f"{title} connects to {concept_text} because the abstract focuses on real people, events, or changes in society.",
        f"One important detail is: {sentence}",
        f"That detail helps you think about who made a difference, what changed, or why that change mattered.",
    ]
    questions = [
        f"Why does {title} connect to {concept_text}?",
        "What real-life change, role, or contribution is suggested by the abstract?",
        "Why is it important to study real people and events in social science?",
    ]
    answers = [
        f"It connects because the title and abstract point to real people, real events, or change over time.",
        f"One good answer uses the real detail in the abstract: {sentence}",
        "It helps us understand how people and events shape society.",
    ]
    return examples, questions, answers


def _build_values_examples(book: dict[str, Any], concept: str) -> tuple[list[str], list[str], list[str]]:
    sentence = extract_reference_sentence(book)
    concept_text = concept.title()
    examples = [
        f"This book supports {concept_text} when the abstract shows a choice, action, or attitude linked to that value.",
        f"One useful detail is: {sentence}",
        f"That detail helps you think about what someone did and what we can learn from it.",
    ]
    questions = [
        f"What value connects best to this book: {concept_text} or something else?",
        f"What part of the abstract suggests {concept_text}?",
        "How can this value help in everyday life?",
    ]
    answers = [
        f"{concept_text} fits when the abstract shows people sharing, helping, or making caring choices.",
        f"One good answer points to this detail: {sentence}",
        f"It can help someone act with {concept_text.lower()} in school, home, or the community.",
    ]
    return examples, questions, answers


def build_examples_questions_answers(book: dict[str, Any], subject: str, concept: str) -> tuple[list[str], list[str], list[str]]:
    if subject == "Math":
        return _build_math_examples(book, concept)
    if subject == "Science":
        return _build_science_examples(book, concept)
    if subject == "English":
        return _build_english_examples(book, concept)
    if subject == "Social Science":
        return _build_social_science_examples(book, concept)
    return _build_values_examples(book, concept)


def build_concept_explanation(
    subject: str,
    concept: str,
    grade: str,
    student_context: dict[str, Any] | None = None,
) -> str:
    concept_text = concept.title()
    adaptive_profile = build_student_adaptive_profile(grade, student_context)
    support_mode = adaptive_profile["support_mode"]
    if subject == "Math":
        base = f"{concept_text} helps you notice amounts, compare them, and explain your answer with clear number thinking."
    elif subject == "Science":
        base = f"{concept_text} helps you use real details to notice, describe, and explain what is happening in the natural world."
    elif subject == "English":
        base = f"{concept_text} helps you understand the main message of a text and say it clearly in your own words."
    elif subject == "Social Science":
        base = f"{concept_text} helps you understand people, events, and how actions or changes shape communities over time."
    else:
        base = f"{concept_text} helps you notice the choices and actions that matter in real life and why they matter."

    if support_mode == "scaffolded":
        return f"{base} Start with one clear idea from the book, then connect it to the concept in one simple step."
    if support_mode == "stretch":
        return f"{base} Try to explain not only what the concept is, but also why it works in this book context."
    return base


def build_activity(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    student_context: dict[str, Any] | None = None,
) -> str:
    sentence = extract_reference_sentence(book)
    context_phrase = build_book_context_phrase(book)
    adaptive_profile = build_student_adaptive_profile(grade, student_context)
    support_mode = adaptive_profile["support_mode"]
    if subject == "Math":
        prompt = f"Use the book ideas about {context_phrase} to write one math statement with {concept}. After that, explain in one sentence how your math idea matches the book."
    elif subject == "Science":
        prompt = f"Choose two science words or ideas from this line: {sentence} Then write one sentence that shows how they connect to {concept}."
    elif subject == "English":
        prompt = f"Write two sentences that show {concept} in this book. Both sentences must stay close to this idea: {sentence}"
    elif subject == "Social Science":
        prompt = f"Write two lines that use one real detail from the abstract to show {concept} in people, society, or history."
    else:
        prompt = f"Write two lines that show how {concept} appears in this book and why that value matters."
    if support_mode == "scaffolded":
        return prompt + " Keep it short and use one clear book detail."
    if support_mode == "stretch":
        return prompt + " Add one line that explains why your example is a strong concept match."
    return prompt


def build_fit_guidance_sections(book: dict[str, Any], subject: str, concept: str, fit_result: dict[str, Any]) -> list[tuple[str, Any]]:
    suggestions = fit_result.get("suggested_concepts", []) or suggest_concepts(book, subject)
    explanation = fit_result["fit_reason"] or f"The book does not naturally support {concept}."
    return [
        ("Why this concept fits this book", explanation),
        ("Simple concept explanation", f"This is not a strong match for {concept}, so a normal lesson would feel forced."),
        ("Examples from this book", [f"Better concepts for this book: {', '.join(suggestions)}"] if suggestions else ["Choose a different concept or another book."]),
        ("Quick reminder", "Choose a concept that the title and abstract support more clearly."),
        ("Try it yourself", "Pick one of the suggested concepts and create the lesson again."),
        ("3 practice questions", ["Why is this concept a weak match?", "What does the title or abstract support more clearly?", "Which better concept would you choose next?"]),
        ("Answers", ["Because the title and abstract do not support it well.", "A correct answer names the stronger idea in the book.", "A correct answer picks one of the suggested concepts."]),
    ]


def build_fallback_lesson(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    fit_result: dict[str, Any],
    student_context: dict[str, Any] | None = None,
) -> list[tuple[str, Any]]:
    title = str(book.get("title", "this book")).strip() or "this book"
    reference_sentence = extract_reference_sentence(book)
    examples, questions, answers = build_examples_questions_answers(book, subject, concept)
    support_terms = fit_result.get("matched_terms", []) + fit_result.get("matched_keywords", [])
    support_text = ", ".join(dict.fromkeys(support_terms[:4])) if support_terms else "the main ideas in the title and abstract"
    context_phrase = build_book_context_phrase(book)
    if fit_result["level"] == "strong":
        why_fit = f"{title} fits {concept} because the title and abstract connect to {support_text}."
    elif fit_result["level"] == "medium":
        why_fit = f"{title} can support {concept} because the abstract gives enough clues through {support_text}."
    else:
        why_fit = f"{title} is a lighter match for {concept}, but it still gives enough context through {support_text}."
    concept_explanation = build_concept_explanation(subject, concept, grade, student_context)
    example_lines = examples[:3]
    reminder = f"Remember: keep using real book ideas such as {context_phrase} while you practice {concept.title()}."
    activity = build_activity(book, subject, concept, grade, student_context)
    return [
        ("Why this concept fits this book", why_fit),
        ("Simple concept explanation", f"{concept_explanation} In this book, the key idea we are using is: {reference_sentence}"),
        ("Examples from this book", example_lines),
        ("Quick reminder", reminder),
        ("Try it yourself", activity),
        ("3 practice questions", questions[:3]),
        ("Answers", answers[:3]),
    ]


def split_lines_as_list(value: str) -> list[str]:
    items = [line.strip("- ").strip() for line in value.splitlines() if line.strip()]
    return items


def build_support_terms(book: dict[str, Any], fit_result: dict[str, Any]) -> list[str]:
    support_terms = fit_result.get("matched_terms", []) + fit_result.get("matched_keywords", [])
    theme_terms = extract_theme_terms(book, limit=6)
    ordered_terms: list[str] = []
    for term in support_terms + theme_terms:
        normalized = normalize_text(term)
        if normalized and normalized not in ordered_terms:
            ordered_terms.append(normalized)
    return ordered_terms[:6]


def build_keyword_feedback(answer: str, expected_terms: list[str]) -> dict[str, Any]:
    answer_tokens = set(split_tokens(answer))
    matched = [term for term in expected_terms if any(token in answer_tokens for token in split_tokens(term))]
    missing = [term for term in expected_terms if term not in matched]
    return {
        "matched_terms": matched,
        "missing_terms": missing,
    }


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
        return [("Why this concept fits this book", content.strip() or "Lesson content could not be parsed.")]

    return ensure_lesson_structure(sections)


def format_section_body(section_title: str, body: str) -> Any:
    if section_title in {"Examples from this book", "3 practice questions", "Answers"}:
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
            if heading in {"Examples from this book", "3 practice questions", "Answers"}:
                fallback_body = ["This section needs review."]
            else:
                fallback_body = "This section needs review."
            ordered_sections.append((heading, fallback_body))
    return ordered_sections


def build_final_warning(fit_result: dict[str, Any], fallback_notice: str) -> str:
    parts = []
    if fit_result["warning"] and fit_result["level"] in {"weak", "bad"}:
        parts.append(fit_result["warning"])
    if fallback_notice and fit_result["level"] in {"strong", "medium", "weak"}:
        parts.append(fallback_notice)
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


def generate_quiz_questions(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    fit_result: dict[str, Any],
) -> list[dict[str, Any]]:
    if fit_result["level"] == "bad":
        return []

    examples, questions, answers = build_examples_questions_answers(book, subject, concept)
    options_pool = {
        "Math": ["A story detail with no numbers", "A made-up answer", "The correct number idea from the lesson"],
        "Science": ["A guessed idea", "A real science idea from the abstract", "A random opinion"],
        "English": ["The main idea from the lesson", "A made-up plot twist", "A fact from another book"],
        "Social Science": ["A real contribution or change", "A made-up event", "A science experiment"],
        "Values": ["A real value from the lesson", "A random action with no connection", "A math formula"],
    }

    quiz_items: list[dict[str, Any]] = []
    for question, answer in zip(questions[:3], answers[:3]):
        distractors = [item for item in options_pool.get(subject, []) if item != answer][:2]
        options = [answer] + distractors
        unique_options: list[str] = []
        for option in options:
            if option not in unique_options:
                unique_options.append(option)
        while len(unique_options) < 3:
            unique_options.append(f"Another possible answer choice {len(unique_options) + 1}")
        quiz_items.append(
            {
                "question": question,
                "options": unique_options[:3],
                "answer": answer,
                "feedback": answer,
            }
        )
    return quiz_items


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
    student_context: dict[str, Any] | None = None,
) -> tuple[list[tuple[str, Any]] | None, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return None, FALLBACK_NOTICE

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=build_prompt(book, subject, concept, grade, fit_result, student_context),
        )
        content = response.output_text.strip()
        return parse_lesson_text(content), ""
    except Exception:  # noqa: BLE001
        return None, FALLBACK_NOTICE


def generate_lesson(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    student_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not str(book.get("abstract", "")).strip():
        return build_missing_abstract_result(book, subject)

    chosen_concept = concept.strip() or suggest_concept(book, subject)
    fit_result = score_concept_fit(book, subject, chosen_concept)

    if fit_result["level"] == "bad":
        return {
            "warning": build_final_warning(fit_result, ""),
            "sections": build_fit_guidance_sections(book, subject, chosen_concept, fit_result),
            "chosen_concept": chosen_concept,
            "fit_result": fit_result,
            "mode": "fit_warning",
        }

    sections, fallback_notice = generate_openai_lesson(book, subject, chosen_concept, grade, fit_result, student_context)
    if sections is None:
        sections = build_fallback_lesson(book, subject, chosen_concept, grade, fit_result, student_context)

    return {
        "warning": build_final_warning(fit_result, fallback_notice),
        "sections": ensure_lesson_structure(sections),
        "chosen_concept": chosen_concept,
        "fit_result": fit_result,
        "mode": "lesson",
    }


def generate_open_ended_question(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    fit_result: dict[str, Any],
    student_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reference_sentence = extract_reference_sentence(book)
    support_terms = build_support_terms(book, fit_result)
    adaptive_profile = build_student_adaptive_profile(grade, student_context)
    support_mode = adaptive_profile["support_mode"]
    concept_text = concept.title()
    if subject == "Math":
        prompt = f"Using this book detail, show how {concept_text} helps you think clearly: {reference_sentence}"
    elif subject == "Science":
        prompt = f"Which science idea in this line connects best to {concept_text}, and why? {reference_sentence}"
    elif subject == "English":
        prompt = f"How does this line help you show {concept_text} clearly? {reference_sentence}"
    elif subject == "Social Science":
        prompt = f"What does this book detail teach you about {concept_text}? {reference_sentence}"
    else:
        prompt = f"What action, choice, or attitude in this line shows {concept_text}? {reference_sentence}"
    if support_mode == "scaffolded":
        prompt += " Use 1 or 2 short sentences."
    elif support_mode == "stretch":
        prompt += " Try to explain your thinking clearly, not just name the concept."
    return {
        "prompt": prompt,
        "expected_terms": support_terms[:4] or split_tokens(concept) or ["book"],
    }


def evaluate_open_ended_feedback(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    fit_result: dict[str, Any],
    answer: str,
    student_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adaptive_profile = build_student_adaptive_profile(grade, student_context)
    support_terms = build_support_terms(book, fit_result)[:4] or split_tokens(concept)
    keyword_feedback = build_keyword_feedback(answer, support_terms)
    matched_terms = keyword_feedback["matched_terms"]
    missing_terms = keyword_feedback["missing_terms"]
    answer_length = len(split_tokens(answer))
    if answer_length == 0:
        return {
            "what_is_correct": "You have not added an answer yet.",
            "what_is_missing": f"Try to explain {concept} using one real idea from the title or abstract.",
            "hint": "Use one word or idea from the book, then connect it to the concept.",
            "encouragement": "You can do this. Start with one simple sentence.",
            "is_complete": False,
        }
    context_phrase = build_book_context_phrase(book, limit=2)
    what_is_correct = (
        f"You connected {concept} to book ideas like {', '.join(matched_terms[:2])}."
        if matched_terms
        else f"You made a start by writing about {concept}."
    )
    what_is_missing = (
        f"To make it stronger, add one clear book detail such as {', '.join(missing_terms[:2])}."
        if missing_terms[:2]
        else f"Now make the link clearer by saying exactly how {concept} works in the book."
    )
    hint = (
        f"Hint: use one book idea like {', '.join(missing_terms[:2])}, then connect it directly to {concept}."
        if missing_terms[:2]
        else f"Hint: mention {context_phrase} and then explain why it shows {concept}."
    )
    encouragement = "Nice thinking. Your answer is moving in the right direction."
    if adaptive_profile["support_mode"] == "stretch":
        encouragement = "Strong start. Push your answer one step further by explaining the reason clearly."
    elif adaptive_profile["support_mode"] == "scaffolded":
        encouragement = "Good start. One more clear book detail will make this even better."
    is_complete = bool(matched_terms) and answer_length >= int(adaptive_profile["reflect_min_words"]) and ("because" in normalize_text(answer) or answer_length >= int(adaptive_profile["reflect_min_words"]) + 2)
    return {
        "what_is_correct": what_is_correct,
        "what_is_missing": what_is_missing,
        "hint": hint,
        "encouragement": encouragement,
        "is_complete": is_complete,
    }


def generate_applied_activity(
    book: dict[str, Any],
    subject: str,
    concept: str,
    fit_result: dict[str, Any],
    grade: str,
    student_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    examples, _, answers = build_examples_questions_answers(book, subject, concept)
    prompt = build_activity(book, subject, concept, grade, student_context)
    return {
        "prompt": prompt,
        "sample_answer": answers[0] if answers else examples[0] if examples else f"Use the title and abstract to show {concept}.",
        "expected_terms": build_support_terms(book, fit_result)[:4] or split_tokens(concept),
        "expected_steps": split_tokens(concept)[:2] or [normalize_text(concept)],
    }


def evaluate_activity_feedback(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    fit_result: dict[str, Any],
    answer: str,
    student_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adaptive_profile = build_student_adaptive_profile(grade, student_context)
    support_terms = build_support_terms(book, fit_result)[:4] or split_tokens(concept)
    keyword_feedback = build_keyword_feedback(answer, support_terms)
    matched_terms = keyword_feedback["matched_terms"]
    missing_terms = keyword_feedback["missing_terms"]
    answer_length = len(split_tokens(answer))
    concept_tokens = split_tokens(concept)
    concept_seen = any(token in split_tokens(answer) for token in concept_tokens) if concept_tokens else True
    if answer_length == 0:
        return {
            "what_is_correct": "You have not submitted the activity answer yet.",
            "what_can_improve": f"Use the book context to apply {concept} in one clear example.",
            "hint": "Start with one fact, idea, or number from the book and use it in the activity.",
            "encouragement": "Try one simple attempt first. You can improve it after that.",
            "is_complete": False,
        }
    context_phrase = build_book_context_phrase(book, limit=2)
    encouragement = "Good effort. You are close to a strong applied answer."
    if adaptive_profile["support_mode"] == "stretch":
        encouragement = "Good effort. Add a clearer explanation of why your example proves the concept."
    elif adaptive_profile["support_mode"] == "scaffolded":
        encouragement = "Good effort. Keep it simple and add one stronger book detail."
    return {
        "what_is_correct": (
            f"You used helpful book ideas like {', '.join(matched_terms[:2])}."
            if matched_terms
            else f"You tried to apply {concept}, which is a good start."
        ),
        "what_can_improve": (
            f"Make the answer stronger by including {', '.join(missing_terms[:2])} and showing the concept step clearly."
            if missing_terms[:2]
            else f"Add one short line that explains how your answer shows {concept}."
        ),
        "hint": (
            f"Hint: include {', '.join(missing_terms[:2])} and say how it helps you use {concept}."
            if missing_terms[:2]
            else f"Hint: use words like {context_phrase} and then show the concept in action."
        ),
        "encouragement": encouragement,
        "is_complete": bool(matched_terms) and concept_seen and answer_length >= int(adaptive_profile["activity_min_words"]),
    }


def generate_sequence_quiz(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    fit_result: dict[str, Any],
    student_context: dict[str, Any] | None = None,
    *,
    simplified: bool = False,
) -> list[dict[str, Any]]:
    examples, questions, answers = build_examples_questions_answers(book, subject, concept)
    support_terms = build_support_terms(book, fit_result)
    adaptive_profile = build_student_adaptive_profile(grade, student_context)
    quiz_items: list[dict[str, Any]] = []
    if simplified or adaptive_profile["support_mode"] == "scaffolded":
        mcq_count = 2
    elif adaptive_profile["support_mode"] == "stretch":
        mcq_count = min(3, len(questions))
    else:
        mcq_count = 3

    for question, answer in zip(questions[:mcq_count], answers[:mcq_count]):
        distractors = [item for item in answers[:mcq_count] if item != answer][:2]
        if len(distractors) < 2:
            distractors.extend([example for example in examples if example != answer][: 2 - len(distractors)])
        options = [answer] + distractors
        unique_options: list[str] = []
        for option in options:
            if option and option not in unique_options:
                unique_options.append(option)
        while len(unique_options) < 3:
            unique_options.append(f"Another choice about {concept}")
        quiz_items.append(
            {
                "question_type": "mcq",
                "question": question,
                "options": unique_options[:3],
                "answer": answer,
                "feedback": answer,
                "pass_threshold": adaptive_profile["pass_threshold"],
                "difficulty_label": adaptive_profile["quiz_depth"],
            }
        )

    short_prompt = (
        f"In one or two sentences, explain how {concept} is used with one real idea from the book."
        if not simplified
        else f"Write one short sentence that uses {concept} with one real book idea."
    )
    if adaptive_profile["support_mode"] == "stretch" and not simplified:
        short_prompt = f"In two short sentences, explain how {concept} works in this book and why that connection makes sense."
    quiz_items.append(
        {
            "question_type": "short",
            "question": short_prompt,
            "answer": f"A good answer mentions {concept} and a real idea such as {', '.join(support_terms[:2]) or 'the title or abstract'}.",
            "concept_terms": split_tokens(concept),
            "expected_terms": support_terms[:3] or split_tokens(concept),
            "feedback": f"Use the concept and one real book idea like {', '.join(support_terms[:2]) or concept}.",
            "pass_threshold": adaptive_profile["pass_threshold"],
            "difficulty_label": adaptive_profile["quiz_depth"],
        }
    )
    return quiz_items


def score_sequence_quiz(questions: list[dict[str, Any]], answers: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    score = 0
    for index, question in enumerate(questions):
        selected = answers[index].strip() if index < len(answers) and isinstance(answers[index], str) else ""
        if question.get("question_type") == "short":
            expected_terms = [normalize_text(term) for term in question.get("expected_terms", [])]
            keyword_feedback = build_keyword_feedback(selected, expected_terms)
            matched_terms = keyword_feedback["matched_terms"]
            concept_terms = question.get("concept_terms", [])
            concept_seen = any(token in split_tokens(selected) for token in concept_terms) if concept_terms else True
            is_correct = bool(matched_terms) and len(split_tokens(selected)) >= 4 and concept_seen
            feedback = (
                f"You included strong ideas like {', '.join(matched_terms[:2])} and used the concept clearly."
                if is_correct
                else question.get("feedback", "Add the concept and one real book idea.")
            )
        else:
            is_correct = selected == question["answer"]
            feedback = question["feedback"] if is_correct else f"Check the concept again. The better answer is: {question['answer']}"
        if is_correct:
            score += 1
        results.append(
            {
                "question": question["question"],
                "selected_answer": selected,
                "correct_answer": question["answer"],
                "is_correct": is_correct,
                "feedback": feedback,
                "question_type": question.get("question_type", "mcq"),
            }
        )

    total = len(questions)
    percentage = round((score / total) * 100, 1) if total else 0.0
    pass_threshold = float(questions[0].get("pass_threshold", 60.0)) if questions else 60.0
    passed = percentage >= pass_threshold
    review_summary = (
        "You passed the learning check. Keep using the same book idea and concept connection."
        if passed
        else "Review the concept, the key examples, and one real book detail before trying again."
    )
    summary = "Great work. You passed the quiz." if passed else "Good try. Review the lesson and try the quiz again."
    return {
        "score": score,
        "total_questions": total,
        "percentage": percentage,
        "pass_threshold": pass_threshold,
        "passed": passed,
        "results": results,
        "summary": summary,
        "review_summary": review_summary,
    }


def learning_sequence_to_text(sequence: dict[str, Any]) -> str:
    teach_sections = sequence.get("teach_sections", [])
    blocks = [lesson_sections_to_text(teach_sections)]
    reflect = sequence.get("reflect_question", {})
    activity = sequence.get("activity", {})
    quiz = sequence.get("quiz_questions", [])
    if reflect.get("prompt"):
        blocks.append(f"Reflect\n{reflect['prompt']}")
    if activity.get("prompt"):
        blocks.append(f"Practice\n{activity['prompt']}")
    if quiz:
        blocks.append(f"Quiz\n{len(quiz)} final check questions are included in the learning sequence.")
    return "\n\n".join(blocks)


def generate_learning_sequence(
    book: dict[str, Any],
    subject: str,
    concept: str,
    grade: str,
    student_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adaptive_profile = build_student_adaptive_profile(grade, student_context)
    lesson = generate_lesson(book, subject, concept, grade, student_context)
    chosen_concept = lesson.get("chosen_concept", concept.strip())
    fit_result = lesson.get("fit_result", {})
    if lesson.get("mode") == "fit_warning":
        return {
            **lesson,
            "teach_sections": lesson.get("sections", []),
            "reflect_question": None,
            "activity": None,
            "quiz_questions": [],
            "sequence_text": lesson_sections_to_text(lesson.get("sections", [])),
            "adaptive_profile": adaptive_profile,
        }

    reflect_question = generate_open_ended_question(book, subject, chosen_concept, grade, fit_result, student_context)
    activity = generate_applied_activity(book, subject, chosen_concept, fit_result, grade, student_context)
    quiz_questions = generate_sequence_quiz(book, subject, chosen_concept, grade, fit_result, student_context, simplified=False)
    sequence = {
        "warning": lesson["warning"],
        "teach_sections": lesson["sections"],
        "chosen_concept": chosen_concept,
        "fit_result": fit_result,
        "mode": lesson.get("mode", "lesson"),
        "adaptive_profile": adaptive_profile,
        "reflect_question": reflect_question,
        "activity": activity,
        "quiz_questions": quiz_questions,
    }
    sequence["sequence_text"] = learning_sequence_to_text(sequence)
    return sequence
