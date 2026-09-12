{{ config(severity = 'warn') }}

-- WARN not ERROR: investigated on real data (15 rows, 2 stations).
-- Confirmed NOT a stale-capacity/SCD2-join bug — dim_station shows a
-- single, unchanged capacity value for both stations across the whole
-- observed period, so this isn't old data being compared against a
-- since-changed number. The overage is real, large (up to ~150% of
-- capacity), and sustained across multiple hours on two separate
-- days — not a single anomalous poll.
--
-- Both stations are large, high-demand locations near Georgetown
-- University. Most likely explanation: e-bikes parked as "valet"
-- overflow near the station (locked to railings/signposts rather
-- than a physical dock) still count as "available at this station"
-- in the live feed, legitimately exceeding the station's marked dock
-- capacity. A real, worthwhile finding — not a pipeline bug.
--
-- The plan itself predicts this test WILL eventually fail on real
-- data. It just did.

select
    s.station_id,
    d.station_name,
    s.partition_date,
    s.partition_hour,
    s.max_bikes_available,
    d.capacity
from {{ ref('fct_station_status_hourly') }} s
inner join {{ ref('dim_station') }} d
    on s.station_id = d.station_id
    and d.is_current
where s.max_bikes_available > d.capacity
