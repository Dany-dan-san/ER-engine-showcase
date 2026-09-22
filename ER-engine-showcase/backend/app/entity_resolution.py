from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from app.graph_resolution import (
    GraphResolutionError,
    resolve_graph_entities,
)
from app.rf2_pairwise import (
    RF2PairwiseError,
    build_rf2_pairwise,
)


class EntityResolutionError(RuntimeError):
    """Raised when the RF2 or GER-CC pipeline fails."""


BACK_END_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MODEL_PATH = (
    BACK_END_ROOT
    / "models"
    / "RF2_frozen_model_bundle_threshold_051.rds"
)

DEFAULT_PREDICTOR_COLUMNS_PATH = (
    BACK_END_ROOT
    / "models"
    / "RF2_frozen_model_predictor_columns.csv"
)

DEFAULT_R_SCORER_PATH = (
    BACK_END_ROOT
    / "r"
    / "score_rf2.R"
)


def _required_path(
    environment_name: str,
    default: Path | None = None,
) -> Path:
    raw_value = os.getenv(environment_name)

    if raw_value:
        path = Path(raw_value)
    elif default is not None:
        path = default
    else:
        raise EntityResolutionError(
            f"Required environment variable {environment_name!r} is not set."
        )

    path = path.expanduser()

    if not path.exists():
        raise EntityResolutionError(
            f"Required path does not exist for {environment_name}: {path}"
        )

    return path


def _resolve_rscript() -> str:
    configured = os.getenv("RSCRIPT_PATH")

    if configured:
        executable = Path(configured).expanduser()
        if not executable.exists():
            raise EntityResolutionError(
                f"RSCRIPT_PATH does not exist: {executable}"
            )
        return str(executable)

    discovered = shutil.which("Rscript")
    if discovered:
        return discovered

    raise EntityResolutionError(
        "Rscript was not found. Add R's bin folder to PATH or set "
        "RSCRIPT_PATH to the full Rscript.exe path."
    )


def _json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return json.loads(
        frame.to_json(
            orient="records",
            force_ascii=False,
        )
    )


def score_pairwise_with_r(
    pairwise: pd.DataFrame,
) -> pd.DataFrame:
    """
    Pass the street-blocked RF2 pair table to the frozen R model.

    Python writes a temporary CSV, R restores the .rds bundle and predicts,
    and Python reads the pair probabilities back into a DataFrame.
    """
    if pairwise.empty:
        return pd.DataFrame(
            columns=[
                "pair_key",
                "ID_1",
                "ID_2",
                "rf2_probability",
                "rf2_match",
                "rf2_threshold",
            ]
        )

    model_path = _required_path(
        "RF2_MODEL_PATH",
        DEFAULT_MODEL_PATH,
    )
    predictor_path = _required_path(
        "RF2_PREDICTOR_COLUMNS_PATH",
        DEFAULT_PREDICTOR_COLUMNS_PATH,
    )
    scorer_path = _required_path(
        "RF2_R_SCORER_PATH",
        DEFAULT_R_SCORER_PATH,
    )
    rscript = _resolve_rscript()

    default_threshold = os.getenv(
        "RF2_DEFAULT_THRESHOLD",
        "0.51",
    )
    positive_class = os.getenv(
        "RF2_POSITIVE_CLASS",
        "1",
    )
    timeout_seconds = int(
        os.getenv(
            "RF2_R_TIMEOUT_SECONDS",
            "120",
        )
    )

    with tempfile.TemporaryDirectory(
        prefix="rf2_scoring_"
    ) as temporary_directory:
        temporary_path = Path(temporary_directory)
        input_path = temporary_path / "rf2_pairwise.csv"
        output_path = temporary_path / "rf2_predictions.csv"

        pairwise.to_csv(
            input_path,
            index=False,
            encoding="utf-8",
        )

        command = [
            rscript,
            str(scorer_path),
            str(model_path),
            str(input_path),
            str(predictor_path),
            str(output_path),
            default_threshold,
            positive_class,
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )

        if completed.returncode != 0:
            raise EntityResolutionError(
                "R scoring failed.\n"
                f"Command: {command!r}\n"
                f"R stdout:\n{completed.stdout}\n"
                f"R stderr:\n{completed.stderr}"
            )

        if not output_path.exists():
            raise EntityResolutionError(
                "R completed without creating the prediction output file."
            )

        scored = pd.read_csv(output_path)

    expected_columns = {
        "pair_key",
        "ID_1",
        "ID_2",
        "rf2_probability",
        "rf2_match",
        "rf2_threshold",
    }

    missing_columns = expected_columns - set(scored.columns)
    if missing_columns:
        raise EntityResolutionError(
            "R prediction output is missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    if len(scored) != len(pairwise):
        raise EntityResolutionError(
            "R returned a different number of predictions "
            f"({len(scored)}) than pairwise rows ({len(pairwise)})."
        )

    if scored["pair_key"].tolist() != pairwise["pair_key"].tolist():
        raise EntityResolutionError(
            "The prediction rows returned by R are not in the same "
            "pair-key order as the Python pairwise table."
        )

    return scored

def make_json_safe(value: Any) -> Any:
    """
    Convert Pandas/NumPy values into values that FastAPI can
    safely serialize as JSON.

    Lists such as Image.URLs are preserved as JSON arrays.
    """
    if isinstance(value, list):
        return [
            make_json_safe(item)
            for item in value
        ]

    if isinstance(value, tuple):
        return [
            make_json_safe(item)
            for item in value
        ]

    if isinstance(value, dict):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }

    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False

    if isinstance(missing, bool) and missing:
        return None

    # Convert NumPy scalar types into normal Python values.
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass

    return value


def build_listing_lookup(
    dataframe: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """
    Create a lookup containing each complete listing record,
    including Source.URL and Image.URLs.
    """
    listing_lookup: dict[
        str,
        dict[str, Any],
    ] = {}

    for raw_record in dataframe.to_dict(
        orient="records"
    ):
        record = {
            key: make_json_safe(value)
            for key, value in raw_record.items()
        }

        listing_id = record.get("ID")

        if listing_id is None:
            continue

        # Ensure consistent metadata values.
        record["Source.URL"] = (
            record.get("Source.URL")
        )

        image_urls = record.get("Image.URLs")

        if not isinstance(image_urls, list):
            image_urls = []

        record["Image.URLs"] = image_urls

        listing_lookup[str(listing_id)] = record

    return listing_lookup


def attach_listings_to_entities(
    entities: list[dict[str, Any]],
    listing_lookup: dict[
        str,
        dict[str, Any],
    ],
) -> list[dict[str, Any]]:
    """
    Attach complete listing records to every final entity.

    Expected entity structure:
        {
            "entity_id": "ENTITY_001",
            "listing_ids": ["ID_1234", "ID_5678"]
        }
    """
    enriched_entities: list[
        dict[str, Any]
    ] = []

    for entity in entities:
        enriched_entity = dict(entity)

        listing_ids = enriched_entity.get(
            "listing_ids",
            [],
        )

        # Fallback in case the graph output already contains a
        # lightweight listings collection rather than listing_ids.
        if not listing_ids:
            existing_listings = enriched_entity.get(
                "listings",
                [],
            )

            listing_ids = []

            for listing in existing_listings:
                if isinstance(listing, dict):
                    listing_id = listing.get("ID")
                else:
                    listing_id = listing

                if listing_id is not None:
                    listing_ids.append(listing_id)

        normalized_ids = [
            str(listing_id)
            for listing_id in listing_ids
            if listing_id is not None
        ]

        enriched_entity["listing_ids"] = (
            normalized_ids
        )

        enriched_entity["listings"] = [
            listing_lookup[listing_id]
            for listing_id in normalized_ids
            if listing_id in listing_lookup
        ]

        enriched_entities.append(
            enriched_entity
        )

    return enriched_entities


def run_entity_resolution(
    listings: pd.DataFrame,
) -> dict[str, object]:
    """
    Score RF2 pairs, construct the RF2-positive graph, and apply GER-CC.

    Complete RF2-positive components remain intact. Incomplete components are
    resolved through weighted correlation clustering. Listings without a
    positive relation remain singleton entities.

    Live-page metadata such as Source.URL and Image.URLs is excluded from RF2
    pair construction but preserved in the complete listing records attached
    to each final entity.
    """

    # -----------------------------------------------------
    # 1. Preserve the complete listing records
    # -----------------------------------------------------

    full_listings = listings.copy(deep=True)

    if "Image.URLs" in full_listings.columns:
        full_listings["Image.URLs"] = full_listings[
            "Image.URLs"
        ].apply(
            lambda value: (
                value
                if isinstance(value, list)
                else []
            )
        )

    # These fields are live-page metadata. They must be returned
    # to the frontend, but they must not enter RF2 preparation.
    live_metadata_columns = [
        "Source.URL",
        "Image.URLs",
    ]

    model_listings = full_listings.drop(
        columns=live_metadata_columns,
        errors="ignore",
    ).copy()

    # -----------------------------------------------------
    # 2. Construct the RF2 pairwise predictor table
    # -----------------------------------------------------

    try:
        transformed = build_rf2_pairwise(
            model_listings,
            predictor_columns_path=_required_path(
                "RF2_PREDICTOR_COLUMNS_PATH",
                DEFAULT_PREDICTOR_COLUMNS_PATH,
            ),
        )
    except RF2PairwiseError as exc:
        raise EntityResolutionError(
            str(exc)
        ) from exc

    # -----------------------------------------------------
    # 3. Score the comparable pairs using the frozen R model
    # -----------------------------------------------------

    scored = score_pairwise_with_r(
        transformed.pairwise
    )

    comparisons = transformed.pairwise.merge(
        scored,
        on=[
            "pair_key",
            "ID_1",
            "ID_2",
        ],
        how="left",
        validate="one_to_one",
    )

    # -----------------------------------------------------
    # 4. Resolve the RF2-positive graph
    # -----------------------------------------------------

    try:
        graph_resolution = resolve_graph_entities(
            full_listings,
            comparisons,
        )
    except GraphResolutionError as exc:
        raise EntityResolutionError(
            str(exc)
        ) from exc

        # -----------------------------------------------------
    # Attach complete listing records to each entity
    # -----------------------------------------------------

    listing_lookup = build_listing_lookup(
        full_listings
    )

    enriched_entities = attach_listings_to_entities(
        graph_resolution.get(
            "entities",
            [],
        ),
        listing_lookup,
    )

    graph_resolution["entities"] = (
        enriched_entities
    )

    # -----------------------------------------------------
    # 5. Determine the public API status and message
    # -----------------------------------------------------

    if transformed.pairwise.empty:
        status = "no_comparable_pairs"

        message = (
            "No submitted listings share the same normalized street. "
            "No RF2 predictions were calculated; each listing was returned "
            "as a singleton entity."
        )
    else:
        status = "success"

        message = (
            "RF2 pair scoring and GER-CC graph resolution completed."
        )

    # -----------------------------------------------------
    # 6. Return the complete result
    # -----------------------------------------------------

    return {
        "status": status,
        "message": message,

        "input_listing_count": (
            transformed.input_listing_count
        ),

        "blocked_street_count": (
            transformed.blocked_street_count
        ),

        "comparable_pair_count": (
            transformed.comparable_pair_count
        ),

        "unpaired_listing_ids": (
            transformed.unpaired_listing_ids
        ),

        "comparisons": _json_records(
            comparisons
        ),

        "graph_resolution": {
            key: value
            for key, value
            in graph_resolution.items()
            if key not in {
                "entities",
                "memberships",
                "regrouped_listings",
                "cc_pair_decisions",
            }
        },

        "entities": enriched_entities,

        "memberships": graph_resolution[
            "memberships"
        ],

        "regrouped_listings": graph_resolution[
            "regrouped_listings"
        ],

        "cc_pair_decisions": graph_resolution[
            "cc_pair_decisions"
        ],
    }


