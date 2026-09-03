"""
Tests for src/ingestion/poll_station_status.py

Run: pytest tests/ -v
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from src.ingestion.poll_station_status import parse_and_land
from src.ingestion.schemas import StationStatusFeed

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_TIME = datetime(2026, 9, 3, 14, 0, 0, tzinfo=UTC)


@pytest.fixture
def sample_raw() -> str:
    return (FIXTURES / "station_status_sample.json").read_text()


@pytest.fixture(autouse=True)
def _isolate_raw_dir(tmp_path, monkeypatch):
    """Point every raw-data path at a temp dir so tests never touch
    the real raw/ directory."""
    import src.config as config

    for name in ["RAW_DIR", "STATION_STATUS_DIR", "STATION_INFO_DIR",
                 "TRIPS_DIR", "DEADLETTER_DIR"]:
        monkeypatch.setattr(config, name, tmp_path / name)

    import src.ingestion.poll_station_status as poller
    monkeypatch.setattr(poller, "STATION_STATUS_DIR", tmp_path / "STATION_STATUS_DIR")
    monkeypatch.setattr(poller, "DEADLETTER_DIR", tmp_path / "DEADLETTER_DIR")
    return tmp_path


# --- Schema validation ---------------------------------------------------

def test_schema_parses_real_shape(sample_raw):
    """The Pydantic model should accept the actual GBFS station_status
    shape, including fields we don't explicitly model (extra='allow')."""
    feed = StationStatusFeed.model_validate(json.loads(sample_raw))
    stations = feed.stations
    assert len(stations) == 3
    assert stations[0].station_id == "0825f2b1-1f3f-11e7-bf6b-3863bb334450"
    assert stations[0].num_bikes_available == 5


def test_negative_counts_rejected():
    bad = {
        "last_updated": 1,
        "ttl": 10,
        "data": {"stations": [{
            "station_id": "x",
            "num_bikes_available": -1,
            "num_docks_available": 5,
            "last_reported": 1,
        }]},
    }
    with pytest.raises(ValidationError):
        StationStatusFeed.model_validate(bad).stations  # noqa: B018 — triggers validation


# --- Dead-letter routing --------------------------------------------------

def test_html_error_page_goes_to_deadletter(_isolate_raw_dir):
    """Feeds return HTML error pages with a 200 status more often than
    you'd think — this must not crash the poller."""
    html = "<html><body>502 Bad Gateway</body></html>"
    result = parse_and_land(html, fetched_at=FIXED_TIME)
    assert result is None
    deadletter_files = list((_isolate_raw_dir / "DEADLETTER_DIR").glob("*.json"))
    assert len(deadletter_files) == 1
    content = json.loads(deadletter_files[0].read_text())
    assert "not JSON" in content["reason"]


def test_malformed_json_goes_to_deadletter(_isolate_raw_dir):
    result = parse_and_land('{"data": {"stations": [{"station_id": "x"', fetched_at=FIXED_TIME)
    assert result is None
    assert len(list((_isolate_raw_dir / "DEADLETTER_DIR").glob("*.json"))) == 1


def test_empty_station_list_goes_to_deadletter(_isolate_raw_dir):
    empty = json.dumps({"last_updated": 1, "ttl": 10, "data": {"stations": []}})
    result = parse_and_land(empty, fetched_at=FIXED_TIME)
    assert result is None


# --- Happy path + partitioning --------------------------------------------

def test_valid_payload_writes_hive_partitioned_parquet(sample_raw, _isolate_raw_dir):
    out_path = parse_and_land(sample_raw, fetched_at=FIXED_TIME)
    assert out_path is not None
    assert out_path.exists()
    assert "dt=2026-09-03" in str(out_path)
    assert "hr=14" in str(out_path)

    df = pd.read_parquet(out_path)
    assert len(df) == 3
    assert set(df.columns) >= {"station_id", "num_bikes_available",
                                "num_docks_available", "fetched_at", "system_id"}


# --- Idempotency: the property the plan calls non-negotiable --------------

def test_rerun_same_partition_is_idempotent(sample_raw, _isolate_raw_dir):
    """Delete a partition, rerun the job, and the resulting row count
    must be identical. This is the single most important property in
    the whole ingestion layer."""
    first_path = parse_and_land(sample_raw, fetched_at=FIXED_TIME)
    first_df = pd.read_parquet(first_path)

    # Simulate "delete partition, rerun" from the plan's backfill demo.
    first_path.unlink()
    second_path = parse_and_land(sample_raw, fetched_at=FIXED_TIME)
    second_df = pd.read_parquet(second_path)

    assert first_path == second_path, "re-running same fetch minute must overwrite, not duplicate"
    assert len(first_df) == len(second_df)
    pd.testing.assert_frame_equal(
        first_df.drop(columns=["fetched_at"]),
        second_df.drop(columns=["fetched_at"]),
    )


def test_rerun_does_not_duplicate_rows_across_full_hour(sample_raw, _isolate_raw_dir):
    """Poll the same hour twice at different minutes, then read the whole
    hour partition back with a glob — total row count should be
    (stations_per_poll * distinct_polls), never more, never fewer."""
    t1 = FIXED_TIME
    t2 = FIXED_TIME.replace(minute=5)

    parse_and_land(sample_raw, fetched_at=t1)
    parse_and_land(sample_raw, fetched_at=t2)

    hour_dir = _isolate_raw_dir / "STATION_STATUS_DIR" / "dt=2026-09-03" / "hr=14"
    files = list(hour_dir.glob("*.parquet"))
    assert len(files) == 2  # two distinct polls, two files — no overwrite across minutes

    total_rows = sum(len(pd.read_parquet(f)) for f in files)
    assert total_rows == 3 * 2
