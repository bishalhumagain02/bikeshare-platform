.PHONY: setup poll poll-loop test lint idempotency-check clean

setup:
	pip install -e ".[dev]" --break-system-packages

poll:
	PYTHONPATH=. python3 -m src.ingestion.poll_station_status

poll-loop:
	PYTHONPATH=. python3 -m src.ingestion.poll_station_status --loop

test:
	PYTHONPATH=. python3 -m pytest tests/ -v

lint:
	ruff check src/ tests/

# The plan's "delete any partition, rerun the job, row count is identical"
# check, run as an explicit target so it can be a CI step later.
idempotency-check:
	PYTHONPATH=. python3 -m pytest tests/test_ingestion.py -v -k idempotent

clean:
	rm -rf raw/_deadletter/* .pytest_cache
