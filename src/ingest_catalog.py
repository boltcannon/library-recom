from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import pandas as pd

from src.config import DatabaseConfig
from src.database import BOOK_COLUMNS, replace_books
from src.utils import clean_catalog_dataframe, detect_tags, infer_length_type, infer_reading_level, list_to_text


def ingest_catalog(uploaded_file: str | Path | BinaryIO, db_config: DatabaseConfig) -> dict[str, object]:
    try:
        raw_df = pd.read_excel(uploaded_file, engine="openpyxl")
    except ImportError as exc:
        raise RuntimeError("Excel upload needs openpyxl to be installed.") from exc
    except ValueError as exc:
        raise RuntimeError("The uploaded file could not be read as an Excel sheet.") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Catalog upload failed: {exc}") from exc

    if raw_df.empty:
        raise RuntimeError("The uploaded Excel file is empty.")

    cleaned_df = clean_catalog_dataframe(raw_df)

    enriched_df = cleaned_df.copy()
    enriched_df["length_type"] = enriched_df["pages"].apply(infer_length_type)
    enriched_df["reading_level"] = enriched_df.apply(
        lambda row: infer_reading_level(row["pages"], f"{row['title']} {row['abstract']}"),
        axis=1,
    )

    tag_values = enriched_df.apply(
        lambda row: detect_tags(row["title"], row["abstract"], row["item_type"]),
        axis=1,
    )
    enriched_df["genre_tags"] = tag_values.apply(lambda tags: list_to_text(tags[0]))
    enriched_df["subject_tags"] = tag_values.apply(lambda tags: list_to_text(tags[1]))

    catalog_df = enriched_df.reindex(columns=BOOK_COLUMNS, fill_value="")
    imported_count = replace_books(db_config, catalog_df)

    preview_columns = [
        "title",
        "author",
        "item_type",
        "pages",
        "length_type",
        "genre_tags",
        "subject_tags",
    ]
    return {
        "imported_count": imported_count,
        "columns": list(cleaned_df.columns),
        "preview": enriched_df[preview_columns].head(10),
    }
