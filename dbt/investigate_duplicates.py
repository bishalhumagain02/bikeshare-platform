"""
One-off investigation script — not part of the pipeline, just for
digging into the 141 duplicate trip_id finding. Run from inside dbt/:

    python investigate_duplicates.py
"""

import duckdb

con = duckdb.connect("bikeshare.duckdb")

print("=== Top duplicated trip_ids ===")
dupes = con.execute("""
    select trip_id, count(*) as n
    from stg_trips
    group by trip_id
    having count(*) > 1
    order by n desc
    limit 10
""").df()
print(dupes)

if len(dupes) > 0:
    first_id = dupes.iloc[0]["trip_id"]
    print(f"\n=== Full rows for trip_id = {first_id} ===")
    detail = con.execute(
        "select * from stg_trips where trip_id = ?", [first_id]
    ).df()
    print(detail.to_string())