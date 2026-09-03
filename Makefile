.PHONY: setup poll poll-loop archive-forecast backfill-weather test lint idempotency-check clean

setup:
	pip install -e ".[dev]" --break-system-packages

poll:
	PYTHONPATH=. python3 -m src.ingestion.poll_station_status

poll-loop:
	PYTHONPATH=. python3 -m src.ingestion.poll_station_status --loop

# Run once a day (cron / Dagster schedule / Task Scheduler). Every day this
# is skipped is forecast history that cannot be recreated retroactively.
archive-forecast:
	PYTHONPATH=. python3 -m src.ingestion.archive_weather_forecast

# Historical actuals, one-time backfill. Example:
#   make backfill-weather FROM=2024-01 TO=2025-12
backfill-weather:
	PYTHONPATH=. python3 -m src.ingestion.fetch_weather_actuals --from $(FROM) --to $(TO)

test:
	PYTHONPATH=. python3 -m pytest tests/ -v

lint:
	ruff check src/ tests/

# The plan's "delete any partition, rerun the job, row count is identical"
# check, run as an explicit target so it can be a CI step later.
idempotency-check:
	PYTHONPATH=. python3 -m pytest tests/ -v -k idempotent

clean:
	rm -rf raw/_deadletter/* .pytest_cache
