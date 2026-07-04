from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import re
from typing import Final

from passlib.context import CryptContext

PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
ALLOWED_ROLES = {"student", "teacher", "admin"}
MAX_PASSWORD_BYTES: Final[int] = 1024
PBKDF2_ITERATIONS: Final[int] = 390000
PBKDF2_SCHEME: Final[str] = "pbkdf2_sha256"


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


def _pbkdf2_hash(password: str, *, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    password_bytes = password.encode("utf-8")
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password_bytes, salt_bytes, iterations)
    salt_token = base64.urlsafe_b64encode(salt_bytes).decode("ascii")
    digest_token = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{PBKDF2_SCHEME}${iterations}${salt_token}${digest_token}"


def _verify_pbkdf2_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_token, digest_token = password_hash.split("$", 3)
        if scheme != PBKDF2_SCHEME:
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_token.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(digest_token.encode("ascii"))
    except (TypeError, ValueError):
        return False

    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def hash_password(password: str) -> str:
    return _pbkdf2_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith(f"{PBKDF2_SCHEME}$"):
        return _verify_pbkdf2_password(password, password_hash)

    try:
        return PASSWORD_CONTEXT.verify(password, password_hash)
    except ValueError:
        return False
