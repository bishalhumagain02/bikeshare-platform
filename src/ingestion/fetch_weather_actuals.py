"""
Backfill historical hourly weather ACTUALS for the active city.

This is the ERA5 reanalysis archive — ground-truth weather that
actually occurred. It's what you'll join against trip data for
analytics (Week 4) and as a training FEATURE ONLY where actuals are
legitimately available at prediction time (e.g. "weather 2 hours ago"
as a lag feature is fine; "the forecast for the prediction hour" must
come from archive_weather_forecast.py instead, or you leak the future).

Usage:
    python -m src.ingestion.fetch_weather_actuals --from 2024-01 --to 2025-12
"""

from __future__ import annotations

import argparse
import calendar
import sys
import time
from datetime import date

import httpx
import pandas as pd
from pydantic import ValidationError

from src.config import ACTIVE_SYSTEM, OPEN_METEO_ARCHIVE_URL, WEATHER_ACTUALS_DIR
from src.ingestion.schemas import OpenMeteoResponse

MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2.0
HOURLY_VARS = ["temperature_2m", "precipitation", "wind_speed_10m", "relative_humidity_2m"]


def _fetch_with_retry(client: httpx.Client, url: str, params: dict) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get(url, params=params, timeout=30.0)
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


def backfill_month(year: int, month: int) -> int:
    """Fetch one calendar month of hourly actuals. Returns row count
    written. Idempotent: overwrites that month's file, never appends."""
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])

    params = {
        "latitude": ACTIVE_SYSTEM.lat,
        "longitude": ACTIVE_SYSTEM.lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "UTC",
    }
    with httpx.Client(headers={"User-Agent": "bikeshare-platform/0.1"}) as client:
        resp = _fetch_with_retry(client, OPEN_METEO_ARCHIVE_URL, params)

    try:
        payload = OpenMeteoResponse.model_validate_json(resp.text)
    except ValidationError as exc:
        print(f"  {year}-{month:02d}: validation failed: {exc}", file=sys.stderr)
        return 0

    hourly = payload.hourly
    df = pd.DataFrame({
        "time_utc": pd.to_datetime(hourly.time, utc=True),
        "temperature_2m_c": hourly.temperature_2m,
        "precipitation_mm": hourly.precipitation,
        "wind_speed_10m_kmh": hourly.wind_speed_10m,
        "relative_humidity_2m_pct": hourly.relative_humidity_2m,
    })
    df["system_id"] = ACTIVE_SYSTEM.system_id

    out_dir = WEATHER_ACTUALS_DIR / f"year={year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"weather_actuals_{year}{month:02d}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"  {year}-{month:02d}: {len(df)} hours -> {out_path}")
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
    print(f"done — {total} hourly rows backfilled")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_ym", required=True, help="YYYY-MM")
    parser.add_argument("--to", dest="to_ym", required=True, help="YYYY-MM")
    args = parser.parse_args()
    backfill_range(args.from_ym, args.to_ym)


if __name__ == "__main__":
    main()
