"""
Trains the bike-availability model with a rolling-origin backtest —
NOT a random train/test split, which the plan specifically calls out
as a leakage trap on temporal data (it would let the model "see"
patterns from timestamps that happen to sit near training rows
chronologically, an unrealistic advantage a real deployed model would
never have).

Adapts the number of backtest folds to however much real history
exists — with only days of real station_status polling so far (see
docs/DECISIONS.md), a full 4-fold rolling-origin backtest spanning
different weeks/seasons isn't yet possible. This script uses as many
folds as the data honestly supports and prints exactly how many, so
results are never presented as more robust than they are.

Usage:
    python -m src.ml.train
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import lightgbm as lgb
import mlflow
import pandas as pd

from src.features.build_features import build_features
from src.ml.baselines import (
    mae,
    predict_persistence,
    predict_seasonal_naive,
    predict_station_hour_mean,
)

DB_PATH = Path(__file__).resolve().parents[2] / "dbt" / "bikeshare.duckdb"
MIN_FOLD_HOURS = 12  # each fold's test window needs at least this much data to be meaningful
TARGET_FOLDS = 4  # the plan's target — used only if enough history actually exists

FEATURE_COLUMNS = [
    "capacity",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "lag_15m", "lag_30m", "lag_60m", "rolling_mean_60m",
    "neighbor_avg_bikes_ratio",
    "forecast_temp_c", "forecast_precip_mm",
]
TARGET_COLUMN = "target_bikes_available_60m"


def load_feature_data() -> pd.DataFrame:
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}. Run `dbt build` first.", file=sys.stderr)
        sys.exit(1)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    station_status = con.execute(
        "select station_id, fetched_at, num_bikes_available, num_docks_available "
        "from stg_station_status"
    ).df()
    capacity = con.execute("select station_id, capacity from dim_station where is_current").df()
    forecast = con.execute(
        "select issued_at, forecast_target_time, temperature_2m_c, precipitation_mm "
        "from stg_weather_forecast"
    ).df()
    con.close()

    df = build_features(station_status, capacity, forecast)
    return df.dropna(subset=[TARGET_COLUMN])


def make_rolling_origin_folds(
    df: pd.DataFrame,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Returns a list of (train_end, test_start, test_end) cutpoints.
    Each fold trains on everything before train_end, tests on
    [test_start, test_end) — test_start includes a small purge gap
    after train_end so no train row is within 60 min of a test row
    (which would otherwise leak, since the target itself is 60 min
    in the future).

    Cutpoints are chosen by QUANTILES OF ACTUAL ROW TIMESTAMPS, not by
    dividing the raw min-max time span evenly. Real polling data has
    gaps (a laptop off, a GitHub Actions hiccup, or — as hit while
    testing this — stray data far outside the intended window) that
    would otherwise silently produce an empty or tiny fold; quantile
    cutpoints guarantee every fold gets a comparable amount of actual
    data regardless of how it's distributed in time."""
    purge = pd.Timedelta(minutes=60)
    times = df["fetched_at"].sort_values().reset_index(drop=True)
    n_rows = len(times)

    # Need enough rows for at least a 1-fold split with meaningful
    # train/test sizes on each side.
    approx_hours = (times.iloc[-1] - times.iloc[0]).total_seconds() / 3600
    n_folds = max(1, min(TARGET_FOLDS, int(approx_hours // MIN_FOLD_HOURS) - 1))
    if n_folds < TARGET_FOLDS:
        print(
            f"WARNING: only ~{approx_hours:.1f} hours of real history available — "
            f"running {n_folds} fold(s) instead of the plan's target of {TARGET_FOLDS}. "
            "Treat these results as preliminary; re-run once more history accumulates.",
            file=sys.stderr,
        )

    # (n_folds + 1) roughly equal-ROW-COUNT chunks — the first chunk is
    # always training-only "warm-up", each subsequent chunk boundary is
    # one fold's train_end/test_end.
    quantile_points = [
        times.iloc[min(int(n_rows * q / (n_folds + 1)), n_rows - 1)]
        for q in range(1, n_folds + 2)
    ]

    folds = []
    for i in range(n_folds):
        train_end = quantile_points[i]
        test_end = quantile_points[i + 1]
        test_start = train_end + purge
        if test_end <= test_start:
            continue
        folds.append((train_end, test_start, test_end))
    return folds


def run_backtest(df: pd.DataFrame) -> pd.DataFrame:
    folds = make_rolling_origin_folds(df)
    print(f"Running {len(folds)} rolling-origin fold(s)")

    results = []
    for i, (train_end, test_start, test_end) in enumerate(folds):
        train = df[df["fetched_at"] < train_end]
        test = df[(df["fetched_at"] >= test_start) & (df["fetched_at"] < test_end)]
        if len(train) < 20 or len(test) < 5:
            print(f"  fold {i}: skipped, insufficient rows (train={len(train)}, test={len(test)})")
            continue

        model = lgb.LGBMRegressor(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            min_child_samples=5, verbosity=-1,
        )
        X_train, y_train = train[FEATURE_COLUMNS], train[TARGET_COLUMN]
        X_test, y_test = test[FEATURE_COLUMNS], test[TARGET_COLUMN]
        model.fit(X_train, y_train)
        model_preds = model.predict(X_test)

        fold_result = {
            "fold": i,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "n_train": len(train),
            "n_test": len(test),
            "model_mae": mae(y_test, pd.Series(model_preds, index=y_test.index)),
            "persistence_mae": mae(y_test, predict_persistence(test)),
            "seasonal_naive_mae": mae(y_test, predict_seasonal_naive(df.loc[test.index])),
            "station_hour_mean_mae": mae(y_test, predict_station_hour_mean(train, test)),
        }
        results.append(fold_result)
        print(
            f"  fold {i}: model MAE={fold_result['model_mae']:.3f} | "
            f"persistence={fold_result['persistence_mae']:.3f} | "
            f"seasonal_naive={fold_result['seasonal_naive_mae']:.3f} | "
            f"station_hour_mean={fold_result['station_hour_mean_mae']:.3f}"
        )

    return pd.DataFrame(results)


def train_final_model(df: pd.DataFrame) -> lgb.LGBMRegressor:
    """Trains on ALL available data for the model that would actually
    be saved/served — the backtest above is for honest evaluation
    only, this is the artifact itself."""
    model = lgb.LGBMRegressor(
        n_estimators=200, max_depth=6, learning_rate=0.05,
        min_child_samples=5, verbosity=-1,
    )
    model.fit(df[FEATURE_COLUMNS], df[TARGET_COLUMN])
    return model


def main() -> None:
    df = load_feature_data()
    print(f"Loaded {len(df)} feature rows spanning "
          f"{df['fetched_at'].min()} to {df['fetched_at'].max()}")

    mlflow.set_experiment("bikeshare-availability")
    with mlflow.start_run():
        backtest_results = run_backtest(df)

        if len(backtest_results) == 0:
            print("No folds could be run — not enough data yet.", file=sys.stderr)
            sys.exit(1)

        avg_model_mae = backtest_results["model_mae"].mean()
        avg_persistence_mae = backtest_results["persistence_mae"].mean()
        avg_seasonal_mae = backtest_results["seasonal_naive_mae"].mean()
        avg_station_hour_mae = backtest_results["station_hour_mean_mae"].mean()

        n_seasonal_valid = backtest_results["seasonal_naive_mae"].notna().sum()
        if n_seasonal_valid < len(backtest_results):
            print(
                f"NOTE: seasonal-naive MAE only computed on {n_seasonal_valid}/"
                f"{len(backtest_results)} folds — the others didn't have a full "
                "7-day-prior lookback available yet (expected, given how little "
                "real history currently exists). The averages below reflect only "
                "the folds where each baseline was actually computable.",
                file=sys.stderr,
            )

        mlflow.log_param("n_folds", len(backtest_results))
        mlflow.log_param("n_estimators", 200)
        mlflow.log_param("max_depth", 6)
        mlflow.log_metric("model_mae", avg_model_mae)
        mlflow.log_metric("persistence_mae", avg_persistence_mae)
        mlflow.log_metric("seasonal_naive_mae", avg_seasonal_mae)
        mlflow.log_metric("station_hour_mean_mae", avg_station_hour_mae)

        print()
        print("=== Backtest summary (averaged across folds) ===")
        print(f"Model (LightGBM):     MAE = {avg_model_mae:.3f}")
        print(f"Persistence baseline: MAE = {avg_persistence_mae:.3f}")
        print(f"Seasonal-naive:       MAE = {avg_seasonal_mae:.3f}")
        print(f"Station-hour-mean:    MAE = {avg_station_hour_mae:.3f}")

        best_baseline = min(avg_persistence_mae, avg_seasonal_mae, avg_station_hour_mae)
        if avg_model_mae < best_baseline:
            print(f"\nModel beats the best baseline by {best_baseline - avg_model_mae:.3f} MAE.")
        else:
            print(
                f"\nModel does NOT beat the best baseline "
                f"(worse by {avg_model_mae - best_baseline:.3f} MAE). "
                "This is a real, honestly-reported result — see the plan's own note that "
                "many published portfolio models silently lose to seasonal naive."
            )

        final_model = train_final_model(df)
        importances = pd.Series(
            final_model.feature_importances_, index=FEATURE_COLUMNS
        ).sort_values(ascending=False)
        print("\n=== Feature importances (final model, trained on all data) ===")
        print(importances)

        for feat, imp in importances.items():
            mlflow.log_metric(f"importance_{feat}", float(imp))

        backtest_results.to_csv("backtest_results.csv", index=False)
        mlflow.log_artifact("backtest_results.csv")


if __name__ == "__main__":
    main()
