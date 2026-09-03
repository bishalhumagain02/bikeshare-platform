"""
Central config for the bike-share platform.

Swapping cities should mean changing this file only. If you ever find
yourself hardcoding a city-specific field name or URL somewhere else in
the codebase, that's a design smell — bring it back here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CitySystem:
    """One GBFS-publishing bike-share system."""

    system_id: str
    display_name: str
    gbfs_discovery_url: str
    # Historical trip data (monthly CSVs, zipped, S3-hosted).
    trip_history_base_url: str
    trip_history_pattern: str  # strftime-style pattern for filenames
    timezone: str
    # Rough lat/lon bounding box, used for the weather API calls.
    lat: float
    lon: float


CAPITAL_BIKESHARE = CitySystem(
    system_id="capital_bikeshare",
    display_name="Capital Bikeshare (Washington, DC metro)",
    gbfs_discovery_url="https://gbfs.capitalbikeshare.com/gbfs/gbfs.json",
    trip_history_base_url="https://s3.amazonaws.com/capitalbikeshare-data/",
    # e.g. 202401-capitalbikeshare-tripdata.zip
    trip_history_pattern="{year}{month:02d}-capitalbikeshare-tripdata.zip",
    timezone="America/New_York",
    lat=38.9072,
    lon=-77.0369,
)

# Active system for this run. Change this one line to swap cities.
ACTIVE_SYSTEM = CAPITAL_BIKESHARE

# --- Paths -------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "raw"
STATION_STATUS_DIR = RAW_DIR / "station_status"
STATION_INFO_DIR = RAW_DIR / "station_information"
TRIPS_DIR = RAW_DIR / "trips"
WEATHER_ACTUALS_DIR = RAW_DIR / "weather" / "actuals"
WEATHER_FORECASTS_DIR = RAW_DIR / "weather" / "forecasts"
DEADLETTER_DIR = RAW_DIR / "_deadletter"

# --- Polling ------------------------------------------------------------

STATION_STATUS_POLL_SECONDS = 300  # 5 min, matches the plan's freshness bar
FRESHNESS_WARN_SECONDS = 30 * 60
FRESHNESS_ERROR_SECONDS = 2 * 60 * 60

# --- Open-Meteo -----------------------------------------------------------

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_HOURS_TO_ARCHIVE = 48  # store next 48h of forecast, every day
