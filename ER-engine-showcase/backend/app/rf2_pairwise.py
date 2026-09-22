from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd


PAIR_ID_COLUMNS = ["pair_key", "ID_1", "ID_2"]

DEFAULT_RF2_PREDICTOR_COLUMNS = [
    "same_agency",
    "same_agency_contact",
    "same_type",
    "same_energy",
    "same_floor",
    "same_district",
    "same_neighborhood",
    "same_building_material",
    "same_renovation",
    "same_furnished",
    "same_partly_furnished",
    "same_wheelchair",
    "same_elevator",
    "same_balcony",
    "same_terrace",
    "same_loggia",
    "same_swimming",
    "same_basement",
    "same_parking",
    "same_garage",
    "abs_price_diff",
    "rel_price_diff",
    "abs_area_diff",
    "rel_area_diff",
    "abs_lat_diff",
    "abs_lon_diff",
    "abs_floor_diff",
    "price_close_1pct",
    "price_close_5pct",
    "price_close_10pct",
    "area_close_1sqm",
    "area_close_2sqm",
    "area_close_5sqm",
    "floor_close_1",
    "shared_amenity_count",
    "abs_days_published_diff",
    "abs_days_modified_diff",
]

REQUIRED_LISTING_COLUMNS = [
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

STRICT_NUMERIC_COLUMNS = [
    "Price",
    "Net.Area",
    "Floor",
    "lat",
    "lon",
]

AMENITY_COLUMNS = [
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
]


class RF2PairwiseError(ValueError):
    """Raised when listing data cannot be transformed for the frozen RF2 model."""


@dataclass(frozen=True)
class RF2PairwiseResult:
    """The complete pair table and the model-ready predictor matrix."""

    pairwise: pd.DataFrame
    predictors: pd.DataFrame
    predictor_columns: list[str]
    input_listing_count: int
    comparable_pair_count: int
    blocked_street_count: int
    unpaired_listing_ids: list[str]


def load_predictor_columns(path: str | Path | None = None) -> list[str]:
    """
    Load the exact frozen RF2 predictor order.

    When no path is supplied, the order observed in
    RF2_frozen_model_predictor_columns.csv is used.
    """
    if path is None:
        return DEFAULT_RF2_PREDICTOR_COLUMNS.copy()

    predictor_path = Path(path)
    if not predictor_path.exists():
        raise RF2PairwiseError(
            f"RF2 predictor-column file was not found: {predictor_path}"
        )

    frame = pd.read_csv(predictor_path)
    if "predictor_cols" not in frame.columns:
        raise RF2PairwiseError(
            "The predictor-column CSV must contain a 'predictor_cols' column."
        )

    columns = (
        frame["predictor_cols"]
        .dropna()
        .astype(str)
        .str.strip()
        .tolist()
    )

    if not columns:
        raise RF2PairwiseError("The predictor-column CSV is empty.")

    if len(columns) != len(set(columns)):
        raise RF2PairwiseError(
            "The predictor-column CSV contains duplicate column names."
        )

    expected = set(DEFAULT_RF2_PREDICTOR_COLUMNS)
    received = set(columns)

    if received != expected:
        missing = sorted(expected - received)
        unexpected = sorted(received - expected)
        raise RF2PairwiseError(
            "The predictor-column CSV does not match the frozen RF2 schema. "
            f"Missing={missing}; unexpected={unexpected}."
        )

    return columns


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _normalize_text(value: Any) -> str | None:
    if _is_missing(value):
        return None

    text = unicodedata.normalize("NFC", str(value))
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text or None


def _street_block(value: Any) -> str | None:
    """
    Create a stable street-blocking key.

    Accents, case, punctuation and repeated spaces are ignored. Building
    numbers should already have been removed by extraction_web.py, but a
    trailing number is removed again defensively.
    """
    text = _normalize_text(value)
    if text is None:
        return None

    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    text = re.sub(r"\s+\d+(?:/\d+)?[a-z]?$", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _same_value(left: Any, right: Any) -> int:
    """
    Return 1 only when both values are present and equal.

    Missing values are deliberately not treated as a match, including when
    both sides are missing.
    """
    if _is_missing(left) or _is_missing(right):
        return 0

    left_number = pd.to_numeric(pd.Series([left]), errors="coerce").iloc[0]
    right_number = pd.to_numeric(pd.Series([right]), errors="coerce").iloc[0]

    if not pd.isna(left_number) and not pd.isna(right_number):
        return int(float(left_number) == float(right_number))

    return int(_normalize_text(left) == _normalize_text(right))


def _require_number(value: Any, *, field: str, listing_id: str) -> float:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        raise RF2PairwiseError(
            f"Listing {listing_id!r} has no valid numeric value for {field!r}."
        )
    return float(number)


def _binary(value: Any, *, field: str, listing_id: str) -> int:
    if _is_missing(value):
        return 0

    if isinstance(value, bool):
        return int(value)

    text = str(value).strip().casefold()
    mapping = {
        "0": 0,
        "0.0": 0,
        "false": 0,
        "no": 0,
        "n": 0,
        "1": 1,
        "1.0": 1,
        "true": 1,
        "yes": 1,
        "y": 1,
    }

    if text not in mapping:
        raise RF2PairwiseError(
            f"Listing {listing_id!r} has an invalid binary value "
            f"for {field!r}: {value!r}."
        )

    return mapping[text]


def _require_date(value: Any, *, field: str, listing_id: str) -> pd.Timestamp:
    if _is_missing(value):
        raise RF2PairwiseError(
            f"Listing {listing_id!r} has no value for {field!r}."
        )

    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        raise RF2PairwiseError(
            f"Listing {listing_id!r} has an invalid date for "
            f"{field!r}: {value!r}."
        )

    return pd.Timestamp(parsed).normalize()


def _absolute_difference(left: float, right: float) -> float:
    return abs(left - right)


def _relative_difference(left: float, right: float) -> float:
    """
    Match the RF2 training transformation:

        abs(left - right) / max(abs(left), abs(right))

    The uploaded RF2 pair table confirms the larger value is the denominator.
    """
    denominator = max(abs(left), abs(right))
    if denominator == 0:
        return 0.0
    return abs(left - right) / denominator


def _integer_if_whole(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)


def _validate_listing_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing_columns = [
        column
        for column in REQUIRED_LISTING_COLUMNS
        if column not in frame.columns
    ]
    if missing_columns:
        raise RF2PairwiseError(
            "The standardized listing DataFrame is missing required columns: "
            + ", ".join(missing_columns)
        )

    if len(frame) < 2:
        raise RF2PairwiseError(
            "At least two listings are required to create pairwise comparisons."
        )

    working = frame[REQUIRED_LISTING_COLUMNS].copy()

    if working["ID"].isna().any():
        raise RF2PairwiseError("Every listing must have a non-empty ID.")

    working["ID"] = working["ID"].astype(str).str.strip()

    if (working["ID"] == "").any():
        raise RF2PairwiseError("Every listing must have a non-empty ID.")

    if working["ID"].duplicated().any():
        duplicated = working.loc[
            working["ID"].duplicated(keep=False),
            "ID",
        ].tolist()
        raise RF2PairwiseError(
            f"Listing IDs must be unique. Duplicates: {duplicated}"
        )

    working["_street_block"] = working["Street"].map(_street_block)
    return working


def _create_pair(left: pd.Series, right: pd.Series) -> dict[str, object]:
    left_id = str(left["ID"])
    right_id = str(right["ID"])

    price_left = _require_number(
        left["Price"],
        field="Price",
        listing_id=left_id,
    )
    price_right = _require_number(
        right["Price"],
        field="Price",
        listing_id=right_id,
    )
    area_left = _require_number(
        left["Net.Area"],
        field="Net.Area",
        listing_id=left_id,
    )
    area_right = _require_number(
        right["Net.Area"],
        field="Net.Area",
        listing_id=right_id,
    )
    floor_left = _require_number(
        left["Floor"],
        field="Floor",
        listing_id=left_id,
    )
    floor_right = _require_number(
        right["Floor"],
        field="Floor",
        listing_id=right_id,
    )
    lat_left = _require_number(
        left["lat"],
        field="lat",
        listing_id=left_id,
    )
    lat_right = _require_number(
        right["lat"],
        field="lat",
        listing_id=right_id,
    )
    lon_left = _require_number(
        left["lon"],
        field="lon",
        listing_id=left_id,
    )
    lon_right = _require_number(
        right["lon"],
        field="lon",
        listing_id=right_id,
    )

    published_left = _require_date(
        left["Date.Published"],
        field="Date.Published",
        listing_id=left_id,
    )
    published_right = _require_date(
        right["Date.Published"],
        field="Date.Published",
        listing_id=right_id,
    )
    modified_left = _require_date(
        left["Date.Modified"],
        field="Date.Modified",
        listing_id=left_id,
    )
    modified_right = _require_date(
        right["Date.Modified"],
        field="Date.Modified",
        listing_id=right_id,
    )

    abs_price_diff = _absolute_difference(price_left, price_right)
    rel_price_diff = _relative_difference(price_left, price_right)
    abs_area_diff = _absolute_difference(area_left, area_right)
    rel_area_diff = _relative_difference(area_left, area_right)
    abs_floor_diff = _absolute_difference(floor_left, floor_right)

    shared_amenity_count = sum(
        int(
            _binary(
                left[column],
                field=column,
                listing_id=left_id,
            )
            == 1
            and _binary(
                right[column],
                field=column,
                listing_id=right_id,
            )
            == 1
        )
        for column in AMENITY_COLUMNS
    )

    pair = {
        "pair_key": f"{left_id}_{right_id}",
        "ID_1": left_id,
        "ID_2": right_id,
        "same_agency": _same_value(left["Agency"], right["Agency"]),
        "same_agency_contact": _same_value(
            left["Agency_Contact"],
            right["Agency_Contact"],
        ),
        "same_type": _same_value(left["Type"], right["Type"]),
        "same_energy": _same_value(
            left["Energy.Score"],
            right["Energy.Score"],
        ),
        "same_floor": _same_value(left["Floor"], right["Floor"]),
        "same_district": _same_value(
            left["District"],
            right["District"],
        ),
        "same_neighborhood": _same_value(
            left["Neighborhood"],
            right["Neighborhood"],
        ),
        "same_building_material": _same_value(
            left["Building.material"],
            right["Building.material"],
        ),
        "same_renovation": _same_value(
            left["Renovation"],
            right["Renovation"],
        ),
        "same_furnished": _same_value(
            left["Furnished"],
            right["Furnished"],
        ),
        "same_partly_furnished": _same_value(
            left["Partly.Furnished"],
            right["Partly.Furnished"],
        ),
        "same_wheelchair": _same_value(
            left["Wheelchair"],
            right["Wheelchair"],
        ),
        "same_elevator": _same_value(
            left["Elevator"],
            right["Elevator"],
        ),
        "same_balcony": _same_value(
            left["Balcony"],
            right["Balcony"],
        ),
        "same_terrace": _same_value(
            left["Terrace"],
            right["Terrace"],
        ),
        "same_loggia": _same_value(
            left["Loggia"],
            right["Loggia"],
        ),
        "same_swimming": _same_value(
            left["Swimming.pool"],
            right["Swimming.pool"],
        ),
        "same_basement": _same_value(
            left["Basement"],
            right["Basement"],
        ),
        "same_parking": _same_value(
            left["Parking"],
            right["Parking"],
        ),
        "same_garage": _same_value(
            left["Garage"],
            right["Garage"],
        ),
        "abs_price_diff": _integer_if_whole(abs_price_diff),
        "rel_price_diff": rel_price_diff,
        "abs_area_diff": _integer_if_whole(abs_area_diff),
        "rel_area_diff": rel_area_diff,
        "abs_lat_diff": abs(lat_left - lat_right),
        "abs_lon_diff": abs(lon_left - lon_right),
        "abs_floor_diff": _integer_if_whole(abs_floor_diff),
        "price_close_1pct": int(rel_price_diff <= 0.01),
        "price_close_5pct": int(rel_price_diff <= 0.05),
        "price_close_10pct": int(rel_price_diff <= 0.10),
        "area_close_1sqm": int(abs_area_diff <= 1),
        "area_close_2sqm": int(abs_area_diff <= 2),
        "area_close_5sqm": int(abs_area_diff <= 5),
        "floor_close_1": int(abs_floor_diff <= 1),
        "shared_amenity_count": shared_amenity_count,
        "abs_days_published_diff": abs(
            (published_left - published_right).days
        ),
        "abs_days_modified_diff": abs(
            (modified_left - modified_right).days
        ),
    }

    return pair


def build_rf2_pairwise(
    listings: pd.DataFrame,
    *,
    predictor_columns_path: str | Path | None = None,
) -> RF2PairwiseResult:
    """
    Convert standardized listing rows into the frozen RF2 pairwise format.

    Only listings sharing the same normalized Street value are compared.
    Cross-street combinations are never generated and therefore never reach
    the distance calculations or the frozen RF2 model.
    """
    predictor_columns = load_predictor_columns(predictor_columns_path)
    working = _validate_listing_frame(listings)

    rows: list[dict[str, object]] = []
    paired_ids: set[str] = set()
    blocked_street_count = 0

    valid_blocks = working.dropna(subset=["_street_block"]).groupby(
        "_street_block",
        sort=False,
        dropna=True,
    )

    for _, block in valid_blocks:
        if len(block) < 2:
            continue

        blocked_street_count += 1
        records = [
            row
            for _, row in block.iterrows()
        ]

        for left, right in combinations(records, 2):
            rows.append(_create_pair(left, right))
            paired_ids.add(str(left["ID"]))
            paired_ids.add(str(right["ID"]))

    full_columns = PAIR_ID_COLUMNS + predictor_columns
    pairwise = pd.DataFrame(rows, columns=full_columns)

    if not pairwise.empty:
        pairwise = pairwise.loc[:, full_columns]
        predictors = pairwise.loc[:, predictor_columns].copy()

        if predictors.isna().any().any():
            missing = predictors.columns[
                predictors.isna().any()
            ].tolist()
            raise RF2PairwiseError(
                "The model-ready RF2 matrix contains missing values in: "
                + ", ".join(missing)
            )
    else:
        predictors = pd.DataFrame(columns=predictor_columns)

    unpaired_ids = [
        listing_id
        for listing_id in working["ID"].tolist()
        if listing_id not in paired_ids
    ]

    return RF2PairwiseResult(
        pairwise=pairwise,
        predictors=predictors,
        predictor_columns=predictor_columns,
        input_listing_count=len(working),
        comparable_pair_count=len(pairwise),
        blocked_street_count=blocked_street_count,
        unpaired_listing_ids=unpaired_ids,
    )
