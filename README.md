# Entity Resolution Engine

End-to-end entity resolution application for identifying duplicate residential property listings using pairwise similarity features, Random Forest classification, and graph-based entity reconciliation.

This repository is a public showcase of the software architecture developed as part of my MSc research into duplicate housing listings on Sreality.cz. It combines a Python/FastAPI backend, an R-based machine-learning scoring layer, graph-based entity resolution, file and web-data ingestion, and a lightweight JavaScript frontend.

## Architecture

    Input listings
        │
        ▼
    Data ingestion
        │
        ▼
    Pairwise feature construction
        │
        ▼
    Random Forest scoring
        │
        ▼
    Duplicate-link graph
        │
        ▼
    Graph-based entity resolution
        │
        ▼
    Resolved entities

The application supports both structured file inputs and listing-based comparison workflows.

## Technology Stack

### Backend

* Python
* FastAPI
* Pydantic
* R
* Random Forest
* Graph-based entity resolution
* Docker

### Frontend

* JavaScript
* HTML
* CSS

### Deployment

The original application is deployed using Google Cloud infrastructure, with the frontend and backend maintained separately for production deployment (https://sreality-frontend.web.app/).

## Repository Structure

    ER-engine-showcase/
    ├── backend/
    │   ├── app/
    │   │   ├── main.py
    │   │   ├── entity_resolution.py
    │   │   ├── graph_resolution.py
    │   │   ├── rf2_pairwise.py
    │   │   ├── file_ingestion.py
    │   │   └── extraction_web.py
    │   ├── models/
    │   ├── r/
    │   ├── Dockerfile
    │   └── requirements.txt
    │
    ├── frontend/
    │   ├── media/
    │   └── public/
    │
    ├── .gitignore
    ├── LICENSE.txt
    └── README.md

## Key Components

* **`backend/app/main.py`** — FastAPI application and API endpoints
* **`backend/app/file_ingestion.py`** — structured input handling
* **`backend/app/rf2_pairwise.py`** — pairwise feature preparation and ML scoring integration
* **`backend/app/entity_resolution.py`** — entity-resolution workflow
* **`backend/app/graph_resolution.py`** — graph-based reconciliation of predicted duplicate relationships
* **`backend/r/score_rf2.R`** — interface to the frozen Random Forest scoring model
* **`frontend/public/`** — user-facing application interface

## Model and Data Availability

The trained Random Forest model, original research datasets, deployment credentials, and other non-public research artifacts are intentionally excluded from this repository.

The production application loads the frozen model independently from the source-code repository.

Synthetic example data included in this showcase can be used to inspect the expected input formats and application workflow.

## Background

The project originated from MSc research investigating duplicate residential property advertisements as an entity-resolution and data-quality problem.

Rather than treating duplicate detection as a simple rule-based matching task, the system combines multiple pairwise signals through supervised classification and subsequently reconciles predicted duplicate relationships at graph level to produce groups representing underlying real-world entities.

## License

Licensed under the **PolyForm Noncommercial License 1.0.0**.

Noncommercial study, modification, and distribution are permitted under the terms of the license. Commercial use requires separate permission from the copyright holder.

Copyright © 2026 Dempsey Pasternak.
