"""
Archive tomorrow's weather forecast, every day, starting today.

Why this exists (from the plan): the model in Week 5 predicts bike
availability using WEATHER FORECASTS, because that's all it will have
at inference time. If we only ever save weather ACTUALS, the model
would train on information it can't have when it actually runs — a
leakage bug called "look-ahead bias." Open-Meteo's live forecast API
only shows the *current* forecast; it doesn't let you ask "what did
the forecast look like on Sept 3rd for Sept 4th?" after the fact. So
that history has to be captured going forward, one issue-timestamp at
a time, or it's gone forever.

Run this once a day (cron, Dagster schedule, Task Scheduler — anything).
Each run is cheap: one HTTP GET, no auth, free tier.

Usage:
    python -m src.ingestion.archive_weather_forecast
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
from pydantic import ValidationError

from src.config import (
    ACTIVE_SYSTEM,
    FORECAST_HOURS_TO_ARCHIVE,
    OPEN_METEO_FORECAST_URL,
    WEATHER_FORECASTS_DIR,
)
from src.ingestion.schemas import OpenMeteoResponse

MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2.0

HOURLY_VARS = ["temperature_2m", "precipitation", "wind_speed_10m", "relative_humidity_2m"]


def _fetch_with_retry(client: httpx.Client, url: str, params: dict) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get(url, params=params, timeout=15.0)
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


def fetch_raw_forecast_text() -> str:
    """Network call, isolated so tests can bypass it with a fixture."""
    params = {
        "latitude": ACTIVE_SYSTEM.lat,
        "longitude": ACTIVE_SYSTEM.lon,
        "hourly": ",".join(HOURLY_VARS),
        "forecast_days": 2,  # covers the next 48h we care about
        "timezone": "UTC",
    }
    with httpx.Client(headers={"User-Agent": "bikeshare-platform/0.1"}) as client:
        resp = _fetch_with_retry(client, OPEN_METEO_FORECAST_URL, params)
        return resp.text


def parse_and_archive(raw_text: str, issued_at: datetime | None = None) -> Path | None:
    """Validate an Open-Meteo forecast response and archive it, tagged
    with the moment it was issued. This timestamp is the whole point:
    it's what lets a future training script join 'the forecast that
    existed at prediction time' instead of 'the forecast we know now
    was correct' (that second one is the leakage bug)."""
    issued_at = issued_at or datetime.now(UTC)

    try:
        payload = OpenMeteoResponse.model_validate_json(raw_text)
    except ValidationError as exc:
        print(f"  forecast payload failed validation: {exc}", file=sys.stderr)
        return None

    hourly = payload.hourly
    n = len(hourly.time)
    df = pd.DataFrame({
        "forecast_target_time": hourly.time,
        "temperature_2m_c": (hourly.temperature_2m or [None] * n),
        "precipitation_mm": (hourly.precipitation or [None] * n),
        "wind_speed_10m_kmh": (hourly.wind_speed_10m or [None] * n),
        "relative_humidity_2m_pct": (hourly.relative_humidity_2m or [None] * n),
    })
    # Keep only the next FORECAST_HOURS_TO_ARCHIVE hours from issue time —
    # forecast_days=2 over-fetches slightly (up to 48h from midnight, not
    # from "now"), so trim to what we actually need.
    df["forecast_target_time"] = pd.to_datetime(df["forecast_target_time"], utc=True)
    cutoff = issued_at + pd.Timedelta(hours=FORECAST_HOURS_TO_ARCHIVE)
    df = df[(df["forecast_target_time"] >= issued_at.replace(minute=0, second=0, microsecond=0))
            & (df["forecast_target_time"] <= cutoff)].reset_index(drop=True)

    df["issued_at"] = issued_at
    df["system_id"] = ACTIVE_SYSTEM.system_id
    df["latitude"] = payload.latitude
    df["longitude"] = payload.longitude

    dt_str = issued_at.strftime("%Y-%m-%d")
    out_dir = WEATHER_FORECASTS_DIR / f"issued_dt={dt_str}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"forecast_issued_{issued_at.strftime('%Y%m%dT%H%M%S')}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"  archived {len(df)} forecast hours (issued {issued_at.isoformat()}) -> {out_path}")
    return out_path


def archive_once() -> Path | None:
    raw_text = fetch_raw_forecast_text()
    return parse_and_archive(raw_text)


if __name__ == "__main__":
    print(f"archiving 48h forecast for {ACTIVE_SYSTEM.display_name} "
          f"({ACTIVE_SYSTEM.lat}, {ACTIVE_SYSTEM.lon})")
    archive_once()
