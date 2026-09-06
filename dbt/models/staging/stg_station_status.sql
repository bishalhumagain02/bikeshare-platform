-- Renaming, casting, and deduping ONLY — per the plan, no business
-- logic belongs in staging. Reads Hive-partitioned Parquet directly;
-- DuckDB needs no separate load step.

with source as (

    select *
    from read_parquet(
        '{{ var("raw_data_path") }}/station_status/dt=*/hr=*/*.parquet',
        hive_partitioning = true
    )

),

renamed as (

    select
        station_id,
        system_id,
        num_bikes_available,
        num_docks_available,
        coalesce(num_bikes_disabled, 0) as num_bikes_disabled,
        coalesce(num_docks_disabled, 0) as num_docks_disabled,
        is_installed,
        is_renting,
        is_returning,
        to_timestamp(last_reported) as last_reported_at,
        fetched_at,
        dt as partition_date,
        hr as partition_hour

    from source

),

deduped as (

    -- Same station can appear more than once per fetched_at in rare
    -- retry/overlap scenarios — one row per (station, fetched_at).
    select distinct * from renamed

)

select * from deduped
