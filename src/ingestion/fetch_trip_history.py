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


def normalize_old_era(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["trip_id"] = None  # old era has no unique ride identifier
    out["rideable_type"] = None  # not tracked pre-2020
    out["started_at"] = pd.to_datetime(df["Start date"])
    out["ended_at"] = pd.to_datetime(df["End date"])
    out["duration_seconds"] = df["Duration"].astype("Int64")
    out["start_station_id"] = df["Start station number"].astype(str)
    out["start_station_name"] = df["Start station"]
    out["end_station_id"] = df["End station number"].astype(str)
    out["end_station_name"] = df["End station"]
    out["start_lat"] = None
    out["start_lng"] = None
    out["end_lat"] = None
    out["end_lng"] = None
    out["member_casual"] = df["Member type"].str.lower()
    out["schema_era"] = "old"
    return out[CANONICAL_COLUMNS]


def normalize_new_era(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["trip_id"] = df["ride_id"]
    out["rideable_type"] = df["rideable_type"]
    out["started_at"] = pd.to_datetime(df["started_at"])
    out["ended_at"] = pd.to_datetime(df["ended_at"])
    duration = (out["ended_at"] - out["started_at"]).dt.total_seconds()
    out["duration_seconds"] = duration.astype("Int64")
    out["start_station_id"] = df["start_station_id"].astype(str)
    out["start_station_name"] = df["start_station_name"]
    out["end_station_id"] = df["end_station_id"].astype(str)
    out["end_station_name"] = df["end_station_name"]
    out["start_lat"] = df["start_lat"]
    out["start_lng"] = df["start_lng"]
    out["end_lat"] = df["end_lat"]
    out["end_lng"] = df["end_lng"]
    out["member_casual"] = df["member_casual"].str.lower()
    out["schema_era"] = "new"
    return out[CANONICAL_COLUMNS]


def normalize_trip_csv(raw_csv_text: str) -> pd.DataFrame:
    """Detect era, map to the canonical schema. Raises on unknown shapes
    rather than silently passing bad data through."""
    df = pd.read_csv(io.StringIO(raw_csv_text))
    era = detect_era(set(df.columns))
    if era == "old":
        return normalize_old_era(df)
    return normalize_new_era(df)


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
