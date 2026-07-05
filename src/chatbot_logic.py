from __future__ import annotations


def explain_recommendation(book: dict) -> str:
    simple_reason = str(book.get("simple_recommendation_reason", "")).strip()
    if simple_reason:
        return simple_reason

    title = book.get("title") or "This book"
    reason = str(book.get("recommendation_reason", "")).strip()
    if reason:
        return reason
    return f"{title} was recommended because it matches your overall reading preferences."
