-- The weather FORECAST archive — NOT weather actuals. This is the
-- leakage-safe source for ML features: at prediction time, a model
-- only ever has access to what the forecast said, not what actually
-- happened. issued_at is what makes this usable: it lets a training
-- pipeline join "the forecast that existed AT prediction time" rather
-- than "the forecast that turned out to be correct."

with source as (

    select *
    from read_parquet(
        '{{ var("raw_data_path") }}/weather/forecasts/issued_dt=*/*.parquet',
        hive_partitioning = true
    )

),

renamed as (

    select
        system_id,
        issued_at,
        forecast_target_time,
        temperature_2m_c,
        precipitation_mm,
        wind_speed_10m_kmh,
        relative_humidity_2m_pct,
        issued_dt as partition_date

    from source

)

select * from renamed
