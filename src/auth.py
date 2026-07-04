from __future__ import annotations

import re
from typing import Final

from passlib.context import CryptContext

PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
ALLOWED_ROLES = {"student", "teacher", "admin"}
MAX_PASSWORD_BYTES: Final[int] = 1024


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.match(normalize_email(email)))


def validate_password_rules(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return "Password is too long. Please keep it under 1024 bytes."
    if not any(char.isupper() for char in password):
        return "Password must include at least one uppercase letter."
    if not any(char.islower() for char in password):
        return "Password must include at least one lowercase letter."
    if not any(char.isdigit() for char in password):
        return "Password must include at least one number."
    return None


def hash_password(password: str) -> str:
    return PASSWORD_CONTEXT.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORD_CONTEXT.verify(password, password_hash)
    except ValueError:
        return False
