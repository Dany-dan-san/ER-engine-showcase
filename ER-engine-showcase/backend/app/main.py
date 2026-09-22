from __future__ import annotations

import os
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

from app.entity_resolution import run_entity_resolution
from app.extraction_web import ScrapeError, urls_to_dataframe
from app.file_ingestion import (
    FileIngestionError,
    uploaded_file_to_dataframe,
)


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class ListingURLRequest(BaseModel):
    listing_urls: list[HttpUrl] = Field(
        min_length=2,
        max_length=4,
    )


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title="Sreality Entity Resolution API",
    version="1.0.0",
    description=(
        "Entity-resolution service accepting either live Sreality URLs "
        "or structured CSV/JSON listing data."
    ),
)


# ============================================================
# CORS
# ============================================================

frontend_origin = os.getenv(
    "FRONTEND_ORIGIN",
    "http://127.0.0.1:5500",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


# ============================================================
# LIVE URL INGESTION
# ============================================================

@app.post("/api/compare-urls")
async def compare_urls(
    payload: ListingURLRequest,
) -> dict[str, object]:
    try:
        dataframe = await urls_to_dataframe(
            [str(url) for url in payload.listing_urls]
        )

    except ScrapeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "The live Sreality listings could not be extracted: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    try:
        result = await run_in_threadpool(
            run_entity_resolution,
            dataframe,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "The entity-resolution engine could not process "
                "the extracted listings."
            ),
        ) from exc

    return {
        "input_mode": "live_urls",
        "input_count": len(dataframe),
        "result": result,
    }


# ============================================================
# STRUCTURED FILE INGESTION
# ============================================================

@app.post("/api/analyse-file")
async def analyse_file(
    file: Annotated[UploadFile, File(...)],
) -> dict[str, object]:
    try:
        dataframe = await uploaded_file_to_dataframe(file)

    except FileIngestionError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "The uploaded file could not be processed: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    finally:
        await file.close()

    try:
        result = await run_in_threadpool(
            run_entity_resolution,
            dataframe,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "The entity-resolution engine could not process "
                "the uploaded listings."
            ),
        ) from exc

    return {
        "input_mode": "uploaded_file",
        "input_count": len(dataframe),
        "filename": file.filename,
        "result": result,
    }
