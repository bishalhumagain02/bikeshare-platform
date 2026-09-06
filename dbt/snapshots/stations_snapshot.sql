{% snapshot stations_snapshot %}

{{
    config(
        target_schema='snapshots',
        unique_key='station_id',
        strategy='check',
        check_cols=['station_name', 'lat', 'lon', 'capacity', 'region_id', 'station_type'],
    )
}}

select * from {{ ref('stg_stations') }}

{% endsnapshot %}
