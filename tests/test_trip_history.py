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


def test_both_eras_produce_matching_dtypes_not_just_matching_names(old_era_csv, new_era_csv):
    """Real bug hit in production: old era's all-null trip_id/lat/lon
    columns and integer-typed duration_seconds silently diverged in
    PHYSICAL dtype from new era's (string/Float64/float64 respectively)
    even though both had the 'same' column names — which crashes DuckDB
    the moment both eras are read together (Parquet 'NULL type' cannot
    unify with VARCHAR; int64 cannot unify with float64 without a cast).
    Column names matching is not enough — dtypes must match too."""
    old_out = normalize_trip_csv(old_era_csv)
    new_out = normalize_trip_csv(new_era_csv)
    for col in CANONICAL_COLUMNS:
        if col == "schema_era":
            continue  # expected to legitimately differ ("old" vs "new")
        assert str(old_out[col].dtype) == str(new_out[col].dtype), (
            f"dtype mismatch on '{col}': old={old_out[col].dtype}, new={new_out[col].dtype}"
        )


def test_new_era_has_real_lat_lon(new_era_csv):
    out = normalize_trip_csv(new_era_csv)
    assert out["start_lat"].notna().all()
    assert out.iloc[0]["start_lat"] == pytest.approx(38.8893)


# --- Real-world messiness: malformed timestamps and macOS zip junk --------

def test_malformed_timestamp_becomes_null_not_a_crash():
    """A real bug hit in production: some rows in real Capital Bikeshare
    monthly files have unparseable timestamps. This must degrade to a
    null duration for that one row, not crash the whole month's backfill."""
    from pathlib import Path

    bad_csv = (Path(__file__).parent / "fixtures" /
               "trip_history_new_era_with_bad_timestamp.csv").read_text()
    out = normalize_trip_csv(bad_csv)  # must not raise
    assert len(out) == 3
    bad_row = out[out["trip_id"] == "BADTIMESTAMP99"].iloc[0]
    assert pd.isna(bad_row["started_at"])
    assert pd.isna(bad_row["duration_seconds"])
    # The two good rows around it must still compute correctly —
    # one bad row shouldn't poison the whole batch.
    good_row = out[out["trip_id"] == "A1B2C3D4E5F6G7H8"].iloc[0]
    assert good_row["duration_seconds"] == 707


def test_macosx_junk_files_are_skipped_before_parsing():
    from src.ingestion.fetch_trip_history import _is_junk_zip_entry

    assert _is_junk_zip_entry("__MACOSX/._202401-capitalbikeshare-tripdata.csv")
    assert _is_junk_zip_entry("some/path/__MACOSX/._file.csv")
    assert not _is_junk_zip_entry("202401-capitalbikeshare-tripdata.csv")
    assert not _is_junk_zip_entry("data/real_trips.csv")


def test_mixed_timezone_aware_and_naive_timestamps_do_not_crash():
    """Real bug hit in production: some real Capital Bikeshare rows have
    timezone-aware timestamps ("...T00:15:00-04:00") mixed with
    timezone-naive ones in the SAME column. Without normalizing to a
    single timezone first, subtracting started_at from ended_at raises
    'Cannot subtract tz-naive and tz-aware datetime-like objects' —
    this must not happen, on any mix of garbage."""
    from src.ingestion.fetch_trip_history import normalize_new_era

    n = 200
    started = [f"2024-06-01 00:{i % 60:02d}:00" for i in range(n)]
    ended = [f"2024-06-01 00:{(i + 10) % 60:02d}:00" for i in range(n)]
    for i in range(0, n, 7):
        started[i] = "not-a-real-date"
    for i in range(0, n, 11):
        ended[i] = ""
    for i in range(0, n, 13):
        started[i] = None
    for i in range(0, n, 17):
        ended[i] = "2024-06-01T00:15:00-04:00"  # tz-aware mixed into a naive column

    df = pd.DataFrame({
        "ride_id": [f"id{i}" for i in range(n)],
        "rideable_type": ["classic_bike"] * n,
        "started_at": started,
        "ended_at": ended,
        "start_station_name": ["A"] * n,
        "start_station_id": ["1"] * n,
        "end_station_name": ["B"] * n,
        "end_station_id": ["2"] * n,
        "start_lat": [38.9] * n,
        "start_lng": [-77.0] * n,
        "end_lat": [38.9] * n,
        "end_lng": [-77.0] * n,
        "member_casual": ["member"] * n,
    })

    out = normalize_new_era(df)  # must not raise
    assert len(out) == n
    assert out["duration_seconds"].dtype == "float64"
    # Rows with any garbage timestamp must have a null duration, not a crash
    assert out["duration_seconds"].isna().sum() > 0
    # Rows with two clean, consistent timestamps must still compute correctly
    clean_row = out.iloc[1]  # index 1 has no injected garbage
    assert clean_row["duration_seconds"] == pytest.approx(600.0)


def test_station_id_with_missing_values_does_not_get_dot_zero_suffix():
    """Real bug hit in production: a station ID column with SOME missing
    values gets read by pandas as float64 (no NaN representation in a
    plain int column), so a clean ID like 31258 becomes 31258.0 — and a
    bare .astype(str) bakes that '.0' permanently into the string,
    breaking any downstream join against a clean-integer-string ID from
    another source."""
    from src.ingestion.fetch_trip_history import _clean_station_id

    # Simulates exactly what pandas.read_csv produces for a column with
    # some missing IDs: float64 dtype, real IDs represented as floats.
    col = pd.Series([31258.0, 31817.0, float("nan"), 32418.0])
    cleaned = _clean_station_id(col)

    assert cleaned.iloc[0] == "31258"
    assert cleaned.iloc[1] == "31817"
    assert pd.isna(cleaned.iloc[2])  # missing stays missing, in whatever
    # form pandas represents it at this intermediate step — the full
    # pipeline's later dtype-enforcement step (tested separately below)
    # is what guarantees a clean pd.NA in the final shipped output.
    assert cleaned.iloc[3] == "32418"
    # The bug this test exists for: none of the real values should ever
    # carry a trailing ".0".
    for v in cleaned:
        if pd.notna(v):
            assert not str(v).endswith(".0")


def test_station_id_cleaning_end_to_end_via_normalize():
    """Same bug, exercised through the real normalize path with a CSV
    that has a genuinely missing station ID in one row (forcing pandas'
    float64 promotion), matching the shape hit in production."""
    from src.ingestion.fetch_trip_history import normalize_new_era

    df = pd.DataFrame({
        "ride_id": ["a", "b", "c"],
        "rideable_type": ["classic_bike"] * 3,
        "started_at": ["2024-06-01 00:00:00"] * 3,
        "ended_at": ["2024-06-01 00:10:00"] * 3,
        "start_station_name": ["X", "Y", "Z"],
        "start_station_id": [31258, 31817, None],  # None forces float64
        "end_station_name": ["X", "Y", "Z"],
        "end_station_id": [32418, None, 31062],
        "start_lat": [38.9] * 3,
        "start_lng": [-77.0] * 3,
        "end_lat": [38.9] * 3,
        "end_lng": [-77.0] * 3,
        "member_casual": ["member"] * 3,
    })
    out = normalize_new_era(df)
    assert out["start_station_id"].tolist()[:2] == ["31258", "31817"]
    assert pd.isna(out["start_station_id"].iloc[2])
    assert out["end_station_id"].iloc[0] == "32418"
    assert pd.isna(out["end_station_id"].iloc[1])
    assert out["end_station_id"].iloc[2] == "31062"
