{{ config(severity = 'warn') }}

-- A trip ending before it started is impossible in real elapsed time,
-- but WARN not ERROR: investigated on the real dataset (371 rows out
-- of millions) and this concentrates around specific dates consistent
-- with the US fall-back Daylight Saving Time transition — source
-- timestamps are naive local (America/New_York) wall-clock strings,
-- and during the one "repeated hour" each November, wall-clock time
-- briefly runs backwards. This pipeline currently treats naive
-- timestamps as literal UTC (no DST-aware localization), so trips
-- spanning that hour can show ended_at < started_at. A real, bounded,
-- well-understood phenomenon — not a bug worth blocking builds over,
-- but a genuine README/interview finding.

select
    trip_id,
    started_at,
    ended_at
from {{ ref('fct_trip') }}
where ended_at < started_at
