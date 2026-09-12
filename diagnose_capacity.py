import duckdb

con = duckdb.connect("dbt/bikeshare.duckdb")

print("=== The 15 failing rows ===")
print(con.execute("""
    select s.station_id, d.station_name, s.partition_date, s.partition_hour,
           s.max_bikes_available, d.capacity
    from fct_station_status_hourly s
    inner join dim_station d on s.station_id = d.station_id and d.is_current
    where s.max_bikes_available > d.capacity
    order by s.station_id, s.partition_date
""").df().to_string())

print()
print("=== Does dim_station show a capacity CHANGE for these specific stations? ===")
print(con.execute("""
    select station_id, station_name, capacity, valid_from, valid_to, is_current
    from dim_station
    where station_id in (
        select distinct s.station_id
        from fct_station_status_hourly s
        inner join dim_station d on s.station_id = d.station_id and d.is_current
        where s.max_bikes_available > d.capacity
    )
    order by station_id, valid_from
""").df().to_string())