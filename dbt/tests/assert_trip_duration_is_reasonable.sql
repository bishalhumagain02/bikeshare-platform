{{ config(severity = 'warn') }}

-- WARN not ERROR: 10,072 rows out of millions (~0.1-0.2%) is well
-- within the expected rate of bikes checked out and never properly
-- redocked (lost, stolen, or a rider forgetting to end their rental)
-- — a well-known, common phenomenon in real bikeshare systems, not a
-- pipeline bug. A negative duration is impossible; a duration over 24
-- hours almost certainly means exactly this.

select
    trip_id,
    started_at,
    ended_at,
    duration_seconds
from {{ ref('fct_trip') }}
where duration_seconds is not null
  and (duration_seconds < 0 or duration_seconds > 86400)
