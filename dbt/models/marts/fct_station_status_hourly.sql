with status as (

    select * from {{ ref('stg_station_status') }}

),

hourly as (

    select
        station_id,
        system_id,
        partition_date,
        partition_hour,
        count(*) as num_polls_in_hour,
        avg(num_bikes_available) as avg_bikes_available,
        avg(num_docks_available) as avg_docks_available,
        min(num_bikes_available) as min_bikes_available,
        max(num_bikes_available) as max_bikes_available,
        -- Each poll represents roughly (60 / polls_per_hour) minutes.
        -- Counting polls where the station was empty/full and scaling
        -- by that per-poll duration approximates minutes_empty /
        -- minutes_full without needing continuous per-minute data —
        -- coarser than true minute-by-minute tracking, but a reasonable
        -- approximation given the ~10-min poll interval.
        sum(case when num_bikes_available = 0 then 1 else 0 end)
            * (60.0 / count(*)) as minutes_empty,
        sum(case when num_docks_available = 0 then 1 else 0 end)
            * (60.0 / count(*)) as minutes_full

    from status
    group by station_id, system_id, partition_date, partition_hour

)

select * from hourly
