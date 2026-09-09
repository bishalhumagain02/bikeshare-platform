"""
Tests for src/features/build_features.py

test_forecast_join_never_uses_a_future_issued_forecast is the most
important test in this whole project's ML pipeline — it's a
deliberate adversarial check that the leakage guard actually works,
not just an assumption that it does.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.build_features import (
    _add_cyclical_time_features,
    _add_forecast_features,
    _add_lag_features,
    _add_neighbor_state,
    build_features,
)


def test_forecast_join_never_uses_a_future_issued_forecast():
    """THE core leakage test. A forecast issued AFTER the prediction
    time carries a deliberately wrong sentinel value (999.0) — if the
    join ever picks it up, that's a real leakage bug, not a style
    issue. Must always resolve to the forecast that was actually
    available at prediction time."""
    df = pd.DataFrame({
        "fetched_at": pd.to_datetime(["2026-06-01 10:00:00"], utc=True),
    })
    forecast = pd.DataFrame({
        "issued_at": pd.to_datetime([
            "2026-06-01 06:00:00",  # available at prediction time
            "2026-06-01 11:00:00",  # issued AFTER prediction time — must be ignored
        ], utc=True),
        "forecast_target_time": pd.to_datetime(["2026-06-01 11:00:00"] * 2, utc=True),
        "temperature_2m_c": [15.0, 999.0],  # 999 = leaked-future sentinel
        "precipitation_mm": [0.0, 0.0],
    })

    result = _add_forecast_features(df, forecast)
    assert result["forecast_temp_c"].iloc[0] == 15.0


def test_forecast_join_picks_the_most_recent_valid_forecast():
    """When multiple valid (issued_at <= fetched_at) forecasts exist
    for the same target hour, use the MOST RECENT one — a forecast
    issued closer to prediction time is more accurate in reality, and
    is also what a real serving system would actually have."""
    df = pd.DataFrame({
        "fetched_at": pd.to_datetime(["2026-06-01 10:00:00"], utc=True),
    })
    forecast = pd.DataFrame({
        "issued_at": pd.to_datetime([
            "2026-06-01 02:00:00",  # older, valid
            "2026-06-01 09:00:00",  # newer, valid — should win
        ], utc=True),
        "forecast_target_time": pd.to_datetime(["2026-06-01 11:00:00"] * 2, utc=True),
        "temperature_2m_c": [10.0, 22.0],
        "precipitation_mm": [0.0, 0.0],
    })
    result = _add_forecast_features(df, forecast)
    assert result["forecast_temp_c"].iloc[0] == 22.0


def test_forecast_join_returns_null_when_no_valid_forecast_exists():
    """No forecast was ever issued before prediction time for this
    target hour — must be null, not silently fall back to something
    issued later (which would be leakage) or raise."""
    df = pd.DataFrame({
        "fetched_at": pd.to_datetime(["2026-06-01 10:00:00"], utc=True),
    })
    forecast = pd.DataFrame({
        "issued_at": pd.to_datetime(["2026-06-01 11:00:00"], utc=True),  # only a future one exists
        "forecast_target_time": pd.to_datetime(["2026-06-01 11:00:00"], utc=True),
        "temperature_2m_c": [999.0],
        "precipitation_mm": [0.0],
    })
    result = _add_forecast_features(df, forecast)
    assert pd.isna(result["forecast_temp_c"].iloc[0])


def test_lag_features_only_look_backward():
    """A lag feature must never pull from a poll that happened AFTER
    the row's own fetched_at — same class of bug as the forecast one,
    just within the station_status data itself."""
    times = pd.date_range("2026-06-01 00:00", periods=10, freq="10min", tz="UTC")
    df = pd.DataFrame({
        "station_id": ["A"] * 10,
        "fetched_at": times,
        "num_bikes_available": list(range(10)),  # 0,1,2,...,9 — value == index
    })
    out = _add_lag_features(df)
    # Row 6 (index 6, value 6) should have lag_60m pointing to ~60 min
    # earlier = index 0 (value 0), never anything with a HIGHER value
    # than the row's own (which would mean pulling from the future).
    row6 = out.iloc[6]
    assert row6["num_bikes_available"] == 6
    if pd.notna(row6["lag_60m"]):
        assert row6["lag_60m"] <= row6["num_bikes_available"]


def test_neighbor_state_excludes_the_stations_own_value():
    """The neighbor average must be computed from OTHER stations only
    — including the station's own value would just be circular."""
    df = pd.DataFrame({
        "station_id": ["A", "B", "C"],
        "fetched_at": pd.to_datetime(["2026-06-01 10:00:00"] * 3, utc=True),
        "num_bikes_available": [10, 20, 30],
        "capacity": [20, 20, 20],  # ratios: 0.5, 1.0, 1.5
    })
    out = _add_neighbor_state(df)
    # For station A (ratio 0.5), neighbor avg should be mean(1.0, 1.5) = 1.25
    row_a = out[out.station_id == "A"].iloc[0]
    assert row_a["neighbor_avg_bikes_ratio"] == pytest.approx(1.25)


def test_cyclical_features_are_bounded():
    df = pd.DataFrame({"fetched_at": pd.date_range("2026-06-01", periods=48, freq="h", tz="UTC")})
    out = _add_cyclical_time_features(df, "fetched_at")
    for col in ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]:
        assert out[col].between(-1.0, 1.0).all()


def test_build_features_end_to_end_produces_target_column():
    """Smoke test: the full pipeline runs without error and produces
    a populated target column, on a small hand-built dataset."""
    times = pd.date_range("2026-06-01 00:00", periods=20, freq="10min", tz="UTC")
    station_status = pd.DataFrame({
        "station_id": ["A"] * 20,
        "fetched_at": times,
        "num_bikes_available": np.random.default_rng(0).integers(0, 20, 20),
        "num_docks_available": 20,
    })
    capacity = pd.DataFrame({"station_id": ["A"], "capacity": [20]})
    forecast = pd.DataFrame({
        "issued_at": pd.to_datetime(["2026-06-01 00:00:00"], utc=True),
        "forecast_target_time": pd.to_datetime(["2026-06-01 01:00:00"], utc=True),
        "temperature_2m_c": [20.0],
        "precipitation_mm": [0.0],
    })
    out = build_features(station_status, capacity, forecast)
    assert "target_bikes_available_60m" in out.columns
    assert len(out) == 20
