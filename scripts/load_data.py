"""
Loads BLS OEWS (MSA-level) employment data and Census CBSA Gazetteer data
(land area, centroid lat/lon) into a SQLite database.

Usage: python scripts/load_data.py
Reads from data/raw/, writes data/job_market.db.
"""

import re
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "job_market.db"

OEWS_FILE = RAW_DIR / "MSA_M2025_dl.xlsx"
GAZ_FILE = RAW_DIR / "2025_Gaz_cbsa_national.txt"
POP_FILE = RAW_DIR / "cbsa-est2025-alldata.csv"
UNEMPLOYMENT_FILE = RAW_DIR / "fred_unemployment.csv"
EDUCATION_FILE = RAW_DIR / "acs_education.csv"

# Plain numeric fields: BLS uses "*"/"**" for "not available" (no top-code
# concept applies), so a straight coerce-to-NaN is correct here.
NUMERIC_COLS = ["TOT_EMP", "LOC_QUOTIENT", "JOBS_1000"]

# Wage fields additionally use "#" for *top-coded* values (a known lower
# bound - e.g. "at least $239,200/yr" - not a missing value). Coercing "#"
# straight to NaN the way NUMERIC_COLS does would silently throw that lower
# bound away. HOURLY_TOPCODE/ANNUAL_TOPCODE are BLS's own published caps
# (see the raw file's "Field Descriptions" sheet).
HOURLY_WAGE_COLS = ["H_MEAN", "H_PCT10", "H_PCT25", "H_MEDIAN", "H_PCT75", "H_PCT90"]
ANNUAL_WAGE_COLS = ["A_MEAN", "A_PCT10", "A_PCT25", "A_MEDIAN", "A_PCT75", "A_PCT90"]
HOURLY_TOPCODE = 115.00
ANNUAL_TOPCODE = 239200


def parse_wage_column(series: pd.Series, topcode_value: float) -> tuple[pd.Series, pd.Series]:
    """Coerce a wage column to numeric, tracking "#" (top-coded) separately
    from "*"/"**" (not available) instead of collapsing both to NaN."""
    topcoded = series.astype(str).str.strip() == "#"
    numeric = pd.to_numeric(series.mask(topcoded, topcode_value), errors="coerce")
    return numeric, topcoded


def load_oews() -> pd.DataFrame:
    df = pd.read_excel(OEWS_FILE)
    df = df[df["O_GROUP"].isin(["major", "detailed"])].copy()

    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    topcoded_flags = []
    for col in HOURLY_WAGE_COLS:
        df[col], flag = parse_wage_column(df[col], HOURLY_TOPCODE)
        topcoded_flags.append(flag)
    for col in ANNUAL_WAGE_COLS:
        df[col], flag = parse_wage_column(df[col], ANNUAL_TOPCODE)
        topcoded_flags.append(flag)
    # One row-level flag rather than one per wage column: keeps the schema
    # from growing by 12 boolean columns for a case that's rare and, when it
    # happens, usually hits several of a row's wage fields at once (e.g. if
    # the mean is top-coded, the 90th percentile usually is too).
    df["WAGE_TOPCODED"] = pd.concat(topcoded_flags, axis=1).any(axis=1)

    return df


def load_gazetteer() -> pd.DataFrame:
    gaz = pd.read_csv(GAZ_FILE, sep="|", dtype={"GEOID": str})
    gaz = gaz.rename(
        columns={
            "GEOID": "area_code",
            "ALAND_SQMI": "land_area_sqmi",
            "INTPTLAT": "lat",
            "INTPTLONG": "lon",
        }
    )
    return gaz[["area_code", "land_area_sqmi", "lat", "lon"]]


def load_population() -> pd.DataFrame:
    # This file also contains each large metro's "Metropolitan Division"
    # sub-areas (e.g. Atlanta splits into two), sharing the SAME CBSA code
    # as their parent metro row (a separate MDIV column distinguishes them).
    # OEWS reports the unified metro, not its divisions, so keeping only
    # LSAD == 'Metropolitan Statistical Area' is what keeps this a clean
    # one-row-per-code join instead of fanning out into duplicates.
    pop = pd.read_csv(POP_FILE, dtype={"CBSA": str, "STCOU": str}, encoding="latin-1")
    pop = pop[(pop["STCOU"].isna() | (pop["STCOU"] == "")) & (pop["LSAD"] == "Metropolitan Statistical Area")]
    pop = pop.rename(columns={"CBSA": "area_code", "POPESTIMATE2025": "population"})
    return pop[["area_code", "population"]]


def load_unemployment() -> pd.DataFrame:
    # Fetched separately by scripts/fetch_unemployment.py (via FRED, since
    # BLS's own site/download domain is blocked from this environment - see
    # NOTES.md). Static cached file, same treatment as the other raw inputs.
    return pd.read_csv(UNEMPLOYMENT_FILE, dtype={"area_code": str})


def load_education() -> pd.DataFrame:
    # Fetched separately by scripts/fetch_education.py (Census ACS 5-year).
    return pd.read_csv(EDUCATION_FILE, dtype={"area_code": str})


def build_msa_table(
    oews: pd.DataFrame, gaz: pd.DataFrame, pop: pd.DataFrame, unemployment: pd.DataFrame, education: pd.DataFrame
) -> pd.DataFrame:
    msa = oews[["AREA", "AREA_TITLE"]].drop_duplicates()
    msa = msa.rename(columns={"AREA": "area_code", "AREA_TITLE": "area_title"})
    msa["area_code"] = msa["area_code"].astype(str)
    msa = msa.merge(gaz, on="area_code", how="left")
    msa = msa.merge(pop, on="area_code", how="left")
    msa = msa.merge(unemployment, on="area_code", how="left")
    msa = msa.merge(education, on="area_code", how="left")
    return msa


def build_occupation_table(oews: pd.DataFrame) -> pd.DataFrame:
    major = oews[oews["O_GROUP"] == "major"][["OCC_CODE", "OCC_TITLE"]].drop_duplicates()
    major_titles = dict(zip(major["OCC_CODE"], major["OCC_TITLE"]))

    occ = oews[["OCC_CODE", "OCC_TITLE", "O_GROUP"]].drop_duplicates()
    occ["major_group_code"] = occ["OCC_CODE"].apply(lambda c: re.sub(r"^(\d\d)-.*", r"\1-0000", c))
    occ["major_group_title"] = occ["major_group_code"].map(major_titles)
    occ = occ.rename(columns={"OCC_CODE": "soc_code", "OCC_TITLE": "soc_title", "O_GROUP": "level"})
    return occ[["soc_code", "soc_title", "level", "major_group_code", "major_group_title"]]


EMPLOYMENT_COLS = (
    ["AREA", "OCC_CODE", "TOT_EMP", "LOC_QUOTIENT", "JOBS_1000", "WAGE_TOPCODED"]
    + HOURLY_WAGE_COLS
    + ANNUAL_WAGE_COLS
)
EMPLOYMENT_RENAME = {
    "AREA": "area_code",
    "OCC_CODE": "soc_code",
    "TOT_EMP": "tot_emp",
    "LOC_QUOTIENT": "loc_quotient",
    "JOBS_1000": "jobs_1000",
    "WAGE_TOPCODED": "wage_topcoded",
    "H_MEAN": "h_mean",
    "H_PCT10": "h_pct10",
    "H_PCT25": "h_pct25",
    "H_MEDIAN": "h_median",
    "H_PCT75": "h_pct75",
    "H_PCT90": "h_pct90",
    "A_MEAN": "a_mean",
    "A_PCT10": "a_pct10",
    "A_PCT25": "a_pct25",
    "A_MEDIAN": "a_median",
    "A_PCT75": "a_pct75",
    "A_PCT90": "a_pct90",
}


def build_employment_table(oews: pd.DataFrame) -> pd.DataFrame:
    emp = oews[EMPLOYMENT_COLS].copy()
    emp = emp.rename(columns=EMPLOYMENT_RENAME)
    emp["area_code"] = emp["area_code"].astype(str)
    return emp


def main():
    oews = load_oews()
    gaz = load_gazetteer()
    pop = load_population()
    unemployment = load_unemployment()
    education = load_education()

    msa = build_msa_table(oews, gaz, pop, unemployment, education)
    occupation = build_occupation_table(oews)
    employment = build_employment_table(oews)

    engine = create_engine(f"sqlite:///{DB_PATH}")
    msa.to_sql("msa", engine, if_exists="replace", index=False)
    occupation.to_sql("occupation", engine, if_exists="replace", index=False)
    employment.to_sql("employment", engine, if_exists="replace", index=False)

    print(f"msa: {len(msa)} rows")
    print(f"occupation: {len(occupation)} rows")
    print(f"employment: {len(employment)} rows")
    print(f"MSAs missing gazetteer match: {msa['land_area_sqmi'].isna().sum()}")
    print(f"MSAs missing population/unemployment (Puerto Rico metros - separate files, not pulled): "
          f"{msa['population'].isna().sum()}/{msa['unemployment_rate'].isna().sum()}")


if __name__ == "__main__":
    main()