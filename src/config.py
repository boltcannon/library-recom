from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "database" / "library.db"


def get_database_path() -> Path:
    configured_path = os.getenv("LIBRARY_DB_PATH", "").strip()
    return Path(configured_path).expanduser() if configured_path else DEFAULT_DB_PATH
