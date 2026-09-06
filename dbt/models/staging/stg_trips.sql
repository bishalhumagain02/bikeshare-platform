with source as (

    select *
    from read_parquet(
        '{{ var("raw_data_path") }}/trips/year=*/month=*/*.parquet',
        hive_partitioning = true,
        union_by_name = true
    )

),

renamed as (

    select
        -- old-era rows have no trip_id at all; synthesize a stable one
        -- from the row's own content rather than leaving it fully null,
        -- so downstream `unique` tests have something meaningful to key on
        coalesce(
            trip_id,
            md5(concat_ws('|', started_at::varchar, ended_at::varchar,
                           start_station_id, end_station_id))
        ) as trip_id,
        system_id,
        schema_era,
        rideable_type,
        started_at,
        ended_at,
        duration_seconds,
        start_station_id,
        start_station_name,
        end_station_id,
        end_station_name,
        start_lat,
        start_lng,
        end_lat,
        end_lng,
        member_casual,
        year as partition_year,
        month as partition_month

    from source

),

deduped as (

    select distinct * from renamed

)

select * from deduped
