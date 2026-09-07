-- Answers: "Which commute corridors are directionally asymmetric
-- (implying trucks must rebalance them)?" A corridor with heavy
-- morning A->B and light afternoon B->A implies bikes pile up at B.

with morning_trips as (

    select
        start_station_id as station_a,
        end_station_id as station_b,
        count(*) as morning_a_to_b
    from {{ ref('fct_trip') }}
    where trip_hour between 6 and 9
      and start_station_id is not null
      and end_station_id is not null
    group by start_station_id, end_station_id

),

evening_trips as (

    select
        end_station_id as station_a,
        start_station_id as station_b,
        count(*) as evening_b_to_a
    from {{ ref('fct_trip') }}
    where trip_hour between 16 and 19
      and start_station_id is not null
      and end_station_id is not null
    group by end_station_id, start_station_id

),

joined as (

    select
        coalesce(m.station_a, e.station_a) as station_a,
        coalesce(m.station_b, e.station_b) as station_b,
        coalesce(m.morning_a_to_b, 0) as morning_a_to_b,
        coalesce(e.evening_b_to_a, 0) as evening_b_to_a
    from morning_trips m
    full outer join evening_trips e
        on m.station_a = e.station_a and m.station_b = e.station_b

)

select
    j.station_a,
    ta.station_name as station_a_name,
    j.station_b,
    tb.station_name as station_b_name,
    j.morning_a_to_b,
    j.evening_b_to_a,
    j.morning_a_to_b - j.evening_b_to_a as asymmetry,
    -- Only meaningful for corridors with real volume both ways —
    -- avoids a 1-trip corridor looking "100% asymmetric"
    (j.morning_a_to_b + j.evening_b_to_a) >= 20 as has_meaningful_volume

from joined j
left join {{ ref('dim_trip_station') }} ta on j.station_a = ta.station_id
left join {{ ref('dim_trip_station') }} tb on j.station_b = tb.station_id
