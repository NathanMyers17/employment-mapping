"""
Job Market Map — Phase 2 MVP.

Pick a job field (SOC major group), see per-metro total employment on a map,
click a metro for its land area, mean wage, and top detailed occupations.
"""

import sqlite3
from pathlib import Path

import branca.colormap as cm
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

DB_PATH = Path(__file__).resolve().parent / "data" / "job_market.db"

# Sequential blue ramp, light -> dark (dataviz palette: sequential hue = blue).
SEQUENTIAL_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

st.set_page_config(page_title="Job Market Map", layout="wide")

# Reset every rerun (Streamlit re-executes the whole script on each
# interaction), so this always reflects exactly the queries behind what's
# on screen right now.
queries_log = []


@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def run_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    queries_log.append((sql.strip(), params))
    return pd.read_sql(sql, get_connection(), params=params)


st.title("Job Market Map")
st.caption(
    "Explore where employment in a given job field is concentrated across U.S. metro areas."
)

major_groups = run_query(
    "SELECT soc_code, soc_title FROM occupation WHERE level = 'major' ORDER BY soc_title"
)
field_title = st.selectbox("Job field", major_groups["soc_title"])
field_code = major_groups.loc[major_groups["soc_title"] == field_title, "soc_code"].iloc[0]

emp_df = run_query(
    """
    SELECT m.area_code, m.area_title, m.lat, m.lon, m.land_area_sqmi,
           e.tot_emp, e.a_mean, e.h_mean
    FROM employment e
    JOIN msa m ON m.area_code = e.area_code
    WHERE e.soc_code = ? AND e.tot_emp IS NOT NULL
    """,
    (field_code,),
)

# Quantile bins keep the color scale readable despite employment being
# heavily right-skewed (a few huge metros, many small ones).
base_colormap = cm.LinearColormap(
    SEQUENTIAL_RAMP, vmin=emp_df["tot_emp"].min(), vmax=emp_df["tot_emp"].max()
)
step_colormap = base_colormap.to_step(n=6, data=emp_df["tot_emp"], method="quantiles")
# Marker fill uses the quantile-stepped colors (better differentiation on
# skewed data), but the on-map legend uses the plain two-endpoint gradient —
# to_step's legend places a label at every bin edge's literal value, and on
# this skewed a distribution those edges bunch up and overlap.
base_colormap.caption = "Total employment"

fmap = folium.Map(location=[39.8, -98.6], zoom_start=4, tiles="cartodbpositron")

max_emp = emp_df["tot_emp"].max()
for row in emp_df.itertuples():
    folium.CircleMarker(
        location=[row.lat, row.lon],
        radius=4 + 10 * (row.tot_emp / max_emp) ** 0.5,
        color=step_colormap(row.tot_emp),
        weight=1,
        fill=True,
        fill_color=step_colormap(row.tot_emp),
        fill_opacity=0.85,
        tooltip=row.area_title,
    ).add_to(fmap)

base_colormap.add_to(fmap)

col_map, col_panel = st.columns([3, 2])

with col_map:
    map_state = st_folium(
        fmap, width=None, height=600, returned_objects=["last_object_clicked_tooltip"]
    )

with col_panel:
    st.subheader("Metro details")
    clicked_title = (map_state or {}).get("last_object_clicked_tooltip")

    if clicked_title and clicked_title in emp_df["area_title"].values:
        row = emp_df.loc[emp_df["area_title"] == clicked_title].iloc[0]
        st.markdown(f"### {row.area_title}")
        st.metric("Total employment in field", f"{int(row.tot_emp):,}")
        st.metric(
            "Mean annual wage",
            f"${row.a_mean:,.0f}" if pd.notna(row.a_mean) else "N/A",
        )
        st.write(
            f"Land area: {row.land_area_sqmi:,.0f} sq mi"
            if pd.notna(row.land_area_sqmi)
            else "Land area: N/A"
        )

        top_occ = run_query(
            """
            SELECT o.soc_title, e.tot_emp, e.a_mean, e.h_mean
            FROM employment e
            JOIN occupation o ON o.soc_code = e.soc_code
            WHERE e.area_code = ? AND o.major_group_code = ? AND o.level = 'detailed'
            ORDER BY e.tot_emp DESC
            LIMIT 5
            """,
            (row.area_code, field_code),
        )
        st.write("**Top occupations in this field:**")
        top_occ_display = top_occ.rename(
            columns={
                "soc_title": "Occupation",
                "tot_emp": "Employment",
                "a_mean": "Mean annual wage",
                "h_mean": "Mean hourly wage",
            }
        )
        top_occ_display[["Mean annual wage", "Mean hourly wage"]] = top_occ_display[
            ["Mean annual wage", "Mean hourly wage"]
        ].fillna("N/A")
        st.dataframe(top_occ_display, hide_index=True)
    else:
        st.info("Click a metro on the map to see details.")

with st.expander("SQL used on this page"):
    for sql, params in queries_log:
        st.code(sql, language="sql")
        if params:
            st.caption(f"params: {params}")
