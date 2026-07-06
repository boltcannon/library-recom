from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT_SECONDS = 20


class RecommendationAPIError(RuntimeError):
    pass


@dataclass
class RecommendationChatResponse:
    session_id: str
    assistant_message: str
    recommendations: list[Any]
    raw_payload: dict[str, Any]


def create_client_session_id() -> str:
    return str(uuid.uuid4())


def _extract_session_id(payload: Any, fallback_session_id: str) -> str:
    if isinstance(payload, dict):
        for key in ("session_id", "conversation_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for nested_key in ("data", "conversation", "result"):
            nested_value = payload.get(nested_key)
            if isinstance(nested_value, dict):
                nested_session_id = _extract_session_id(nested_value, "")
                if nested_session_id:
                    return nested_session_id
    return fallback_session_id


def _extract_assistant_message(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("message", "reply", "response", "assistant_message", "answer", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for nested_key in ("data", "conversation", "result"):
            nested_value = payload.get(nested_key)
            if nested_value is not None:
                nested_message = _extract_assistant_message(nested_value)
                if nested_message:
                    return nested_message
        messages = payload.get("messages")
        if isinstance(messages, list):
            for item in reversed(messages):
                if isinstance(item, dict):
                    role = str(item.get("role", "")).lower()
                    content = item.get("content")
                    if role in {"assistant", "bot", "system"} and isinstance(content, str) and content.strip():
                        return content.strip()
    if isinstance(payload, list):
        for item in reversed(payload):
            nested_message = _extract_assistant_message(item)
            if nested_message:
                return nested_message
    return ""


def _extract_recommendations(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        for key in ("recommendations", "books", "suggested_books", "results", "matches"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        for nested_key in ("data", "conversation", "result"):
            nested_value = payload.get(nested_key)
            if nested_value is not None:
                nested_recommendations = _extract_recommendations(nested_value)
                if nested_recommendations:
                    return nested_recommendations
    return []


def send_recommendation_message(base_url: str, message: str, session_id: str) -> RecommendationChatResponse:
    try:
        response = requests.post(
            f"{base_url}/book-suggestor/conversation",
            json={"message": message, "session_id": session_id},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        LOGGER.warning("Recommendation API request failed", exc_info=exc)
        raise RecommendationAPIError("Recommendation service is unavailable right now.") from exc
    except ValueError as exc:
        LOGGER.warning("Recommendation API returned a non-JSON response", exc_info=exc)
        raise RecommendationAPIError("Recommendation service returned an unexpected response.") from exc

    resolved_session_id = _extract_session_id(payload, session_id)
    assistant_message = _extract_assistant_message(payload) or "I checked the recommendation service for you."
    recommendations = _extract_recommendations(payload)
    return RecommendationChatResponse(
        session_id=resolved_session_id,
        assistant_message=assistant_message,
        recommendations=recommendations,
        raw_payload=payload if isinstance(payload, dict) else {"payload": payload},
    )


def delete_recommendation_session(base_url: str, session_id: str) -> None:
    try:
        response = requests.delete(
            f"{base_url}/book-suggestor/conversation/{session_id}",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.warning("Recommendation API session delete failed", exc_info=exc)
        raise RecommendationAPIError("The recommendation chat could not be reset right now.") from exc
