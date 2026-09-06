with source as (

    select *
    from read_parquet(
        '{{ var("raw_data_path") }}/station_information/dt=*/*.parquet',
        hive_partitioning = true
    )

),

renamed as (

    select
        station_id,
        system_id,
        name as station_name,
        lat,
        lon,
        capacity,
        region_id,
        station_type,
        -- NOTE: real GBFS feeds vary on this field's name across spec
        -- versions ("legacy_id" in some, "external_id" in others) —
        -- confirmed on this project's actual data that Capital
        -- Bikeshare's live feed uses "external_id". If you ever swap
        -- cities and hit a "column not found" error here again, check
        -- which name that feed actually uses.
        external_id,
        fetched_at,
        dt as partition_date

    from source

),

-- The poller captures a new snapshot every time it runs, so this
-- source accumulates one row per station PER CAPTURE DAY. The dbt
-- snapshot (SCD2) needs exactly one "current" row per station per
-- run — it's the thing that tracks history, not this staging model —
-- so we keep only each station's most recently fetched row here.
latest_per_station as (

    select *
    from renamed
    qualify row_number() over (
        partition by station_id
        order by fetched_at desc
    ) = 1

)

select * from latest_per_station
