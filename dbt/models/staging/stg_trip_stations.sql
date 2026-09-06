-- Real GBFS feeds don't reliably bridge modern UUID station_ids back
-- to the legacy numeric codes used in ALL historical trip data (found
-- in production: Capital Bikeshare's "external_id" field just
-- duplicates station_id, providing no real crosswalk). Rather than
-- fight that, this derives station reference data directly from trip
-- data itself — trips already self-report station name and exact
-- coordinates on both the start and end side, in the SAME ID scheme
-- fct_trip uses, so this join works by construction.
--
-- This does NOT replace dim_station (the SCD2 snapshot from the live
-- feed) — that's still the right source for real-time station state
-- (current capacity, current status). This is specifically for
-- enriching historical trip facts.

with start_side as (

    select
        start_station_id as station_id,
        start_station_name as station_name,
        start_lat as lat,
        start_lng as lng,
        started_at as observed_at
    from {{ ref('stg_trips') }}
    where start_station_id is not null

),

end_side as (

    select
        end_station_id as station_id,
        end_station_name as station_name,
        end_lat as lat,
        end_lng as lng,
        ended_at as observed_at
    from {{ ref('stg_trips') }}
    where end_station_id is not null

),

combined as (

    select * from start_side
    union all
    select * from end_side

),

-- Keep the most recently observed name/coordinates per station, in
-- case of a rename or a small coordinate correction across the two
-- years of trip data — same "most recent wins" logic as stg_stations.
latest_per_station as (

    select *
    from combined
    qualify row_number() over (
        partition by station_id
        order by observed_at desc
    ) = 1

)

select
    station_id,
    station_name,
    lat,
    lng
from latest_per_station
