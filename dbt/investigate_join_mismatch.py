"""
Diagnostic: why does the trip<->station join still fail near-100%
after switching to external_id? Run from inside dbt/:

    python investigate_join_mismatch.py
"""

import duckdb

con = duckdb.connect("bikeshare.duckdb")

print("=== dim_station: how many rows have a non-null external_id? ===")
print(con.execute("""
    select
        count(*) as total_stations,
        count(external_id) as non_null_external_id,
        count(*) filter (where external_id = '') as empty_string_external_id
    from dim_station
""").df())

print("\n=== Sample of dim_station.external_id values (raw) ===")
print(con.execute("select station_id, station_name, external_id from dim_station limit 10").df())

print("\n=== Sample of stg_trips.start_station_id values (raw) ===")
print(con.execute("select distinct start_station_id from stg_trips limit 10").df())

print("\n=== Any exact overlap at all between the two sets? ===")
print(con.execute("""
    select count(*) as overlapping_ids
    from (select distinct external_id from dim_station where external_id is not null) d
    inner join (select distinct start_station_id from stg_trips) t
        on d.external_id = t.start_station_id
""").df())