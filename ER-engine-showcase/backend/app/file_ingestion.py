from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd
from fastapi import UploadFile


# Complete internal schema expected by the downstream RF2 pipeline.
OUTPUT_COLUMNS = [
    "ID",
    "Price",
    "Type",
    "Energy.Score",
    "Net.Area",
    "Floor",
    "District",
    "Street",
    "Neighborhood",
    "Furnished",
    "Partly.Furnished",
    "Wheelchair",
    "Elevator",
    "Balcony",
    "Terrace",
    "Loggia",
    "Swimming.pool",
    "Basement",
    "Parking",
    "Garage",
    "Building.material",
    "Renovation",
    "Date.Published",
    "Date.Modified",
    "Agency",
    "Agency_Contact",
    "lat",
    "lon",
]

# Columns that a public user must actually provide.
#
# ID is generated automatically when absent.
# lat/lon are internal legacy RF2 fields and are supplied automatically.
USER_REQUIRED_COLUMNS = [
    column
    for column in OUTPUT_COLUMNS
    if column not in {"ID", "lat", "lon"}
]

MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_RECORDS = 100


class FileIngestionError(RuntimeError):
    """Raised when an uploaded listing file is invalid."""


async def uploaded_file_to_dataframe(
    file: UploadFile,
) -> pd.DataFrame:
    filename = file.filename or ""
    extension = Path(filename).suffix.casefold()

    if extension not in {".csv", ".json"}:
        raise FileIngestionError(
            "Only CSV and JSON files are accepted."
        )

    content = await file.read(MAX_FILE_SIZE + 1)

    if len(content) > MAX_FILE_SIZE:
        raise FileIngestionError(
            "The uploaded file cannot exceed 2 MB."
        )

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileIngestionError(
            "The uploaded file must use UTF-8 encoding."
        ) from exc

    if extension == ".csv":
        dataframe = parse_csv(text)
    else:
        dataframe = parse_json(text)

    validate_dataframe(dataframe)

    dataframe = add_internal_columns(dataframe)
    validate_internal_ids(dataframe)

    return dataframe[OUTPUT_COLUMNS].copy()


def parse_csv(text: str) -> pd.DataFrame:
    try:
        return pd.read_csv(io.StringIO(text))
    except Exception as exc:
        raise FileIngestionError(
            "The CSV file could not be parsed."
        ) from exc


def parse_json(text: str) -> pd.DataFrame:
    try:
        records = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FileIngestionError(
            "The JSON file is not valid JSON."
        ) from exc

    if not isinstance(records, list):
        raise FileIngestionError(
            "The JSON file must contain a list of listing objects."
        )

    if not all(isinstance(record, dict) for record in records):
        raise FileIngestionError(
            "Every JSON record must be an object."
        )

    return pd.DataFrame(records)


def validate_dataframe(
    dataframe: pd.DataFrame,
) -> None:
    """
    Validate only fields that the public user is responsible for supplying.

    ID, lat and lon are intentionally excluded because they are internal
    pipeline fields added automatically after parsing.
    """
    if dataframe.empty:
        raise FileIngestionError(
            "The file does not contain any listings."
        )

    if len(dataframe) < 2:
        raise FileIngestionError(
            "At least two listings are required."
        )

    if len(dataframe) > MAX_RECORDS:
        raise FileIngestionError(
            f"A maximum of {MAX_RECORDS} listings is allowed."
        )

    missing_columns = [
        column
        for column in USER_REQUIRED_COLUMNS
        if column not in dataframe.columns
    ]

    if missing_columns:
        formatted = ", ".join(missing_columns)

        raise FileIngestionError(
            f"The file is missing required columns: {formatted}."
        )


def add_internal_columns(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add the legacy/internal fields required by the downstream RF2 code.

    ID
    --
    Existing non-empty IDs are preserved. Missing IDs are generated as
    ID_0001, ID_0002, ... while avoiding collisions with supplied IDs.

    lat / lon
    ---------
    These predictors are retained only because they are part of the frozen
    RF2 schema. In the original methodology, listings compared inside the
    same standardized street do not have building-level coordinates, so their
    pairwise latitude/longitude differences carry no useful information.

    For uploaded CSV/JSON files, lat and lon are therefore set to constants
    for every listing. Because RF2 comparisons are blocked by normalized
    street, abs_lat_diff and abs_lon_diff are consequently 0 for every pair,
    which preserves the intended legacy behavior without asking users to
    geocode streets themselves.
    """
    working = dataframe.copy()

    # Ensure ID exists so we can fill missing values.
    if "ID" not in working.columns:
        working["ID"] = pd.NA

    # Normalize supplied IDs enough to detect blanks/collisions safely.
    supplied_ids = working["ID"].copy()

    def clean_id(value):
        if pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    cleaned = supplied_ids.map(clean_id)

    existing_ids = {
        value
        for value in cleaned.tolist()
        if value is not None
    }

    generated_counter = 1
    final_ids: list[str] = []

    for value in cleaned.tolist():
        if value is not None:
            final_ids.append(value)
            continue

        while True:
            candidate = f"ID_{generated_counter:04d}"
            generated_counter += 1

            if candidate not in existing_ids:
                existing_ids.add(candidate)
                final_ids.append(candidate)
                break

    working["ID"] = final_ids

    # Legacy RF2 coordinate predictors: deliberately constant.
    working["lat"] = 0.0
    working["lon"] = 0.0

    return working


def validate_internal_ids(
    dataframe: pd.DataFrame,
) -> None:
    """Validate IDs after automatic enrichment."""
    if dataframe["ID"].isna().any():
        raise FileIngestionError(
            "Every listing must have a non-empty ID."
        )

    ids = dataframe["ID"].astype(str).str.strip()

    if (ids == "").any():
        raise FileIngestionError(
            "Every listing must have a non-empty ID."
        )

    if ids.duplicated().any():
        duplicated = ids[ids.duplicated(keep=False)].tolist()
        formatted = ", ".join(sorted(set(duplicated)))

        raise FileIngestionError(
            f"Every listing ID must be unique. Duplicates: {formatted}."
        )
