# Metric Definitions

Every metric used in the dashboard and decision memo, defined precisely
enough that two people computing it independently would get the same
number. Ambiguous metric definitions are the #1 source of analytics
distrust in real companies — this file exists to prevent that here.

---

## Trip

**A trip** is one row in `fct_trip`: a single rental from `started_at`
to `ended_at`. Trips with `duration_seconds < 0` or `> 86400` (24h) are
**excluded** from all metrics below unless explicitly noted — these are
documented data quality findings (DST anomalies, lost/never-redocked
bikes — see `DECISIONS.md`), not real completed rentals for demand
analysis purposes.

## Member vs. Casual

Directly from `fct_trip.member_casual` — no derivation. Two values:
`member` (has a membership) and `casual` (single-ride or day-pass).

## Station Empty-Hours (the invented KPI)

**Definition:** for a given station and time window, the total number
of hours (fractional) during which that station had **zero bikes
available** during **demand hours** (06:00-23:00 local time — outside
this window, an empty station is far less operationally relevant, since
rebalancing crews and most riders aren't active).

**Computation:** `fct_station_status_hourly.minutes_empty` is already a
per-station-hour approximation (see that model's own comment for how
it's derived from raw ~10-min polls) — sum `minutes_empty / 60` across
all station-hours within demand hours for the window in question.

**Known limitation:** this is a poll-interval-limited approximation
(currently ~10 min), not true minute-by-minute tracking. A station that
goes empty and refills between two consecutive polls would be
undercounted. Stated explicitly rather than presented as exact.

## Weather Elasticity of Demand

**Definition:** the change in daily trip count associated with a 1°C
change in daily mean temperature, and separately with 1mm of daily
total precipitation — holding day-of-week and season roughly constant
(via a simple linear regression with day-of-week fixed effects, not a
naive raw correlation, which would be confounded by season).

**Computation:** join daily trip counts (from `fct_trip`, grouped by
`trip_date`) to daily aggregated weather (`stg_weather_hourly` grouped
by date: mean temperature, total precipitation).

## Commute Corridor Asymmetry

**Definition:** for a station pair (A, B), the imbalance between
morning (06:00-10:00) trips A→B vs. afternoon (16:00-20:00) trips B→A.
A corridor with morning A→B ≫ afternoon B→A implies bikes accumulate at
B and need active rebalancing back to A.

**Computation:** count trips grouped by (start_station, end_station,
time-of-day bucket), compare the two directional counts for each pair.

## Peak Demand vs. Installed Capacity

**Definition:** for each station, the number of distinct hours where
the observed maximum concurrent demand (approximated by trip
starts+ends within that hour) exceeded the station's installed
capacity (from `dim_station.capacity`, current/live value — see the
caveat below).

**Known limitation:** joins `fct_trip` (via `dim_trip_station`, the
legacy numeric ID scheme) to `dim_station`'s capacity (the live UUID
scheme) by station **name**, not ID — because no reliable ID crosswalk
exists between the two (see `DECISIONS.md`). This is a real, accepted
limitation: a renamed station would silently fail to join. Coverage
rate of this join is reported alongside any result using it, not
hidden.

---

## General exclusions applied throughout

- Trips with a null `start_station_id` or `end_station_id` (~15-17% of
  all trips — see `DECISIONS.md`) are excluded from any *station-level*
  metric, but **included** in any metric that doesn't require a
  station (e.g. system-wide daily ride counts, member/casual split).
- The date range for all metrics is **2024-01-01 through 2025-12-31**
  unless a metric explicitly states otherwise.
