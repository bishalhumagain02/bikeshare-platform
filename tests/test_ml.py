"""
Tests for src/ml/baselines.py and the fold-generation logic in
src/ml/train.py.

test_folds_never_index_out_of_bounds and
test_folds_are_robust_to_gaps_in_data are regression tests for two
real bugs hit while building this: an off-by-one in the quantile
indexing, and fold boundaries becoming degenerate (empty test
windows, a suspicious persistence_mae=0.0) when stray/gappy timestamps
skewed a naive min-max time-division approach.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.baselines import (
    mae,
    predict_persistence,
    predict_seasonal_naive,
    predict_station_hour_mean,
)
from src.ml.train import make_rolling_origin_folds


def test_persistence_prediction_is_just_the_current_value():
    df = pd.DataFrame({"num_bikes_available": [5, 10, 0, 20]})
    result = predict_persistence(df)
    assert result.tolist() == [5, 10, 0, 20]


def test_seasonal_naive_falls_back_to_persistence_without_a_week_of_history():
    """Only 2 days of data exist — no row has a real value from 7 days
    earlier, so every prediction must fall back to persistence rather
    than silently producing NaN."""
    times = pd.date_range("2026-06-01", periods=5, freq="h", tz="UTC")
    df = pd.DataFrame({
        "station_id": ["A"] * 5,
        "fetched_at": times,
        "num_bikes_available": [1, 2, 3, 4, 5],
    })
    result = predict_seasonal_naive(df)
    assert result.tolist() == [1, 2, 3, 4, 5]


def test_station_hour_mean_never_uses_eval_data():
    """The baseline must be computed from train_df ONLY — this is the
    same leakage class as everything else in this project. Eval rows
    with an extreme value must not shift the baseline's own prediction
    for those same rows."""
    train = pd.DataFrame({
        "station_id": ["A", "A", "A"],
        "fetched_at": pd.to_datetime(["2026-06-01 08:00"] * 3, utc=True),
        "num_bikes_available": [10, 10, 10],
    })
    eval_df = pd.DataFrame({
        "station_id": ["A"],
        "fetched_at": pd.to_datetime(["2026-06-02 08:00"], utc=True),
        "num_bikes_available": [999],  # extreme eval-only value
    })
    pred = predict_station_hour_mean(train, eval_df)
    assert pred.iloc[0] == 10.0  # must reflect only train, never the 999


def test_mae_ignores_null_pairs():
    y_true = pd.Series([1.0, 2.0, np.nan, 4.0])
    y_pred = pd.Series([1.0, 3.0, 5.0, np.nan])
    # Valid pairs: index 0 (|1-1|=0), index 1 (|2-3|=1). Indices 2 and 3
    # each have one side null and must be excluded. Mean of [0, 1] = 0.5.
    assert mae(y_true, y_pred) == pytest.approx(0.5)


def test_folds_never_index_out_of_bounds():
    """Regression test for a real off-by-one bug: the last quantile
    point computed to exactly n_rows, one past the last valid .iloc
    index, crashing with IndexError on every run."""
    times = pd.date_range("2026-06-01", periods=500, freq="10min", tz="UTC")
    df = pd.DataFrame({"fetched_at": times})
    folds = make_rolling_origin_folds(df)  # must not raise
    assert len(folds) > 0
    for train_end, test_start, test_end in folds:
        assert test_start > train_end
        assert test_end > test_start


def test_folds_are_robust_to_gaps_in_data():
    """Regression test for a real bug: a small cluster of far-future
    stray timestamps (simulating leftover/contaminated data — exactly
    what happened during development) skewed naive min-max time
    division into producing an empty fold. Quantile-based cutpoints
    must instead give every fold a comparable row count regardless of
    how unevenly the timestamps are distributed."""
    dense_period = pd.date_range("2026-06-01", periods=1000, freq="10min", tz="UTC")
    stray_future = pd.date_range("2026-08-01", periods=5, freq="h", tz="UTC")
    times = pd.Series(list(dense_period) + list(stray_future))
    df = pd.DataFrame({"fetched_at": times})

    folds = make_rolling_origin_folds(df)
    for _train_end, test_start, test_end in folds:
        n_test = ((df["fetched_at"] >= test_start) & (df["fetched_at"] < test_end)).sum()
        assert n_test > 0, "a fold's test window was empty — the gap-robustness fix regressed"
