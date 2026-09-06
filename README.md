# Bike-Share Intelligence Platform — Capital Bikeshare (DC Metro)

A 7-week end-to-end data platform build: GBFS live feeds + historical trip
data + weather actuals/forecasts → dbt dimensional warehouse → Dagster
orchestration → dashboard + decision memo → a leakage-checked bike
availability model, served and monitored.

**City:** Capital Bikeshare (Washington, DC metro — DC, Arlington,
Alexandria, Montgomery Co., Prince George's Co., Fairfax, Falls Church).
Chosen over Divvy (Chicago) for deeper public trip history (2010+) and a
lighter station count. Full reasoning: `docs/city-selection.md`.

## Quickstart

```bash
git clone <this-repo>
cd bikeshare-platform
pip install -e ".[dev]"
cp .env.example .env        # fill in your Backblaze B2 credentials if using cloud collection
pytest tests/ -v             # 38 tests should pass
python -m src.ingestion.poll_station_status   # one-shot poll of live station_status
```

For the dbt warehouse:
```bash
cd dbt
pip install dbt-core dbt-duckdb
DBT_PROFILES_DIR=. dbt build --vars '{"raw_data_path": "../raw"}'
```

## Status

### Week 1 — Ingestion (complete)

Four independent data sources, each with retry/backoff, Pydantic
validation at the boundary, dead-letter routing for malformed payloads,
and Hive-partitioned Parquet output:

| Source | Script | Cadence |
|---|---|---|
| Live station bike/dock counts | `src/ingestion/poll_station_status.py` | ~10 min |
| Station metadata (name/capacity/lat-lon) | `src/ingestion/poll_station_information.py` | daily |
| Weather forecast (issue-timestamped) | `src/ingestion/archive_weather_forecast.py` | daily |
| Weather actuals (historical) | `src/ingestion/fetch_weather_actuals.py` | one-time backfill |
| Trip history (schema-drift-aware) | `src/ingestion/fetch_trip_history.py` | one-time backfill |

**Cloud collection:** GitHub Actions + Backblaze B2, triggered externally
by cron-job.org (not GitHub's own `schedule:` trigger — see
`docs/DECISIONS.md` for why). Runs continuously regardless of local time
zone or whether any personal machine is on. Setup: `docs/cloud-setup.md`.

Backfilled range: **2024-01 through 2025-12** (most recent complete
2-year window — spans a real pattern of record 2025 ridership followed
by a 2026 decline).

### Week 2 — dbt warehouse (complete)

- 5 staging models (station status, stations, trips, trip-derived
  stations, weather) — rename/cast/dedupe only, no business logic
- SCD Type 2 snapshot on station metadata (`snapshots/stations_snapshot.sql`)
  — verified against a real simulated capacity change
- 4 marts: `dim_station` (live, SCD2), `dim_trip_station` (derived from
  trip data — see below), `fct_trip` (incremental), `fct_station_status_hourly`
- 15 dbt tests (schema + singular), all passing or intentionally
  warning on documented, investigated findings

**Full build result on real data (~10M+ trips):** `PASS=21 WARN=4 ERROR=0`
— every warning is understood and documented, not a mystery. See
`docs/DECISIONS.md` for the full list of real issues found and how each
was resolved.

### Not started yet

- Week 3: Dagster orchestration, CI
- Week 4: analytics dashboard + decision memo
- Week 5: baseline models + leakage-checked ML model
- Week 6: serving (FastAPI) + monitoring
- Week 7: polish, video, final README pass

## Repo layout

```
src/
  config.py                       # city config, poll interval — swap cities here only
  storage.py                      # optional B2 upload (no-op without credentials)
  ingestion/
    schemas.py                    # Pydantic models — GBFS + Open-Meteo boundary validation
    poll_station_status.py        # (1) live bike/dock counts
    poll_station_information.py   # (2) station metadata (feeds the SCD2 snapshot)
    archive_weather_forecast.py   # (3) daily forecast, issue-timestamped
    fetch_weather_actuals.py      # (4) historical weather backfill
    fetch_trip_history.py         # (5) historical trips - schema-drift + dtype-consistency handling
  tools/
    download_from_b2.py           # pull accumulated cloud data down locally, on demand

dbt/
  models/staging/                 # 5 models - rename/cast/dedupe only
  models/marts/                   # 4 models - dim_station, dim_trip_station, fct_trip, fct_station_status_hourly
  models/schema.yml               # generic tests, with documented severity choices
  snapshots/stations_snapshot.sql # SCD Type 2
  tests/                          # 3 singular tests, all with documented severity

tests/                            # 38 Python tests, 5 test files, fixtures for every source
.github/workflows/                # 2 cloud-collection workflows (repository_dispatch triggered)
docs/
  city-selection.md               # Divvy vs Capital Bikeshare decision
  cloud-setup.md                  # B2 + cron-job.org setup guide
  DECISIONS.md                    # every real bug/finding hit, with root cause and fix
raw/                               # data lands here locally when downloaded
```
