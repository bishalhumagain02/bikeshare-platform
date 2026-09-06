-- The station reference table that actually matches fct_trip's ID
-- scheme, by construction. See stg_trip_stations.sql for why this
-- exists separately from dim_station (the live-feed SCD2 snapshot).

select
    station_id,
    station_name,
    lat,
    lng
from {{ ref('stg_trip_stations') }}
