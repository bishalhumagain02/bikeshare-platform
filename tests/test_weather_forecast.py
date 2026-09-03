"""
Tests for src/ingestion/archive_weather_forecast.py

The one property that actually matters here: every archived row must
carry BOTH the time the forecast was FOR and the time it was ISSUED.
Without that second timestamp, week 5 can't tell "the forecast we
had at prediction time" from "weather we now know actually happened"
— and training on the latter is the leakage bug the whole plan warns
about.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.archive_weather_forecast import parse_and_archive

FIXTURES = Path(__file__).parent / "fixtures"
ISSUED_AT = datetime(2026, 9, 3, 8, 0, 0, tzinfo=UTC)


@pytest.fixture
def sample_raw() -> str:
    return (FIXTURES / "open_meteo_forecast_sample.json").read_text()


@pytest.fixture(autouse=True)
def _isolate_forecast_dir(tmp_path, monkeypatch):
    import src.ingestion.archive_weather_forecast as archiver
    monkeypatch.setattr(archiver, "WEATHER_FORECASTS_DIR", tmp_path / "forecasts")
    return tmp_path


def test_archives_real_open_meteo_shape(sample_raw, _isolate_forecast_dir):
    out_path = parse_and_archive(sample_raw, issued_at=ISSUED_AT)
    assert out_path is not None
    assert out_path.exists()
    df = pd.read_parquet(out_path)
    assert len(df) > 0
    assert set(df.columns) >= {
        "forecast_target_time", "issued_at", "temperature_2m_c",
        "precipitation_mm", "system_id",
    }


def test_every_row_carries_the_issue_timestamp(sample_raw, _isolate_forecast_dir):
    """This is the whole point of the module — without issued_at, you
    cannot later reconstruct 'what did we know at prediction time'."""
    out_path = parse_and_archive(sample_raw, issued_at=ISSUED_AT)
    df = pd.read_parquet(out_path)
    assert (df["issued_at"] == pd.Timestamp(ISSUED_AT)).all()


def test_trims_to_configured_horizon(sample_raw, _isolate_forecast_dir):
    """Fixture has 48 raw hours starting at midnight; issued_at is 08:00,
    so trimming to the configured horizon should drop early rows,
    not just pass everything through untouched."""
    from src.config import FORECAST_HOURS_TO_ARCHIVE

    out_path = parse_and_archive(sample_raw, issued_at=ISSUED_AT)
    df = pd.read_parquet(out_path)
    assert len(df) <= FORECAST_HOURS_TO_ARCHIVE + 1
    assert df["forecast_target_time"].min() >= pd.Timestamp(ISSUED_AT).floor("h")


def test_partitioned_by_issue_date_not_target_date(sample_raw, _isolate_forecast_dir):
    """Two archives issued on the same day, even though the forecast
    covers into tomorrow, must land in the same issued_dt= partition —
    that's what makes 'one file per day, forever' hold."""
    out_path = parse_and_archive(sample_raw, issued_at=ISSUED_AT)
    assert "issued_dt=2026-09-03" in str(out_path)


def test_rerunning_same_issue_moment_is_idempotent(sample_raw, _isolate_forecast_dir):
    p1 = parse_and_archive(sample_raw, issued_at=ISSUED_AT)
    df1 = pd.read_parquet(p1)
    p1.unlink()
    p2 = parse_and_archive(sample_raw, issued_at=ISSUED_AT)
    df2 = pd.read_parquet(p2)
    assert p1 == p2
    assert len(df1) == len(df2)
