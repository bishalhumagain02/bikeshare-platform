"""
Tests for src/ingestion/fetch_trip_history.py

The property that matters: old-era and new-era CSVs must map onto
IDENTICAL canonical columns, so downstream code never has to know
which era a row came from. And an unrecognized shape must raise,
never get silently concatenated (that's the bug the plan warns about).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.fetch_trip_history import (
    CANONICAL_COLUMNS,
    detect_era,
    normalize_trip_csv,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def old_era_csv() -> str:
    return (FIXTURES / "trip_history_old_era.csv").read_text()


@pytest.fixture
def new_era_csv() -> str:
    return (FIXTURES / "trip_history_new_era.csv").read_text()


def test_detects_old_era(old_era_csv):
    df = pd.read_csv(pd.io.common.StringIO(old_era_csv))
    assert detect_era(set(df.columns)) == "old"


def test_detects_new_era(new_era_csv):
    df = pd.read_csv(pd.io.common.StringIO(new_era_csv))
    assert detect_era(set(df.columns)) == "new"


def test_unrecognized_schema_raises_loudly():
    """An unknown shape must fail, not silently get force-concatenated —
    this is the exact bug the plan calls out as a real failure mode."""
    with pytest.raises(ValueError, match="unrecognized trip CSV schema"):
        detect_era({"some_totally_different_column", "another_one"})


def test_old_era_normalizes_to_canonical_shape(old_era_csv):
    out = normalize_trip_csv(old_era_csv)
    assert list(out.columns) == CANONICAL_COLUMNS
    assert len(out) == 3
    assert (out["schema_era"] == "old").all()


def test_new_era_normalizes_to_canonical_shape(new_era_csv):
    out = normalize_trip_csv(new_era_csv)
    assert list(out.columns) == CANONICAL_COLUMNS
    assert len(out) == 3
    assert (out["schema_era"] == "new").all()


def test_both_eras_produce_identical_columns_and_dtypes(old_era_csv, new_era_csv):
    """This is the actual point: downstream code should never need to
    branch on era. Same columns, compatible types, every time."""
    old_out = normalize_trip_csv(old_era_csv)
    new_out = normalize_trip_csv(new_era_csv)
    assert list(old_out.columns) == list(new_out.columns)


def test_old_era_duration_taken_directly(old_era_csv):
    out = normalize_trip_csv(old_era_csv)
    # First row in fixture: Duration=634
    assert out.iloc[0]["duration_seconds"] == 634


def test_new_era_duration_computed_from_timestamps(new_era_csv):
    """New era has no Duration column — it must be derived from
    started_at/ended_at, not left null."""
    out = normalize_trip_csv(new_era_csv)
    # First row: 00:02:15 -> 00:14:02 = 707 seconds
    assert out.iloc[0]["duration_seconds"] == 707


def test_member_casual_normalized_lowercase_both_eras(old_era_csv, new_era_csv):
    old_out = normalize_trip_csv(old_era_csv)
    new_out = normalize_trip_csv(new_era_csv)
    assert set(old_out["member_casual"].unique()) <= {"member", "casual"}
    assert set(new_out["member_casual"].unique()) <= {"member", "casual"}


def test_old_era_has_no_lat_lon(old_era_csv):
    """Old era genuinely doesn't have this data — must be null, not
    fabricated or dropped from the schema."""
    out = normalize_trip_csv(old_era_csv)
    assert out["start_lat"].isna().all()
    assert out["end_lat"].isna().all()


def test_new_era_has_real_lat_lon(new_era_csv):
    out = normalize_trip_csv(new_era_csv)
    assert out["start_lat"].notna().all()
    assert out.iloc[0]["start_lat"] == pytest.approx(38.8893)
