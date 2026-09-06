-- The plan calls this test out specifically: it WILL fail on real
-- data, and investigating why is a legitimate finding, not a bug in
-- the test. Likely causes worth checking if/when this returns rows:
-- capacity changed (station resized) between the poll and the
-- snapshot's current capacity value, e-bikes/scooters parked outside
-- formal docks counting toward "available", or a temporary
-- overcapacity event during rebalancing.

select
    s.station_id,
    s.partition_date,
    s.partition_hour,
    s.max_bikes_available,
    d.capacity
from {{ ref('fct_station_status_hourly') }} s
inner join {{ ref('dim_station') }} d
    on s.station_id = d.station_id
    and d.is_current
where s.max_bikes_available > d.capacity
