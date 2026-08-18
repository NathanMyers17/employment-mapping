"""
One-time fetch of metro-level educational attainment from the Census ACS
5-year Subject Tables (S1501 - Educational Attainment).

Variable: S1501_C02_015E - percent of population 25+ with a bachelor's
degree or higher (total population, not broken out by sex/race - simplest
single figure, per NOTES.md's Phase 4 scope). S1501_C02_015M is its margin
of error, kept alongside rather than discarded.

Requires CENSUS_API_KEY in .env (free key: api.census.gov/data/key_signup.html).
Usage: python scripts/fetch_education.py
Writes data/raw/acs_education.csv.
"""

import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT_FILE = RAW_DIR / "acs_education.csv"

ACS_URL = "https://api.census.gov/data/2024/acs/acs5/subject"
GEOGRAPHY = "metropolitan statistical area/micropolitan statistical area:*"


def main():
    load_dotenv()
    api_key = os.environ["CENSUS_API_KEY"]

    resp = requests.get(
        ACS_URL,
        params={
            "get": "NAME,S1501_C02_015E,S1501_C02_015M",
            "for": GEOGRAPHY,
            "key": api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    df = pd.DataFrame(rows[1:], columns=rows[0])

    # The combined CBSA endpoint returns both Metro and Micro areas; OEWS
    # (and everything else in this project) is metro-only.
    df = df[df["NAME"].str.contains("Metro Area")]

    df = df.rename(
        columns={
            "metropolitan statistical area/micropolitan statistical area": "area_code",
            "S1501_C02_015E": "pct_bachelors_or_higher",
            "S1501_C02_015M": "pct_bachelors_or_higher_moe",
        }
    )
    df["pct_bachelors_or_higher"] = pd.to_numeric(df["pct_bachelors_or_higher"], errors="coerce")
    df["pct_bachelors_or_higher_moe"] = pd.to_numeric(df["pct_bachelors_or_higher_moe"], errors="coerce")

    out = df[["area_code", "pct_bachelors_or_higher", "pct_bachelors_or_higher_moe"]]
    out.to_csv(OUT_FILE, index=False)
    print(f"Wrote {len(out)} rows to {OUT_FILE}")


if __name__ == "__main__":
    main()
