"""
Poll GBFS station_status for the active city and land it as Parquet.

Usage:
    python -m src.ingestion.poll_station_status          # one-shot poll
    python -m src.ingestion.poll_station_status --loop    # poll every 5 min

Idempotency contract: re-running this for the same UTC hour overwrites
that hour's partition file rather than appending, so replays never
duplicate rows. See tests/test_idempotency.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
from pydantic import ValidationError

from src.config import (
    ACTIVE_SYSTEM,
    DEADLETTER_DIR,
    STATION_STATUS_DIR,
    STATION_STATUS_POLL_SECONDS,
)
from src.ingestion.schemas import GBFSDiscoveryFeed, StationStatusFeed

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
    path = DEADLETTER_DIR / f"station_status_{stamp}_{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps({"reason": reason, "raw": raw_text[:5000]}, indent=2))
    print(f"  routed to dead-letter: {path}", file=sys.stderr)
    return path


def _fetch_raw_status_text() -> str:
    """Network call, isolated so tests can monkeypatch it without a live feed."""
    with httpx.Client(headers={"User-Agent": "bikeshare-platform/0.1"}) as client:
        discovery_resp = _fetch_with_retry(client, ACTIVE_SYSTEM.gbfs_discovery_url)
        discovery = GBFSDiscoveryFeed.model_validate(discovery_resp.json())
        status_url = discovery.feed_url("station_status")
        if status_url is None:
            _write_deadletter(discovery_resp.text, "no station_status feed in discovery doc")
            return ""
        status_resp = _fetch_with_retry(client, status_url)
        return status_resp.text


def parse_and_land(raw_text: str, fetched_at: datetime | None = None) -> Path | None:
    """Validate a raw station_status JSON string and write one partition.

    Split out from poll_once() so it's testable with a fixture — no
    network required. Returns the output path, or None if dead-lettered.
    """
    fetched_at = fetched_at or datetime.now(UTC)

    # Feeds return HTML error pages with a 200 status more often than
    # you'd think — catch that before Pydantic does.
    stripped = raw_text.lstrip()
    if not stripped.startswith("{"):
        _write_deadletter(raw_text, "response is not JSON (likely an HTML error page)")
        return None

    try:
        payload = json.loads(raw_text)
        feed = StationStatusFeed.model_validate(payload)
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
    hr_str = fetched_at.strftime("%H")
    out_dir = STATION_STATUS_DIR / f"dt={dt_str}" / f"hr={hr_str}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # One file per poll, named by minute — safe to re-run without
    # duplicating rows within the same minute, and safe to delete +
    # re-poll a whole hour partition for a backfill demo.
    out_path = out_dir / f"station_status_{fetched_at.strftime('%Y%m%dT%H%M%S')}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"  wrote {len(df)} stations -> {out_path}")
    return out_path


def poll_once() -> Path | None:
    """Fetch station_status once, validate, write one partition. Returns
    the output path, or None if the payload was dead-lettered."""
    raw_text = _fetch_raw_status_text()
    if not raw_text:
        return None
    return parse_and_land(raw_text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="poll continuously")
    args = parser.parse_args()

    print(f"polling {ACTIVE_SYSTEM.display_name} station_status "
          f"({ACTIVE_SYSTEM.gbfs_discovery_url})")

    if not args.loop:
        poll_once()
        return

    while True:
        try:
            poll_once()
        except Exception as exc:  # noqa: BLE001 — top-level loop guard
            print(f"poll failed after retries: {exc}", file=sys.stderr)
        time.sleep(STATION_STATUS_POLL_SECONDS)


if __name__ == "__main__":
    main()
