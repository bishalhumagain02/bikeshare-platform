-- Answers: "What is the weather elasticity of demand?" and feeds
-- daily trend charts. One row per calendar day.

with daily_trips as (

    select
        trip_date,
        count(*) as trip_count,
        count(*) filter (where member_casual = 'member') as member_trip_count,
        count(*) filter (where member_casual = 'casual') as casual_trip_count
    from {{ ref('fct_trip') }}
    group by trip_date

),

daily_weather as (

    select
        date_trunc('day', weather_hour) as trip_date,
        avg(temperature_2m_c) as mean_temp_c,
        sum(precipitation_mm) as total_precip_mm,
        avg(wind_speed_10m_kmh) as mean_wind_kmh
    from {{ ref('stg_weather_hourly') }}
    group by date_trunc('day', weather_hour)

)

select
    t.trip_date,
    t.trip_count,
    t.member_trip_count,
    t.casual_trip_count,
    w.mean_temp_c,
    w.total_precip_mm,
    w.mean_wind_kmh,
    extract(dow from t.trip_date) as day_of_week,  -- 0=Sunday per DuckDB default
    extract(dow from t.trip_date) in (0, 6) as is_weekend

from daily_trips t
left join daily_weather w on t.trip_date = w.trip_date
