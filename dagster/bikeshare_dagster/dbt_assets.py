"""
Pulls the ENTIRE dbt project (staging models, the SCD2 snapshot, every
mart, every test) into Dagster's asset graph as one coherent set of
assets — this is what the plan means by "the dagster-dbt integration
is native" and "the lineage graph is one coherent picture."

raw_data_path defaults to the project's real raw/ folder. Override with
--vars if you need to point at a different location (e.g. a synthetic
test fixture directory).
"""

from __future__ import annotations

from dagster_dbt import DbtCliResource, dbt_assets

from bikeshare_dagster.dbt_project import dbt_project


@dbt_assets(manifest=dbt_project.manifest_path)
def bikeshare_dbt_assets(context, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()
