"""
Points Dagster at the existing dbt project — the SAME dbt project used
standalone via `cd dbt && dbt build`, not a separate copy.
"""

from __future__ import annotations

from pathlib import Path

from dagster_dbt import DbtCliResource, DbtProject

DBT_PROJECT_DIR = Path(__file__).resolve().parents[2] / "dbt"

dbt_project = DbtProject(
    project_dir=DBT_PROJECT_DIR,
    profiles_dir=DBT_PROJECT_DIR,  # profiles.yml lives inside dbt/, not ~/.dbt/
)

# Must happen here, at import time, before anything (e.g. dbt_assets.py)
# tries to read dbt_project.manifest_path — generates/refreshes the
# manifest so the @dbt_assets decorator has something to load.
dbt_project.prepare_if_dev()

dbt_resource = DbtCliResource(project_dir=dbt_project)
