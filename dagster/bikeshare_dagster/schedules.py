"""
Schedules matching the real-world cadence each source needs:
- station_status: ~10 min (matches the cloud collection cadence)
- station_information, weather_forecast_archive, dbt build: daily

In production, the actual continuous collection runs via GitHub Actions
+ cron-job.org (see docs/cloud-setup.md) — these Dagster schedules exist
to demonstrate the orchestration layer locally/in a Dagster deployment,
using the exact same underlying ingestion code either way.
"""

from __future__ import annotations

import dagster as dg
from bikeshare_dagster.dbt_assets import bikeshare_dbt_assets
from bikeshare_dagster.hooks import notify_on_failure
from bikeshare_dagster.ingestion_assets import (
    station_information_poll,
    station_status_poll,
    weather_forecast_archive,
)

station_status_job = dg.define_asset_job(
    name="station_status_job",
    selection=[station_status_poll],
    hooks={notify_on_failure},
)

daily_ingestion_job = dg.define_asset_job(
    name="daily_ingestion_job",
    selection=[station_information_poll, weather_forecast_archive],
    hooks={notify_on_failure},
)

dbt_build_job = dg.define_asset_job(
    name="dbt_build_job",
    selection=[bikeshare_dbt_assets],
    hooks={notify_on_failure},
)

station_status_schedule = dg.ScheduleDefinition(
    job=station_status_job,
    cron_schedule="*/10 * * * *",
)

daily_ingestion_schedule = dg.ScheduleDefinition(
    job=daily_ingestion_job,
    cron_schedule="0 6 * * *",  # 06:00 UTC daily
)

# Runs after the daily ingestion — station info + weather need to land
# before the warehouse rebuilds on top of them.
dbt_build_schedule = dg.ScheduleDefinition(
    job=dbt_build_job,
    cron_schedule="30 6 * * *",  # 30 min after daily_ingestion_schedule
)
