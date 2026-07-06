from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT_SECONDS = 20


class RecommendationAPIError(RuntimeError):
    def __init__(self, user_message: str, *, should_reset_session: bool = False):
        super().__init__(user_message)
        self.user_message = user_message
        self.should_reset_session = should_reset_session


@dataclass
class RecommendationChatResponse:
    session_id: str
    assistant_message: str
    recommendations: list[Any]
    raw_payload: dict[str, Any]
    had_partial_payload: bool = False


def create_client_session_id() -> str:
    return str(uuid.uuid4())


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_flatten_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "reply", "response", "answer", "value"):
            text_value = _flatten_text(value.get(key))
            if text_value:
                return text_value
        if "parts" in value:
            return _flatten_text(value.get("parts"))
    return ""


def _walk_payload(payload: Any) -> list[Any]:
    items: list[Any] = [payload]
    if isinstance(payload, dict):
        for value in payload.values():
            items.extend(_walk_payload(value))
    elif isinstance(payload, list):
        for item in payload:
            items.extend(_walk_payload(item))
    return items


def _extract_session_id(payload: Any, fallback_session_id: str) -> str:
    for item in _walk_payload(payload):
        if isinstance(item, dict):
            for key in ("session_id", "conversation_id", "id"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return fallback_session_id


def _extract_assistant_message(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()

    for item in _walk_payload(payload):
        if isinstance(item, dict):
            role = str(item.get("role", "")).lower().strip()
            if role in {"assistant", "bot", "system"}:
                role_text = _flatten_text(item.get("content"))
                if role_text:
                    return role_text

            for key in ("assistant_message", "reply", "response", "answer", "message", "text"):
                text_value = _flatten_text(item.get(key))
                if text_value:
                    return text_value

    flattened = _flatten_text(payload)
    return flattened


def _looks_like_book_record(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    keys = {str(key).lower() for key in item.keys()}
    return bool(keys & {"title", "book_title", "name", "author", "isbn", "item_type"})


def _extract_recommendations(payload: Any) -> list[Any]:
    for item in _walk_payload(payload):
        if isinstance(item, dict):
            for key in ("recommendations", "books", "suggested_books", "matches", "catalog_matches"):
                value = item.get(key)
                if isinstance(value, list):
                    return value

            results_value = item.get("results")
            if isinstance(results_value, list) and any(_looks_like_book_record(entry) or isinstance(entry, str) for entry in results_value):
                return results_value

    if isinstance(payload, list) and any(_looks_like_book_record(entry) or isinstance(entry, str) for entry in payload):
        return payload
    return []


def _response_payload_from_http_response(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raw_text = response.text.strip()
        if not raw_text:
            raise
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            return {"message": raw_text}


def _message_for_http_status(status_code: int) -> tuple[str, bool]:
    if status_code in {400, 404, 409, 410, 422}:
        return ("The recommendation chat got out of sync, so StoryShelf will start a fresh chat for you.", True)
    if status_code in {429, 502, 503, 504}:
        return ("The recommendation service is busy right now. StoryShelf can still suggest books from your library here.", False)
    return ("The recommendation service is unavailable right now.", False)


def send_recommendation_message(base_url: str, message: str, session_id: str) -> RecommendationChatResponse:
    try:
        response = requests.post(
            f"{base_url}/book-suggestor/conversation",
            json={"message": message, "session_id": session_id},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        LOGGER.warning("Recommendation API request timed out", exc_info=exc)
        raise RecommendationAPIError("The recommendation service took too long to reply.", should_reset_session=False) from exc
    except requests.RequestException as exc:
        LOGGER.warning("Recommendation API request failed before response", exc_info=exc)
        raise RecommendationAPIError("The recommendation service is unavailable right now.", should_reset_session=False) from exc

    if not response.ok:
        user_message, should_reset_session = _message_for_http_status(response.status_code)
        LOGGER.warning(
            "Recommendation API returned HTTP %s with body: %s",
            response.status_code,
            response.text[:600],
        )
        raise RecommendationAPIError(user_message, should_reset_session=should_reset_session)

    try:
        payload = _response_payload_from_http_response(response)
    except ValueError as exc:
        LOGGER.warning("Recommendation API returned an unreadable response body", exc_info=exc)
        raise RecommendationAPIError("The recommendation service returned something unexpected.", should_reset_session=False) from exc

    resolved_session_id = _extract_session_id(payload, session_id)
    assistant_message = _extract_assistant_message(payload) or "I checked the recommendation service for you."
    recommendations = _extract_recommendations(payload)
    had_partial_payload = not bool(recommendations) or not bool(assistant_message.strip())

    return RecommendationChatResponse(
        session_id=resolved_session_id,
        assistant_message=assistant_message.strip() or "I checked the recommendation service for you.",
        recommendations=recommendations,
        raw_payload=payload if isinstance(payload, dict) else {"payload": payload},
        had_partial_payload=had_partial_payload,
    )


def delete_recommendation_session(base_url: str, session_id: str) -> None:
    try:
        response = requests.delete(
            f"{base_url}/book-suggestor/conversation/{session_id}",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        LOGGER.warning("Recommendation API session delete timed out", exc_info=exc)
        raise RecommendationAPIError("The recommendation chat could not be reset right now.") from exc
    except requests.RequestException as exc:
        LOGGER.warning("Recommendation API session delete failed before response", exc_info=exc)
        raise RecommendationAPIError("The recommendation chat could not be reset right now.") from exc

    if response.status_code in {404, 410}:
        LOGGER.info("Recommendation chat session %s was already gone on the backend.", session_id)
        return
    if not response.ok:
        LOGGER.warning(
            "Recommendation API session delete returned HTTP %s with body: %s",
            response.status_code,
            response.text[:400],
        )
        raise RecommendationAPIError("The recommendation chat could not be reset right now.")
