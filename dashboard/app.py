"""
Bike-Share Intelligence Platform — Analytics Dashboard

Reads directly from the dbt-built DuckDB warehouse (bikeshare.duckdb).
Run from the repo root:

    streamlit run dashboard/app.py

Requires dbt build to have been run first (dbt/bikeshare.duckdb must exist).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parents[1] / "dbt" / "bikeshare.duckdb"

st.set_page_config(page_title="Bike-Share Intelligence Platform", layout="wide")


@st.cache_resource
def get_connection():
    if not DB_PATH.exists():
        st.error(
            f"Database not found at {DB_PATH}. Run `dbt build` from the dbt/ "
            "folder first."
        )
        st.stop()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    # Same fix as src/ml/train.py — see docs/DECISIONS.md. Without this,
    # any date/time display or comparison here would silently differ
    # depending on the host machine's OS timezone.
    con.execute("SET TimeZone='UTC'")
    return con


con = get_connection()


def load(query: str) -> pd.DataFrame:
    return con.execute(query).df()


st.title("Bike-Share Intelligence Platform")
st.caption("Capital Bikeshare (DC Metro) — 2024-2025")

# --- Headline KPI ------------------------------------------------------

empty_hours_df = load("select * from mart_station_empty_hours order by empty_hours desc")
total_empty_hours = empty_hours_df["empty_hours"].sum()
worst_station = empty_hours_df.iloc[0] if len(empty_hours_df) else None

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total station empty-hours (all stations)", f"{total_empty_hours:,.0f}")
with col2:
    if worst_station is not None:
        st.metric("Worst station", worst_station["station_name"] or "—",
                   f"{worst_station['empty_hours']:,.0f} empty-hours")
with col3:
    daily_df = load("select * from mart_ridership_daily order by trip_date")
    st.metric("Total trips (period)", f"{daily_df['trip_count'].sum():,.0f}")

st.divider()

# --- Q1: Member vs casual patterns --------------------------------------

st.header("1. Member vs. Casual Rider Patterns")
hourly_df = load("""
    select trip_hour, member_casual, sum(trip_count) as trip_count
    from mart_ridership_hourly
    group by trip_hour, member_casual
    order by trip_hour
""")
if len(hourly_df):
    pivot = hourly_df.pivot(
        index="trip_hour", columns="member_casual", values="trip_count"
    ).fillna(0)
    st.bar_chart(pivot)
else:
    st.info("No data yet — run dbt build against real data to populate this chart.")

# --- Q2: Weather elasticity ----------------------------------------------

st.header("2. Weather Elasticity of Demand")
if len(daily_df) and daily_df["mean_temp_c"].notna().any():
    col1, col2 = st.columns(2)
    with col1:
        st.scatter_chart(daily_df, x="mean_temp_c", y="trip_count")
        st.caption("Daily trips vs. mean temperature (°C)")
    with col2:
        st.scatter_chart(daily_df, x="total_precip_mm", y="trip_count")
        st.caption("Daily trips vs. total precipitation (mm)")
else:
    st.info("No weather data joined yet.")

# --- Q3: Worst empty-hours stations --------------------------------------

st.header("3. Stations With the Worst Empty-Hours")
if len(empty_hours_df):
    st.dataframe(
        empty_hours_df[
            ["station_name", "capacity", "empty_hours", "full_hours", "likely_cause_flag"]
        ].head(10),
        use_container_width=True,
    )
else:
    st.info("No station status data yet.")

# --- Q4: Commute corridor asymmetry ---------------------------------------

st.header("4. Asymmetric Commute Corridors (Need Rebalancing)")
corridors_df = load("""
    select * from mart_commute_corridors
    where has_meaningful_volume
    order by abs(asymmetry) desc
    limit 10
""")
if len(corridors_df):
    st.dataframe(
        corridors_df[
            ["station_a_name", "station_b_name", "morning_a_to_b", "evening_b_to_a", "asymmetry"]
        ],
        use_container_width=True,
    )
else:
    st.info("No corridors with meaningful volume yet (need >=20 combined trips).")

# --- Q5: Peak demand vs capacity --------------------------------------------

st.header("5. Where Demand Exceeds Installed Capacity")
capacity_df = load("select * from mart_capacity_exceedance")
if len(capacity_df):
    coverage = capacity_df["matched_to_live_capacity"].mean() * 100
    st.caption(
        f"Join coverage: {coverage:.1f}% of demand-hours matched to a live "
        f"capacity value (name-based join — see docs/DECISIONS.md for why "
        f"an ID-based join isn't reliably possible)."
    )
    exceedance_summary = (
        capacity_df[capacity_df["matched_to_live_capacity"]]
        .groupby("station_name")["exceeds_capacity"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
    )
    st.bar_chart(exceedance_summary)
else:
    st.info("No capacity exceedance data yet.")
