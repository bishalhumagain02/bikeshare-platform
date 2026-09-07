-- Answers: "Which stations have the worst empty-hours, and is the
-- cause demand or capacity?" and provides the invented KPI (see
-- metrics.md). Clean join: fct_station_status_hourly and dim_station
-- both use the live GBFS UUID scheme — no crosswalk problem here,
-- unlike the trip-data joins elsewhere (see mart_capacity_exceedance.sql).

with hourly as (

    select * from {{ ref('fct_station_status_hourly') }}

),

-- Demand hours only, per metrics.md's empty-hours definition: 06:00-23:00.
demand_hours_only as (

    select *
    from hourly
    where partition_hour::int between 6 and 22

),

station_totals as (

    select
        station_id,
        sum(minutes_empty) / 60.0 as empty_hours,
        sum(minutes_full) / 60.0 as full_hours,
        count(*) as station_hours_observed

    from demand_hours_only
    group by station_id

)

select
    t.station_id,
    d.station_name,
    d.capacity,
    t.empty_hours,
    t.full_hours,
    t.station_hours_observed,
    -- Flags whether the empty-hours problem looks demand-driven (low
    -- capacity relative to system norms) or something else — a
    -- starting point for the "is the cause demand or capacity" write-up,
    -- not a definitive answer on its own.
    case
        when d.capacity is null then null
        when d.capacity <= 15 then 'low_capacity'
        else 'investigate_demand'
    end as likely_cause_flag

from station_totals t
left join {{ ref('dim_station') }} d
    on t.station_id = d.station_id
    and d.is_current
