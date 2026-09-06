-- A negative duration is impossible; a duration over 24 hours almost
-- certainly means a bike that was never properly docked, not a real
-- ride. WARN-worthy, not necessarily a hard error — flagged here as a
-- singular test (rather than dbt_utils.accepted_range) so this test
-- has zero external package dependencies.

select
    trip_id,
    started_at,
    ended_at,
    duration_seconds
from {{ ref('fct_trip') }}
where duration_seconds is not null
  and (duration_seconds < 0 or duration_seconds > 86400)
