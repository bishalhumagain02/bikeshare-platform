"""
Pydantic models for GBFS v1.1/v2.x feeds.

Only the fields we actually use are modeled strictly; everything else is
allowed to pass through via `model_config = {"extra": "allow"}` so a feed
adding new optional fields doesn't break ingestion.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator


class StationStatus(BaseModel):
    model_config = {"extra": "allow"}

    station_id: str
    num_bikes_available: int
    num_docks_available: int
    is_installed: bool = True
    is_renting: bool = True
    is_returning: bool = True
    last_reported: int  # unix timestamp, per GBFS spec

    @field_validator("num_bikes_available", "num_docks_available")
    @classmethod
    def non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("counts must be non-negative")
        return v

    @property
    def last_reported_dt(self) -> datetime:
        return datetime.fromtimestamp(self.last_reported, tz=UTC)


class StationStatusFeed(BaseModel):
    last_updated: int
    ttl: int
    data: dict

    @property
    def stations(self) -> list[StationStatus]:
        raw = self.data.get("stations", [])
        return [StationStatus.model_validate(s) for s in raw]


class RentalUris(BaseModel):
    model_config = {"extra": "allow"}
    android: str | None = None
    ios: str | None = None


class StationInformation(BaseModel):
    model_config = {"extra": "allow"}

    station_id: str
    name: str
    lat: float
    lon: float
    capacity: int | None = Field(default=None, ge=0)
    region_id: str | None = None
    station_type: str | None = None


class StationInformationFeed(BaseModel):
    last_updated: int
    ttl: int
    data: dict

    @property
    def stations(self) -> list[StationInformation]:
        raw = self.data.get("stations", [])
        return [StationInformation.model_validate(s) for s in raw]


class GBFSDiscoveryFeed(BaseModel):
    """Top-level gbfs.json — just enough to resolve child feed URLs."""

    model_config = {"extra": "allow"}

    data: dict

    def feed_url(self, name: str, language: str = "en") -> str | None:
        lang_block = self.data.get(language) or next(iter(self.data.values()), {})
        for feed in lang_block.get("feeds", []):
            if feed.get("name") == name:
                return feed.get("url")
        return None
