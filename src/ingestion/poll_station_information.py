"""
Fetch GBFS station_information (name, capacity, lat/lon, region) — a
SLOWLY-CHANGING dimension, unlike station_status's high-frequency bike
counts. This is what feeds the Week 2 dbt snapshot (SCD Type 2):
stations occasionally get renamed, resized, or relocated, and the
snapshot needs periodic captures to detect those changes over time.

Cadence: once a day is plenty — this data rarely changes hour to hour.
Wire this into the same GitHub Actions + B2 pattern as
archive_weather_forecast.py if you want it running in the cloud too.

Usage:
    python -m src.ingestion.poll_station_information
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
from pydantic import ValidationError

from src.config import ACTIVE_SYSTEM, DEADLETTER_DIR, RAW_DIR, STATION_INFO_DIR
from src.ingestion.schemas import GBFSDiscoveryFeed, StationInformationFeed
from src.storage import upload_if_configured

MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2.0


def _fetch_with_retry(client: httpx.Client, url: str) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get(url, timeout=15.0)
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


def _write_deadletter(raw_text: str, reason: str) -> Path:
    DEADLETTER_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = DEADLETTER_DIR / f"station_info_{stamp}_{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps({"reason": reason, "raw": raw_text[:5000]}, indent=2))
    print(f"  routed to dead-letter: {path}", file=sys.stderr)
    return path


def _fetch_raw_info_text() -> str:
    """Network call, isolated so tests can bypass it with a fixture."""
    with httpx.Client(headers={"User-Agent": "bikeshare-platform/0.1"}) as client:
        discovery_resp = _fetch_with_retry(client, ACTIVE_SYSTEM.gbfs_discovery_url)
        discovery = GBFSDiscoveryFeed.model_validate(discovery_resp.json())
        info_url = discovery.feed_url("station_information")
        if info_url is None:
            _write_deadletter(discovery_resp.text, "no station_information feed in discovery doc")
            return ""
        info_resp = _fetch_with_retry(client, info_url)
        return info_resp.text


def parse_and_land(raw_text: str, fetched_at: datetime | None = None) -> Path | None:
    """Validate a raw station_information JSON string and write one
    partition. Split out from poll_once() so it's testable with a
    fixture — no network required."""
    fetched_at = fetched_at or datetime.now(UTC)

    if not raw_text.lstrip().startswith("{"):
        _write_deadletter(raw_text, "response is not JSON (likely an HTML error page)")
        return None

    try:
        feed = StationInformationFeed.model_validate(json.loads(raw_text))
        stations = feed.stations
    except (json.JSONDecodeError, ValidationError) as exc:
        _write_deadletter(raw_text, f"validation error: {exc}")
        return None

    if not stations:
        _write_deadletter(raw_text, "parsed feed but station list was empty")
        return None

    df = pd.DataFrame([s.model_dump() for s in stations])
    df["fetched_at"] = fetched_at
    df["system_id"] = ACTIVE_SYSTEM.system_id

    dt_str = fetched_at.strftime("%Y-%m-%d")
    out_dir = STATION_INFO_DIR / f"dt={dt_str}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"station_information_{fetched_at.strftime('%Y%m%dT%H%M%S')}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"  wrote {len(df)} stations -> {out_path}")

    try:
        remote_key = str(out_path.relative_to(RAW_DIR)).replace("\\", "/")
    except ValueError:
        remote_key = f"station_information/{out_path.name}"
    upload_if_configured(out_path, remote_key)

    return out_path


def poll_once() -> Path | None:
    raw_text = _fetch_raw_info_text()
    if not raw_text:
        return None
    return parse_and_land(raw_text)


if __name__ == "__main__":
    print(f"polling {ACTIVE_SYSTEM.display_name} station_information "
          f"({ACTIVE_SYSTEM.gbfs_discovery_url})")
    poll_once()
