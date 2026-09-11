import duckdb
import sys
sys.path.insert(0, ".")
from src.features.build_features import build_features

con = duckdb.connect("dbt/bikeshare.duckdb", read_only=True)
station_status = con.execute(
    "select station_id, fetched_at, num_bikes_available, num_docks_available from stg_station_status"
).df()
capacity = con.execute("select station_id, capacity from dim_station where is_current").df()
forecast = con.execute(
    "select issued_at, forecast_target_time, temperature_2m_c, precipitation_mm from stg_weather_forecast"
).df()

print("Weather forecast rows available:", len(forecast))
print(forecast[["issued_at", "forecast_target_time"]].describe())

df = build_features(station_status, capacity, forecast)
print()
print("Feature rows:", len(df))
print("forecast_temp_c non-null:", df["forecast_temp_c"].notna().sum(), "/", len(df))
print("forecast_precip_mm non-null:", df["forecast_precip_mm"].notna().sum(), "/", len(df))