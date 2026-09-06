-- A trip ending before it started is impossible — this test should
-- return ZERO rows. If it doesn't, that's a real data quality bug
-- worth investigating (bad source data, or a normalization mistake).

select
    trip_id,
    started_at,
    ended_at
from {{ ref('fct_trip') }}
where ended_at < started_at
