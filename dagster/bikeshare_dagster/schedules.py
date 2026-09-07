"""
Only ONE schedule actually runs automatically: the dbt build.

Ingestion (station_status, station_information, weather_forecast) is
NOT scheduled here on purpose — GitHub Actions + cron-job.org already
owns continuous collection in production (see docs/cloud-setup.md),
solving the real timezone/uptime problem this project had. Scheduling
the same polls again here would just fetch duplicate data.

The ingestion assets stay in the graph and ARE materializable on
demand (manually, from the UI, or ad hoc) — useful for local testing
and for showing the full pipeline's lineage — they're just not on an
automatic timer competing with the thing that's already doing this
job in production.
"""

from __future__ import annotations

import dagster as dg
from bikeshare_dagster.dbt_assets import bikeshare_dbt_assets
from bikeshare_dagster.hooks import notify_on_failure

dbt_build_job = dg.define_asset_job(
    name="dbt_build_job",
    selection=[bikeshare_dbt_assets],
    hooks={notify_on_failure},
)

# Assumes GitHub Actions' daily ingestion jobs (station_information,
# weather_forecast_archive) have already landed by this time — adjust
# if you change those workflows' schedule in docs/cloud-setup.md.
dbt_build_schedule = dg.ScheduleDefinition(
    job=dbt_build_job,
    cron_schedule="30 6 * * *",  # 06:30 UTC daily
)
