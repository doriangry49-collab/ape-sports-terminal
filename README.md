# Sports Intelligence Engine (sports-engine)

A lightweight Sports Intelligence Engine starting with Turkish Süper Lig football pre-match analysis.

## Core Philosophy & Architectural Principles

1. **Lightweight & Local-First**: No Docker, no PostgreSQL, no Redis, no Celery, no cloud lock-in. Fully runnable on local Windows/Linux machines with standard Python.
2. **Medallion Data Architecture**:
   - **BRONZE**: Immutable, raw source responses (JSON / raw payloads).
   - **SILVER**: Normalized canonical entities, source mappings, cleaned events.
   - **GOLD**: Model-ready features, timestamped predictions, and evaluation records.
   - Layers are strictly decoupled and never mixed.
3. **Point-in-Time & Auditability**:
   - Every time-sensitive entity tracks `event_time`, `source_time`, `fetched_at`, `ingested_at`, and `available_at`.
   - All timestamps are timezone-aware (UTC enforced).
   - Closing lines are never stored as static flags; they are dynamically derivable from timestamps.
4. **Deterministic Entity Resolution**:
   - Exact canonical normalization handles diacritics and naming conventions (e.g. Turkish characters).
   - RapidFuzz serves as a fallback matcher with strict confidence scoring.
   - Fuzzy matches are never marked as `verified` automatically.

## Repository Structure

```
sports-engine/
├── config/             # Runtime configuration & environment settings
├── data/
│   ├── bronze/         # Raw source payloads (immutable)
│   ├── silver/         # Canonical entities (Parquet / DuckDB)
│   └── gold/           # Features & predictions
├── scripts/            # Local execution & maintenance scripts
├── src/sports_engine/
│   ├── collectors/     # Raw data ingestion interfaces (base classes)
│   ├── domain/         # Canonical entity schemas & validation
│   ├── normalization/  # Canonical IDs & RapidFuzz resolution
│   ├── storage/        # DuckDB & Parquet IO utilities
│   ├── features/       # Feature engineering pipelines
│   ├── models/         # Predictive modeling interfaces
│   ├── backtest/       # Historical simulation logic
│   └── evaluation/     # Metric calculation & performance tracking
├── tests/              # Test suite (pytest)
├── pyproject.toml      # Dependency & package configuration
├── .env.example        # Environment variable template
└── README.md
```

## Getting Started

### Prerequisites

* Python 3.12+

### Installation

```bash
# Clone or navigate to the directory
cd sports-engine

# Install dependencies
pip install -e .
```

### Running Tests

```bash
pytest
```
