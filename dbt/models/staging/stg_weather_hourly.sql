with source as (

    select *
    from read_parquet(
        '{{ var("raw_data_path") }}/weather/actuals/year=*/*.parquet',
        hive_partitioning = true
    )

),

renamed as (

    select
        system_id,
        time_utc as weather_hour,
        temperature_2m_c,
        precipitation_mm,
        wind_speed_10m_kmh,
        relative_humidity_2m_pct,
        year as partition_year

    from source

)

select * from renamed
