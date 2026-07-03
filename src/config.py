from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "database" / "library.db"
TMP_DB_PATH = Path(tempfile.gettempdir()) / "library_recom.db"
_DB_PATH_WARNING = ""


def _is_writable_database_path(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
        return True
    except OSError:
        return False


def get_database_path() -> Path:
    global _DB_PATH_WARNING
    configured_path = os.getenv("LIBRARY_DB_PATH", "").strip()
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    candidates.append(DEFAULT_DB_PATH)
    candidates.append(TMP_DB_PATH)

    for candidate in candidates:
        if _is_writable_database_path(candidate):
            if configured_path and candidate != Path(configured_path).expanduser():
                _DB_PATH_WARNING = (
                    f"Configured LIBRARY_DB_PATH '{configured_path}' is not writable. "
                    f"Using fallback database path '{candidate}'."
                )
            else:
                _DB_PATH_WARNING = ""
            return candidate

    _DB_PATH_WARNING = "No writable database location was found. Using the default database path may fail."
    return DEFAULT_DB_PATH


def get_database_warning() -> str:
    return _DB_PATH_WARNING
