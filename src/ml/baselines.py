"""
Three baselines, per the plan: "Baselines first, before any ML.
Persistence (value right now), seasonal naive (same hour last week),
station-hour historical mean. Write their scores in your README. Many
published portfolio models silently lose to seasonal naive, and
knowing yours doesn't is the entire point."

All three take the SAME feature DataFrame the real model uses (from
build_features.py) so comparisons are apples-to-apples — same rows,
same target column, just different prediction logic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def predict_persistence(df: pd.DataFrame) -> pd.Series:
    """Prediction = whatever the station's bike count is RIGHT NOW.
    The simplest possible baseline: assumes nothing changes in 60 min."""
    return df["num_bikes_available"]


def predict_seasonal_naive(df: pd.DataFrame) -> pd.Series:
    """Prediction = the station's bike count at the SAME time of day,
    one week earlier. Falls back to persistence when a station doesn't
    have a full week of history yet (common early in this project,
    given how recently live polling started) rather than silently
    producing NaN predictions."""
    df = df.sort_values(["station_id", "fetched_at"]).copy()
    lookup = df[["station_id", "fetched_at", "num_bikes_available"]].copy()
    lookup["fetched_at"] = lookup["fetched_at"] + pd.Timedelta(days=7)

    merged = pd.merge_asof(
        df[["station_id", "fetched_at"]].sort_values("fetched_at"),
        lookup.sort_values("fetched_at").rename(columns={"num_bikes_available": "seasonal_pred"}),
        on="fetched_at",
        by="station_id",
        direction="nearest",
        tolerance=pd.Timedelta(hours=1),
    )
    merged = merged.sort_index()
    preds = merged["seasonal_pred"]
    # Fall back to persistence wherever no 1-week-prior value exists.
    return preds.fillna(df["num_bikes_available"])


def predict_station_hour_mean(train_df: pd.DataFrame, eval_df: pd.DataFrame) -> pd.Series:
    """Prediction = the historical average bikes_available for this
    station at this hour of day, computed ONLY from train_df — using
    eval_df's own values here would leak the answer into the baseline,
    the exact same leakage class the real model has to avoid."""
    train_df = train_df.copy()
    train_df["hour"] = train_df["fetched_at"].dt.hour
    station_hour_means = (
        train_df.groupby(["station_id", "hour"])["num_bikes_available"].mean()
    )

    eval_df = eval_df.copy()
    eval_df["hour"] = eval_df["fetched_at"].dt.hour
    preds = eval_df.set_index(["station_id", "hour"]).index.map(station_hour_means)
    preds = pd.Series(preds, index=eval_df.index, dtype="float64")
    # Fall back to the overall training mean for any (station, hour)
    # combination never seen in training.
    return preds.fillna(train_df["num_bikes_available"].mean())


def mae(y_true: pd.Series, y_pred: pd.Series) -> float:
    mask = y_true.notna() & y_pred.notna()
    return float(np.abs(y_true[mask] - y_pred[mask]).mean())
