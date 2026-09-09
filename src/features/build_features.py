"""
Builds the feature matrix for predicting bikes_available 60 minutes
ahead. Shared by both training (this module) and, eventually, serving
(Week 6) — per the plan, this is the ONE place feature logic lives, so
train and serve can never silently drift apart.

LEAKAGE TRAPS THIS MODULE SPECIFICALLY GUARDS AGAINST (see the plan's
own list):
1. Weather ACTUALS as a feature — at prediction time you only have a
   FORECAST, which carries error. This module joins stg_weather_forecast
   (issued_at-stamped), never stg_weather_hourly (actuals), for any
   feature describing the future.
2. Using a forecast issued AFTER the prediction time — the as-of join
   below explicitly filters to issued_at <= prediction_time before
   picking the most recent applicable forecast.
3. Computing rolling/aggregate features over windows that include the
   future — every rolling window here is backward-looking only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _add_cyclical_time_features(df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    hour = df[time_col].dt.hour + df[time_col].dt.minute / 60.0
    dow = df[time_col].dt.dayofweek
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    return df


def _add_lag_features(station_df: pd.DataFrame) -> pd.DataFrame:
    """station_df: one station's polls, sorted by fetched_at, with a
    regular-ish ~10-min cadence. Lags are picked via merge_asof on time
    (backward), not a fixed row-count shift — robust to gaps in polling
    (which WILL happen — laptop off, GitHub Actions hiccup, etc.)."""
    station_df = station_df.sort_values("fetched_at").reset_index(drop=True)
    lagged = station_df[["fetched_at", "num_bikes_available"]].copy()

    out = station_df.copy()
    for label, minutes in [("lag_15m", 15), ("lag_30m", 30), ("lag_60m", 60)]:
        lookup_time = station_df[["fetched_at"]].copy()
        lookup_time["lookup_at"] = lookup_time["fetched_at"] - pd.Timedelta(minutes=minutes)
        merged = pd.merge_asof(
            lookup_time.sort_values("lookup_at"),
            lagged.sort_values("fetched_at").rename(columns={"fetched_at": "src_time"}),
            left_on="lookup_at",
            right_on="src_time",
            direction="backward",
            tolerance=pd.Timedelta(minutes=minutes + 5),  # don't reach further back than sensible
        )
        merged = merged.sort_index()  # merge_asof requires sorted input; restore original order
        out[label] = merged["num_bikes_available"].to_numpy()

    # Backward-looking rolling mean over the last 60 minutes — window
    # only ever includes past polls, never future ones.
    out = out.set_index("fetched_at")
    out["rolling_mean_60m"] = out["num_bikes_available"].rolling("60min", min_periods=1).mean()
    out = out.reset_index()
    return out


def _add_neighbor_state(df: pd.DataFrame) -> pd.DataFrame:
    """Spatial signal: at each poll timestamp, the average
    bikes-available RATIO across every OTHER station's most recent
    poll at or before that time. Real-world polls across stations
    happen together in one batch (one API call returns all stations at
    once), so an exact-time join is appropriate here — not an as-of
    join like the weather one, which crosses genuinely separate data
    sources."""
    df = df.copy()
    df["bikes_ratio"] = df["num_bikes_available"] / df["capacity"].replace(0, np.nan)

    station_avg_at_time = (
        df.groupby("fetched_at")
        .agg(_sum_ratio=("bikes_ratio", "sum"), _n=("bikes_ratio", "count"))
        .reset_index()
    )
    df = df.merge(station_avg_at_time, on="fetched_at", how="left")
    # Exclude the station's own value from the neighbor average.
    df["neighbor_avg_bikes_ratio"] = (
        (df["_sum_ratio"] - df["bikes_ratio"]) / (df["_n"] - 1).replace(0, np.nan)
    )
    return df.drop(columns=["_sum_ratio", "_n"])


def _add_forecast_features(df: pd.DataFrame, forecast_df: pd.DataFrame) -> pd.DataFrame:
    """THE core leakage guard. For each row (prediction made at
    `fetched_at`, target time `fetched_at` + 60min), find the weather
    forecast for that target hour AS IT WAS KNOWN at `fetched_at` —
    i.e. the most recently issued forecast with issued_at <= fetched_at.
    A forecast issued after fetched_at is invisible to this join by
    construction, not by a filter that could be forgotten."""
    df = df.copy()
    df["target_hour"] = (df["fetched_at"] + pd.Timedelta(minutes=60)).dt.floor("h")

    df_sorted = df.sort_values("fetched_at")

    # pandas' merge_asof `by=` needs matching column NAMES on both
    # sides, so rename before joining.
    forecast_renamed = forecast_df.rename(columns={
        "forecast_target_time": "target_hour",
        "temperature_2m_c": "forecast_temp_c",
        "precipitation_mm": "forecast_precip_mm",
    }).sort_values("issued_at")

    merged = pd.merge_asof(
        df_sorted,
        forecast_renamed[["target_hour", "issued_at", "forecast_temp_c", "forecast_precip_mm"]],
        left_on="fetched_at",
        right_on="issued_at",
        by="target_hour",
        direction="backward",
    )
    return merged.sort_index()


def build_features(
    station_status: pd.DataFrame,
    station_capacity: pd.DataFrame,
    weather_forecast: pd.DataFrame,
) -> pd.DataFrame:
    """
    station_status: columns [station_id, fetched_at, num_bikes_available,
        num_docks_available] — one row per raw poll.
    station_capacity: columns [station_id, capacity].
    weather_forecast: columns [issued_at, forecast_target_time,
        temperature_2m_c, precipitation_mm].

    Returns a feature matrix with one row per (station, poll time),
    including the target column `target_bikes_available_60m` (the
    ACTUAL bikes_available 60 minutes later — this is the label, not a
    feature, so it legitimately comes from the future).
    """
    df = station_status.merge(station_capacity, on="station_id", how="left")
    df = _add_cyclical_time_features(df, "fetched_at")

    per_station = []
    for _station_id, group in df.groupby("station_id"):
        per_station.append(_add_lag_features(group))
    df = pd.concat(per_station, ignore_index=True)

    df = _add_neighbor_state(df)
    df = _add_forecast_features(df, weather_forecast)

    # Target: actual bikes_available 60 min later, per station — found
    # via the same kind of as-of join as the lags, just looking forward
    # instead of backward. This is the label we're trying to predict,
    # so pulling from the future here is correct, not leakage.
    target_frames = []
    for _station_id, group in df.groupby("station_id"):
        group = group.sort_values("fetched_at").reset_index(drop=True)
        lookup = group[["fetched_at"]].copy()
        lookup["target_time"] = lookup["fetched_at"] + pd.Timedelta(minutes=60)
        future = group[["fetched_at", "num_bikes_available"]].rename(
            columns={"fetched_at": "src_time", "num_bikes_available": "target_bikes_available_60m"}
        )
        merged = pd.merge_asof(
            lookup.sort_values("target_time"),
            future.sort_values("src_time"),
            left_on="target_time",
            right_on="src_time",
            direction="forward",
            tolerance=pd.Timedelta(minutes=15),
        )
        merged = merged.sort_index()
        group["target_bikes_available_60m"] = merged["target_bikes_available_60m"].to_numpy()
        target_frames.append(group)
    df = pd.concat(target_frames, ignore_index=True)

    return df
