-- Answers: "How do member and casual rider patterns diverge by hour,
-- day, and geography?" One row per (hour of day, day of week,
-- member/casual, start station).

select
    trip_hour,
    extract(dow from trip_date) as day_of_week,
    member_casual,
    start_station_id,
    start_station_name,
    count(*) as trip_count,
    avg(duration_seconds) as avg_duration_seconds

from {{ ref('fct_trip') }}
where start_station_id is not null  -- see metrics.md: excluded from station-level metrics
group by trip_hour, extract(dow from trip_date), member_casual, start_station_id, start_station_name
