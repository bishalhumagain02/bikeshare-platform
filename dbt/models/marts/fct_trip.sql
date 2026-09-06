{{
    config(
        materialized='incremental',
        unique_key='trip_id'
    )
}}

with trips as (

    select * from {{ ref('stg_trips') }}

    {% if is_incremental() %}
    -- Late-arriving records lookback: re-process the last 3 days of
    -- already-loaded data on every incremental run, in case a trip
    -- landed in the source after its month was first backfilled.
    where started_at >= (select coalesce(max(started_at), '1900-01-01'::timestamp) - interval '3 days' from {{ this }})
    {% endif %}

)

select
    trip_id,
    system_id,
    schema_era,
    rideable_type,
    started_at,
    ended_at,
    duration_seconds,
    start_station_id,
    start_station_name,
    end_station_id,
    end_station_name,
    start_lat,
    start_lng,
    end_lat,
    end_lng,
    member_casual,
    date_trunc('day', started_at) as trip_date,
    extract(hour from started_at) as trip_hour

from trips
