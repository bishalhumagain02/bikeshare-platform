"""
Tests for src/ingestion/poll_station_information.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.poll_station_information import parse_and_land
from src.ingestion.schemas import StationInformationFeed

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_TIME = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def sample_raw() -> str:
    return (FIXTURES / "station_information_sample.json").read_text()


@pytest.fixture(autouse=True)
def _isolate_dirs(tmp_path, monkeypatch):
    import src.ingestion.poll_station_information as poller
    monkeypatch.setattr(poller, "STATION_INFO_DIR", tmp_path / "station_information")
    monkeypatch.setattr(poller, "DEADLETTER_DIR", tmp_path / "deadletter")
    return tmp_path


def test_schema_parses_real_shape(sample_raw):
    feed = StationInformationFeed.model_validate(json.loads(sample_raw))
    stations = feed.stations
    assert len(stations) == 3
    assert stations[0].name == "Lincoln Memorial"
    assert stations[0].capacity == 21


def test_writes_dt_partitioned_parquet(sample_raw, _isolate_dirs):
    out_path = parse_and_land(sample_raw, fetched_at=FIXED_TIME)
    assert out_path is not None
    assert "dt=2026-09-03" in str(out_path)
    df = pd.read_parquet(out_path)
    assert len(df) == 3
    assert set(df.columns) >= {"station_id", "name", "capacity", "lat", "lon", "fetched_at"}


def test_html_error_goes_to_deadletter(_isolate_dirs):
    result = parse_and_land("<html>502</html>", fetched_at=FIXED_TIME)
    assert result is None


def test_rerun_same_day_is_idempotent(sample_raw, _isolate_dirs):
    p1 = parse_and_land(sample_raw, fetched_at=FIXED_TIME)
    df1 = pd.read_parquet(p1)
    p1.unlink()
    p2 = parse_and_land(sample_raw, fetched_at=FIXED_TIME)
    df2 = pd.read_parquet(p2)
    assert p1 == p2
    assert len(df1) == len(df2)
