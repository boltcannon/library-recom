from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "database" / "library.db"
TMP_DB_PATH = Path(tempfile.gettempdir()) / "library_recom.db"


@dataclass(frozen=True)
class DatabaseConfig:
    backend: str
    database_url: str | None = None
    sqlite_path: Path | None = None

    @property
    def is_postgres(self) -> bool:
        return self.backend == "postgresql"

    @property
    def is_sqlite(self) -> bool:
        return self.backend == "sqlite"


def _is_writable_database_path(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
        return True
    except OSError:
        return False


def _resolve_local_sqlite_path() -> Path:
    configured_path = os.getenv("LIBRARY_DB_PATH", "").strip()
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    candidates.append(DEFAULT_DB_PATH)
    candidates.append(TMP_DB_PATH)

    for candidate in candidates:
        if _is_writable_database_path(candidate):
            return candidate

    logger.warning("No writable SQLite database location was found. Falling back to the default path.")
    return DEFAULT_DB_PATH


def get_database_config() -> DatabaseConfig:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return DatabaseConfig(backend="postgresql", database_url=database_url)

    return DatabaseConfig(backend="sqlite", sqlite_path=_resolve_local_sqlite_path())
