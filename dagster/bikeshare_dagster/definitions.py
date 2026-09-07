from __future__ import annotations

import dagster as dg
from bikeshare_dagster.dbt_assets import bikeshare_dbt_assets
from bikeshare_dagster.dbt_project import dbt_resource
from bikeshare_dagster.ingestion_assets import (
    station_information_poll,
    station_status_poll,
    weather_forecast_archive,
)
from bikeshare_dagster.schedules import (
    daily_ingestion_schedule,
    dbt_build_schedule,
    station_status_schedule,
)

defs = dg.Definitions(
    assets=[
        station_status_poll,
        station_information_poll,
        weather_forecast_archive,
        bikeshare_dbt_assets,
    ],
    schedules=[
        station_status_schedule,
        daily_ingestion_schedule,
        dbt_build_schedule,
    ],
    resources={
        "dbt": dbt_resource,
    },
)
