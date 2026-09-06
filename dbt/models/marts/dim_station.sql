with snapshot as (

    select * from {{ ref('stations_snapshot') }}

)

select
    station_id,
    system_id,
    station_name,
    lat,
    lon,
    capacity,
    region_id,
    station_type,
    legacy_id,
    dbt_valid_from as valid_from,
    coalesce(dbt_valid_to, timestamp '9999-12-31') as valid_to,
    dbt_valid_to is null as is_current

from snapshot
