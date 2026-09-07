"""
Dagster assets for the recurring ingestion scripts.

These wrap the SAME functions used by the standalone
`python -m src.ingestion.*` scripts and by the GitHub Actions cloud
workflows — there's exactly one implementation of "how to poll
station_status", not a Dagster-specific copy that could drift from the
one actually running in production.
"""

from __future__ import annotations

import dagster as dg
from src.ingestion import archive_weather_forecast, poll_station_information, poll_station_status


@dg.asset(
    group_name="ingestion",
    description="Live station bike/dock counts — polled ~every 10 min in production "
    "(via GitHub Actions + cron-job.org). This asset lets the same logic run under "
    "Dagster's own scheduler for local dev/demo purposes.",
)
def station_status_poll(context) -> dg.MaterializeResult:
    out_path = poll_station_status.poll_once()
    if out_path is None:
        context.log.warning("Poll returned no data — check dead-letter directory")
        return dg.MaterializeResult(metadata={"status": "no_data"})
    return dg.MaterializeResult(
        metadata={
            "output_path": dg.MetadataValue.path(str(out_path)),
        }
    )


@dg.asset(
    group_name="ingestion",
    description="Station metadata (name/capacity/lat-lon) — the slowly-changing "
    "dimension the SCD2 snapshot needs. Polled daily.",
)
def station_information_poll(context) -> dg.MaterializeResult:
    out_path = poll_station_information.poll_once()
    if out_path is None:
        context.log.warning("Poll returned no data — check dead-letter directory")
        return dg.MaterializeResult(metadata={"status": "no_data"})
    return dg.MaterializeResult(
        metadata={"output_path": dg.MetadataValue.path(str(out_path))}
    )


@dg.asset(
    group_name="ingestion",
    description="Next-48h weather forecast, archived with its issue timestamp. "
    "Time-sensitive: a missed day cannot be recreated retroactively.",
)
def weather_forecast_archive(context) -> dg.MaterializeResult:
    out_path = archive_weather_forecast.archive_once()
    if out_path is None:
        context.log.warning("Archive returned no data — check upstream API/response")
        return dg.MaterializeResult(metadata={"status": "no_data"})
    return dg.MaterializeResult(
        metadata={"output_path": dg.MetadataValue.path(str(out_path))}
    )
