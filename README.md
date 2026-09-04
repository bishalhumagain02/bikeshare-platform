# Bike-Share Intelligence Platform — Capital Bikeshare (DC Metro)

A 7-week end-to-end data platform build: GBFS live feeds + historical trip
data + weather actuals/forecasts → dbt dimensional warehouse → Dagster
orchestration → dashboard + decision memo → a leakage-checked bike
availability model, served and monitored.

**City:** Capital Bikeshare (Washington, DC metro — DC, Arlington,
Alexandria, Montgomery Co., Prince George's Co., Fairfax, Falls Church).
Verified live 2026-09-03: `gbfs.json` resolves with no auth, `station_status`
updates well under the 5-min freshness bar, and monthly trip history is
available back to 2010.

## Quickstart

```bash
git clone <this-repo>
cd bikeshare-platform
make setup
make test          # 8 tests should pass, incl. the idempotency check
make poll          # one-shot poll of live station_status
```

## Status (Week 1, in progress)

- [x] Repo scaffold
- [x] Pydantic-validated GBFS `station_status` poller with retry/backoff
      and dead-letter routing for malformed payloads
- [x] Hive-partitioned Parquet landing (`dt=/hr=`)
- [x] Idempotency test suite (delete a partition, rerun, row count is
      identical — see `tests/test_ingestion.py`)
- [x] **Daily weather forecast archiver** (`src/ingestion/archive_weather_forecast.py`)
      — captures the next 48h forecast, tagged with the moment it was
      issued. This is the piece that cannot be recreated retroactively;
      run `make archive-forecast` daily starting now, even before Week 5
- [x] **Historical weather actuals backfill** (`src/ingestion/fetch_weather_actuals.py`)
      — `make backfill-weather FROM=2024-01 TO=2025-12`
- [x] **Historical trip data backfill** (`src/ingestion/fetch_trip_history.py`)
      — `make backfill FROM=2024-01 TO=2024-12`. Handles the real schema
      change Capital Bikeshare made around 2020 (old: `Duration`,
      `Start date`, `Member type`; new: `ride_id`, `started_at`,
      `member_casual`) via an explicit mapping layer, not a silent concat
- [ ] dbt staging/marts/snapshots (Week 2)
- [ ] Dagster orchestration (Week 3)

## Repo layout

```
src/
  config.py                       # city config — swap cities here only
  ingestion/
    schemas.py                    # Pydantic models, GBFS + Open-Meteo boundary validation
    poll_station_status.py        # live poller: fetch → validate → land
    archive_weather_forecast.py   # daily: capture next-48h forecast, tagged with issue time
    fetch_weather_actuals.py      # one-time: backfill historical hourly weather
    fetch_trip_history.py         # one-time: backfill trips, normalizes schema drift across eras
  features/                       # shared train/serve feature module (Week 6)
dbt/
  models/{staging,marts,snapshots}
dagster/                          # asset graph (Week 3)
tests/
  fixtures/                       # real GBFS payload samples, no network needed
docs/                             # metrics.md, DECISIONS.md land here (Week 4/7)
```

## Why this city

Verification steps and the Divvy-vs-Capital-Bikeshare comparison that led
here are in `docs/city-selection.md`.
