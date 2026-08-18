"""
Job Market Map — Phase 4.

Pick a job field (and optionally drill into a specific detailed occupation),
see per-metro data on a map colored either by raw employment or by
concentration (location quotient) relative to the national average. Click a
metro for wages (mean + 10th-90th percentile range), top occupations in the
field, and place-level context (population, unemployment, land area,
educational attainment) that doesn't depend on the field/occupation picked.
"""

import sqlite3
from pathlib import Path

import branca.colormap as cm
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

DB_PATH = Path(__file__).resolve().parent / "data" / "job_market.db"

# Sequential blue ramp, light -> dark (dataviz palette: sequential hue = blue)
# for "Total employment" mode - a magnitude metric.
SEQUENTIAL_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

# Diverging blue<->red pair for "Concentration" mode - location quotient has
# a meaningful neutral point (1.0 = national average), so this is polarity
# data (under- vs over-represented), not magnitude, and gets a diverging
# scale per the dataviz palette rather than a sequential one.
DIVERGING_LOW = "#2a78d6"   # under-concentrated
DIVERGING_MID = "#898781"   # ~national average
DIVERGING_HIGH = "#e34948"  # over-concentrated
LQ_COLOR_CAP = 3.0  # values above this shade the same as the cap; LQ has a
                     # long tail (max observed: 364) that would otherwise
                     # wash out the rest of the scale.

SUPPRESSED_COLOR = "#898781"

# Matches scripts/load_data.py's BLS-published top-code caps, so wage
# figures that hit them can be shown as "$X+" instead of a bare number.
ANNUAL_TOPCODE = 239200
HOURLY_TOPCODE = 115.00

st.set_page_config(page_title="Job Market Map", layout="wide")


@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def run_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql(sql, get_connection(), params=params)


def fmt_wage(value, topcode=None) -> str:
    if pd.isna(value):
        return "N/A"
    suffix = "+" if topcode is not None and value == topcode else ""
    return f"${value:,.0f}{suffix}"


st.title("Job Market Map")
st.caption(
    "Explore where employment in a given job field is concentrated across U.S. metro areas."
)

major_groups = run_query(
    "SELECT soc_code, soc_title FROM occupation WHERE level = 'major' ORDER BY soc_title"
)
field_title = st.selectbox("Job field", major_groups["soc_title"])
field_code = major_groups.loc[major_groups["soc_title"] == field_title, "soc_code"].iloc[0]

# Detailed occupations within the chosen field, for optional drill-down.
# Keyed on field_code so picking a new field resets this back to "All".
detailed_occs = run_query(
    """
    SELECT soc_code, soc_title FROM occupation
    WHERE level = 'detailed' AND major_group_code = ?
    ORDER BY soc_title
    """,
    (field_code,),
)
ALL_OCCUPATIONS = "All occupations in this field"
occ_title = st.selectbox(
    "Occupation (optional)",
    [ALL_OCCUPATIONS] + list(detailed_occs["soc_title"]),
    key=f"occ_select_{field_code}",
)
if occ_title == ALL_OCCUPATIONS:
    selected_code, display_title = field_code, field_title
else:
    selected_code = detailed_occs.loc[detailed_occs["soc_title"] == occ_title, "soc_code"].iloc[0]
    display_title = occ_title

color_mode = st.radio(
    "Color map by",
    ["Total employment", "Concentration (location quotient)"],
    horizontal=True,
)

# No "AND tot_emp IS NOT NULL" filter here (unlike Phase 2): BLS sometimes
# suppresses the employment count specifically while still publishing wage
# data for the same metro/occupation. Filtering those rows out entirely
# made them vanish from the map with no indication anything existed there.
# They're handled as a distinct marker style below instead.
emp_df = run_query(
    """
    SELECT m.area_code, m.area_title, m.lat, m.lon, m.land_area_sqmi,
           m.population, m.unemployment_rate, m.unemployment_rate_year,
           m.pct_bachelors_or_higher, m.pct_bachelors_or_higher_moe,
           e.tot_emp, e.loc_quotient, e.jobs_1000,
           e.a_mean, e.h_mean, e.a_pct10, e.a_pct90, e.wage_topcoded
    FROM employment e
    JOIN msa m ON m.area_code = e.area_code
    WHERE e.soc_code = ?
    """,
    (selected_code,),
)
emp_df["is_suppressed"] = emp_df["tot_emp"].isna()
has_data = emp_df[~emp_df["is_suppressed"]]
suppressed = emp_df[emp_df["is_suppressed"]]

fmap = folium.Map(location=[39.8, -98.6], zoom_start=4, tiles="cartodbpositron")

if color_mode == "Total employment":
    # Quantile bins keep the color scale readable despite employment being
    # heavily right-skewed (a few huge metros, many small ones).
    base_colormap = cm.LinearColormap(
        SEQUENTIAL_RAMP, vmin=has_data["tot_emp"].min(), vmax=has_data["tot_emp"].max()
    )
    step_colormap = base_colormap.to_step(n=6, data=has_data["tot_emp"], method="quantiles")
    # Marker fill uses the quantile-stepped colors (better differentiation
    # on skewed data), but the on-map legend uses the plain two-endpoint
    # gradient - to_step's legend places a label at every bin edge's
    # literal value, and on this skewed a distribution those edges bunch up
    # and overlap.
    base_colormap.caption = "Total employment"
    color_fn = step_colormap
    legend = base_colormap
else:
    # Diverging scale centered on loc_quotient = 1.0 (national average).
    # Values are clipped (not filtered) to LQ_COLOR_CAP for color purposes
    # only - the real value is still shown in the tooltip/panel.
    legend = cm.LinearColormap(
        [DIVERGING_LOW, DIVERGING_MID, DIVERGING_HIGH],
        index=[0, 1, LQ_COLOR_CAP],
        vmin=0,
        vmax=LQ_COLOR_CAP,
    )
    legend.caption = "Concentration (location quotient)"
    color_fn = lambda lq: legend(min(lq, LQ_COLOR_CAP))

max_emp = has_data["tot_emp"].max() if len(has_data) else 1
for row in has_data.itertuples():
    color_value = row.tot_emp if color_mode == "Total employment" else row.loc_quotient
    folium.CircleMarker(
        location=[row.lat, row.lon],
        radius=4 + 10 * (row.tot_emp / max_emp) ** 0.5,
        color=color_fn(color_value),
        weight=1,
        fill=True,
        fill_color=color_fn(color_value),
        fill_opacity=0.85,
        tooltip=row.area_title,
    ).add_to(fmap)

for row in suppressed.itertuples():
    folium.CircleMarker(
        location=[row.lat, row.lon],
        radius=4,
        color=SUPPRESSED_COLOR,
        weight=1,
        fill=True,
        fill_color=SUPPRESSED_COLOR,
        fill_opacity=0.4,
        tooltip=f"{row.area_title} (employment data suppressed)",
    ).add_to(fmap)

legend.add_to(fmap)

col_map, col_panel = st.columns([3, 2])

with col_map:
    map_state = st_folium(
        fmap, width=None, height=600, returned_objects=["last_object_clicked_tooltip"]
    )

with col_panel:
    st.subheader("Metro details")
    clicked_title = (map_state or {}).get("last_object_clicked_tooltip")
    # Suppressed markers' tooltips carry a " (employment data suppressed)"
    # suffix (see above), so strip it to match back against area_title.
    clicked_title = (clicked_title or "").replace(" (employment data suppressed)", "")

    if clicked_title and clicked_title in emp_df["area_title"].values:
        row = emp_df.loc[emp_df["area_title"] == clicked_title].iloc[0]
        st.markdown(f"### {row.area_title}")

        if row.is_suppressed:
            st.warning(
                "Employment count suppressed by BLS for this occupation in "
                "this metro (too few reporting employers). Other figures "
                "below reflect whatever BLS still published."
            )
        else:
            st.metric("Total employment", f"{int(row.tot_emp):,}")
            if pd.notna(row.loc_quotient):
                st.metric("Location quotient", f"{row.loc_quotient:.2f}")
                st.caption("1.0 = same share of local jobs as the national average.")

        st.metric("Mean annual wage", fmt_wage(row.a_mean, ANNUAL_TOPCODE))
        if pd.notna(row.a_pct10) and pd.notna(row.a_pct90):
            # st.write renders markdown, and markdown treats a pair of "$"
            # as inline LaTeX delimiters - two wage figures in one string
            # means two "$" signs, so escape them or BLS's actual numbers
            # get typeset as a formula instead of shown as text.
            lo = fmt_wage(row.a_pct10, ANNUAL_TOPCODE).replace("$", r"\$")
            hi = fmt_wage(row.a_pct90, ANNUAL_TOPCODE).replace("$", r"\$")
            st.write(f"Wage range (10th–90th percentile): {lo} – {hi}")

        st.divider()
        st.write("**About this metro** (independent of the field/occupation selected above):")

        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("Population", f"{int(row.population):,}" if pd.notna(row.population) else "N/A")
            st.write(
                f"Land area: {row.land_area_sqmi:,.0f} sq mi"
                if pd.notna(row.land_area_sqmi)
                else "Land area: N/A"
            )
        with col_b:
            if pd.notna(row.unemployment_rate):
                st.metric("Unemployment rate", f"{row.unemployment_rate:.1f}%")
                st.caption(f"{int(row.unemployment_rate_year)} annual average")
            else:
                st.metric("Unemployment rate", "N/A")
            if pd.notna(row.pct_bachelors_or_higher):
                st.write(f"Bachelor's degree or higher: {row.pct_bachelors_or_higher:.1f}%")
                st.caption(f"±{row.pct_bachelors_or_higher_moe:.1f} pts margin of error")
            else:
                st.write("Bachelor's degree or higher: N/A")

        top_occ = run_query(
            """
            SELECT o.soc_title, e.tot_emp, e.loc_quotient, e.a_mean, e.h_mean
            FROM employment e
            JOIN occupation o ON o.soc_code = e.soc_code
            WHERE e.area_code = ? AND o.major_group_code = ? AND o.level = 'detailed'
            ORDER BY e.tot_emp DESC
            LIMIT 5
            """,
            (row.area_code, field_code),
        )
        st.write(f"**Top occupations in {field_title}:**")
        top_occ_display = top_occ.rename(
            columns={
                "soc_title": "Occupation",
                "tot_emp": "Employment",
                "loc_quotient": "Concentration (LQ)",
                "a_mean": "Mean annual wage",
                "h_mean": "Mean hourly wage",
            }
        )
        top_occ_display[["Mean annual wage", "Mean hourly wage"]] = top_occ_display[
            ["Mean annual wage", "Mean hourly wage"]
        ].fillna("N/A")
        top_occ_display["Concentration (LQ)"] = top_occ_display["Concentration (LQ)"].map(
            lambda v: f"{v:.2f}" if pd.notna(v) else "N/A"
        )
        st.dataframe(top_occ_display, hide_index=True)
    else:
        st.info("Click a metro on the map to see details.")
