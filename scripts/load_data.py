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

NUMERIC_COLS = ["TOT_EMP", "A_MEAN", "H_MEAN"]


def load_oews() -> pd.DataFrame:
    df = pd.read_excel(OEWS_FILE)
    df = df[df["O_GROUP"].isin(["major", "detailed"])].copy()
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
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


def build_msa_table(oews: pd.DataFrame, gaz: pd.DataFrame) -> pd.DataFrame:
    msa = oews[["AREA", "AREA_TITLE"]].drop_duplicates()
    msa = msa.rename(columns={"AREA": "area_code", "AREA_TITLE": "area_title"})
    msa["area_code"] = msa["area_code"].astype(str)
    msa = msa.merge(gaz, on="area_code", how="left")
    return msa


def build_occupation_table(oews: pd.DataFrame) -> pd.DataFrame:
    major = oews[oews["O_GROUP"] == "major"][["OCC_CODE", "OCC_TITLE"]].drop_duplicates()
    major_titles = dict(zip(major["OCC_CODE"], major["OCC_TITLE"]))

    occ = oews[["OCC_CODE", "OCC_TITLE", "O_GROUP"]].drop_duplicates()
    occ["major_group_code"] = occ["OCC_CODE"].apply(lambda c: re.sub(r"^(\d\d)-.*", r"\1-0000", c))
    occ["major_group_title"] = occ["major_group_code"].map(major_titles)
    occ = occ.rename(columns={"OCC_CODE": "soc_code", "OCC_TITLE": "soc_title", "O_GROUP": "level"})
    return occ[["soc_code", "soc_title", "level", "major_group_code", "major_group_title"]]


def build_employment_table(oews: pd.DataFrame) -> pd.DataFrame:
    emp = oews[["AREA", "OCC_CODE", "TOT_EMP", "A_MEAN", "H_MEAN"]].copy()
    emp = emp.rename(
        columns={
            "AREA": "area_code",
            "OCC_CODE": "soc_code",
            "TOT_EMP": "tot_emp",
            "A_MEAN": "a_mean",
            "H_MEAN": "h_mean",
        }
    )
    emp["area_code"] = emp["area_code"].astype(str)
    return emp


def main():
    oews = load_oews()
    gaz = load_gazetteer()

    msa = build_msa_table(oews, gaz)
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


if __name__ == "__main__":
    main()
