-- Answers: "Where does actual peak demand exceed installed dock
-- capacity?" Uses a NAME-based join between trip-derived stations and
-- live capacity, because no reliable ID crosswalk exists between them
-- (see DECISIONS.md — the same root cause as dim_trip_station's
-- existence). This is an accepted, real limitation: a renamed station
-- silently fails to match. join_coverage_pct below reports exactly how
-- much of the data this affects, rather than hiding it.

with hourly_demand as (

    select
        start_station_id,
        trip_date,
        trip_hour,
        count(*) as hourly_departures

    from {{ ref('fct_trip') }}
    where start_station_id is not null
    group by start_station_id, trip_date, trip_hour

),

trip_stations as (

    select station_id, station_name from {{ ref('dim_trip_station') }}

),

live_capacity as (

    select station_name, capacity
    from {{ ref('dim_station') }}
    where is_current

),

-- Name-based join, deduplicated: a station name could in principle
-- match more than one live station_id if renamed/relocated — keep one
-- arbitrary match per name rather than fan out hourly_demand rows.
name_matched_capacity as (

    select
        station_name,
        capacity
    from live_capacity
    qualify row_number() over (partition by station_name) = 1

),

joined as (

    select
        h.start_station_id,
        ts.station_name,
        h.trip_date,
        h.trip_hour,
        h.hourly_departures,
        c.capacity,
        c.capacity is not null as matched_to_live_capacity

    from hourly_demand h
    left join trip_stations ts on h.start_station_id = ts.station_id
    left join name_matched_capacity c on ts.station_name = c.station_name

)

select
    start_station_id,
    station_name,
    trip_date,
    trip_hour,
    hourly_departures,
    capacity,
    hourly_departures > capacity as exceeds_capacity,
    -- Reported per-row so a dashboard/memo can compute overall coverage
    -- (what % of demand rows actually got matched to a live capacity
    -- value) rather than that number being invisible.
    matched_to_live_capacity

from joined
