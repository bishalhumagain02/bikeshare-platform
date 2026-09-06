"""
Backfill historical Capital Bikeshare trip data, month by month.

The schema-drift problem this solves: Capital Bikeshare's monthly
CSVs changed format significantly around 2020. The OLD format used
"Duration", "Start date", "Start station number", "Member type"
(capitalized, human-phrased column names, duration in seconds, no
unique ride ID, no lat/lon). The NEW format (2020+, shared with
Divvy's schema) uses "ride_id", "started_at", "start_station_id",
"member_casual" (snake_case, has lat/lon, has rideable_type).

The plan is explicit: do NOT silently pd.concat() files across this
boundary. Column names alias onto totally different meanings, and a
naive concat would either crash or silently misalign data. Instead
we detect which era a file is and map it into ONE canonical schema
before anything downstream ever sees it.

Usage:
    python -m src.ingestion.fetch_trip_history --from 2024-01 --to 2024-03
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import zipfile

import httpx
import pandas as pd

from src.config import ACTIVE_SYSTEM, TRIPS_DIR

MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2.0


def _clean_station_id(series: pd.Series) -> pd.Series:
    """Format a station ID column as clean strings, avoiding the
    '31258.0' artifact: real Capital Bikeshare files sometimes have a
    handful of missing station IDs (the Week 1 finding), which forces
    pandas to read the WHOLE column as float64 (no NaN in a plain int
    column) — so a clean value like 31258 becomes the float 31258.0,
    and a bare .astype(str) then bakes that '.0' into the string
    permanently. This converts whole-number floats back to clean
    integer-looking strings, and preserves real nulls as null (not the
    literal string "nan")."""
    def _fmt(v):
        if pd.isna(v):
            return None
        try:
            f = float(v)
            if f.is_integer():
                return str(int(f))
        except (TypeError, ValueError):
            pass
        return str(v)

    return series.apply(_fmt)

# Canonical schema every era gets mapped into. Downstream code (dbt
# staging models, features) only ever needs to know this shape.
CANONICAL_COLUMNS = [
    "trip_id", "rideable_type", "started_at", "ended_at", "duration_seconds",
    "start_station_id", "start_station_name", "end_station_id", "end_station_name",
    "start_lat", "start_lng", "end_lat", "end_lng", "member_casual", "schema_era",
]

OLD_ERA_COLUMNS = {"Duration", "Start date", "Start station number", "Member type"}
NEW_ERA_COLUMNS = {"ride_id", "started_at", "start_station_id", "member_casual"}


def _fetch_with_retry(client: httpx.Client, url: str) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get(url, timeout=60.0)
            resp.raise_for_status()
            return resp
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_exc = exc
            sleep_for = BASE_BACKOFF_SECONDS * (2**attempt)
            print(f"  fetch failed (attempt {attempt + 1}/{MAX_RETRIES}): {exc} "
                  f"— retrying in {sleep_for:.0f}s", file=sys.stderr)
            time.sleep(sleep_for)
    assert last_exc is not None
    raise last_exc


def detect_era(columns: set[str]) -> str:
    """Return 'old', 'new', or raise if the shape is unrecognized —
    an unrecognized shape should fail loudly, not get force-concatenated."""
    if NEW_ERA_COLUMNS.issubset(columns):
        return "new"
    if OLD_ERA_COLUMNS.issubset(columns):
        return "old"
    raise ValueError(
        f"unrecognized trip CSV schema — columns were: {sorted(columns)}. "
        "This is neither the old nor new known Capital Bikeshare format. "
        "Add a new era mapping rather than forcing this through."
    )


# Canonical dtype for every column both eras must agree on. Column
# NAMES matching isn't enough — DuckDB refuses to read Parquet files
# with the same column name but incompatible physical types (hit in
# production: old era's all-null columns became Parquet's ambiguous
# "NULL type", and its cleanly-integer duration became int64 while new
# era's was always float64). Enforcing this explicitly, once, in one
# place, is more robust than hoping every column assignment above
# happens to agree.
CANONICAL_DTYPES = {
    "trip_id": "string",
    "rideable_type": "string",
    "duration_seconds": "float64",
    "start_station_id": "string",
    "start_station_name": "string",
    "end_station_id": "string",
    "end_station_name": "string",
    "start_lat": "Float64",
    "start_lng": "Float64",
    "end_lat": "Float64",
    "end_lng": "Float64",
    "member_casual": "string",
    "schema_era": "string",
}


def _enforce_canonical_dtypes(out: pd.DataFrame) -> pd.DataFrame:
    for col, dtype in CANONICAL_DTYPES.items():
        out[col] = out[col].astype(dtype)
    return out


def normalize_old_era(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    n = len(df)
    out["trip_id"] = pd.array([pd.NA] * n, dtype="string")  # old era has no unique ride ID
    out["rideable_type"] = pd.array([pd.NA] * n, dtype="string")  # not tracked pre-2020
    out["started_at"] = pd.to_datetime(
        df["Start date"], errors="coerce", utc=True, format="mixed"
    )
    out["ended_at"] = pd.to_datetime(
        df["End date"], errors="coerce", utc=True, format="mixed"
    )
    out["duration_seconds"] = pd.to_numeric(df["Duration"], errors="coerce")
    out["start_station_id"] = _clean_station_id(df["Start station number"])
    out["start_station_name"] = df["Start station"]
    out["end_station_id"] = _clean_station_id(df["End station number"])
    out["end_station_name"] = df["End station"]
    out["start_lat"] = pd.array([pd.NA] * n, dtype="Float64")
    out["start_lng"] = pd.array([pd.NA] * n, dtype="Float64")
    out["end_lat"] = pd.array([pd.NA] * n, dtype="Float64")
    out["end_lng"] = pd.array([pd.NA] * n, dtype="Float64")
    out["member_casual"] = df["Member type"].str.lower()
    out["schema_era"] = "old"
    return _enforce_canonical_dtypes(out)[CANONICAL_COLUMNS]


def normalize_new_era(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["trip_id"] = df["ride_id"]
    out["rideable_type"] = df["rideable_type"]
    # utc=True: real files sometimes mix timezone-aware timestamps
    # (e.g. "...T00:15:00-04:00") with timezone-naive ones in the SAME
    # column. Without forcing a single timezone, pandas can't build one
    # consistent datetime64 array and the later subtraction raises
    # "Cannot subtract tz-naive and tz-aware datetime-like objects" —
    # hit in production. utc=True normalizes everything to UTC first.
    #
    # format="mixed": pandas otherwise tries to infer ONE date format
    # from the column and cache it for speed — with genuinely mixed
    # formats present, that inference can misfire and wrongly mark
    # perfectly valid, differently-formatted rows as NaT — also hit in
    # production (a normal, well-formed timestamp coerced to NaT for no
    # reason other than a sibling row's differing format confusing the
    # inferred pattern). format="mixed" makes pandas parse each row
    # independently instead of assuming one shared format.
    out["started_at"] = pd.to_datetime(
        df["started_at"], errors="coerce", utc=True, format="mixed"
    )
    out["ended_at"] = pd.to_datetime(
        df["ended_at"], errors="coerce", utc=True, format="mixed"
    )
    duration = (out["ended_at"] - out["started_at"]).dt.total_seconds()
    # Plain float64, NOT pandas' nullable "Int64" dtype. Real Capital
    # Bikeshare files occasionally produce a duration Series that
    # pandas' nullable-Int64 safe-cast check rejects even after
    # to_numeric coercion (hit in production — root cause is a pandas
    # internal edge case, not something worth chasing further). Trip
    # duration doesn't need to be a strict integer; float64 handles
    # NaN natively with no equivalent safe-cast restriction, and
    # Parquet stores a float NaN as a clean null either way.
    out["duration_seconds"] = pd.to_numeric(duration, errors="coerce")
    out["start_station_id"] = _clean_station_id(df["start_station_id"])
    out["start_station_name"] = df["start_station_name"]
    out["end_station_id"] = _clean_station_id(df["end_station_id"])
    out["end_station_name"] = df["end_station_name"]
    out["start_lat"] = df["start_lat"]
    out["start_lng"] = df["start_lng"]
    out["end_lat"] = df["end_lat"]
    out["end_lng"] = df["end_lng"]
    out["member_casual"] = df["member_casual"].str.lower()
    out["schema_era"] = "new"
    return _enforce_canonical_dtypes(out)[CANONICAL_COLUMNS]


def normalize_trip_csv(raw_csv_text: str) -> pd.DataFrame:
    """Detect era, map to the canonical schema. Raises on unknown shapes
    rather than silently passing bad data through."""
    df = pd.read_csv(io.StringIO(raw_csv_text))
    era = detect_era(set(df.columns))
    if era == "old":
        return normalize_old_era(df)
    return normalize_new_era(df)


def _is_junk_zip_entry(name: str) -> bool:
    """macOS adds __MACOSX/ resource-fork metadata files to zips it
    creates — these aren't real data and shouldn't even attempt
    normalization (previously they'd hit detect_era and log a
    confusing 'unrecognized schema' warning every single month)."""
    return "__MACOSX/" in name or name.rsplit("/", 1)[-1].startswith("._")


def backfill_month(year: int, month: int) -> int:
    """Download one month's zip, normalize every CSV inside it, write
    one Parquet partition. Overwrites that month's file — safe to rerun."""
    filename = ACTIVE_SYSTEM.trip_history_pattern.format(year=year, month=month)
    url = ACTIVE_SYSTEM.trip_history_base_url + filename

    with httpx.Client(headers={"User-Agent": "bikeshare-platform/0.1"}) as client:
        resp = _fetch_with_retry(client, url)

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile:
        print(f"  {year}-{month:02d}: response was not a valid zip "
              f"(file may not exist yet for this month) — skipping", file=sys.stderr)
        return 0

    frames = []
    for name in zf.namelist():
        if not name.lower().endswith(".csv"):
            continue
        if _is_junk_zip_entry(name):
            continue  # macOS metadata junk, not real data — skip silently
        raw_text = zf.read(name).decode("utf-8", errors="replace")
        try:
            frames.append(normalize_trip_csv(raw_text))
        except ValueError as exc:
            print(f"  {year}-{month:02d}/{name}: {exc}", file=sys.stderr)

    if not frames:
        print(f"  {year}-{month:02d}: no usable CSVs found in zip", file=sys.stderr)
        return 0

    df = pd.concat(frames, ignore_index=True)
    df["system_id"] = ACTIVE_SYSTEM.system_id

    out_dir = TRIPS_DIR / f"year={year}" / f"month={month:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"trips_{year}{month:02d}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"  {year}-{month:02d}: {len(df)} trips (schema era: "
          f"{df['schema_era'].unique().tolist()}) -> {out_path}")
    return len(df)


def backfill_range(from_ym: str, to_ym: str) -> None:
    from_year, from_month = (int(x) for x in from_ym.split("-"))
    to_year, to_month = (int(x) for x in to_ym.split("-"))

    year, month = from_year, from_month
    total = 0
    while (year, month) <= (to_year, to_month):
        total += backfill_month(year, month)
        month += 1
        if month > 12:
            month = 1
            year += 1
    print(f"done — {total} trips backfilled")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_ym", required=True, help="YYYY-MM")
    parser.add_argument("--to", dest="to_ym", required=True, help="YYYY-MM")
    args = parser.parse_args()
    backfill_range(args.from_ym, args.to_ym)


if __name__ == "__main__":
    main()
