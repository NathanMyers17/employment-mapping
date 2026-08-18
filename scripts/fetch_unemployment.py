"""
One-time fetch of metro-level unemployment rates from FRED (which re-hosts
BLS LAUS data under a stable series-ID scheme, sidestepping BLS's own
blocked website and undocumented-to-us internal area-code crosswalk).

Series ID formula (reverse-engineered via FRED search, verified against
Atlanta/Chicago/Charlottesville): "LAUMT" + state_fips(2) + cbsa_code(5) +
"000000" + measure_code("03"=unemployment rate) + "A" (annual average).

Requires FRED_API_KEY in .env (free key: fred.stlouisfed.org/docs/api/api_key.html).
Usage: python scripts/fetch_unemployment.py
Reads data/raw/MSA_M2025_dl.xlsx (for area codes + states), writes
data/raw/fred_unemployment.csv.
"""

import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OEWS_FILE = RAW_DIR / "MSA_M2025_dl.xlsx"
OUT_FILE = RAW_DIR / "fred_unemployment.csv"

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
REQUEST_DELAY_SECONDS = 0.55  # FRED allows ~120 req/min; this stays well under that

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "PR": "72", "RI": "44", "SC": "45",
    "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51",
    "WA": "53", "WV": "54", "WI": "55", "WY": "56",
}


def load_metro_states() -> pd.DataFrame:
    df = pd.read_excel(OEWS_FILE)
    metros = df[["AREA", "PRIM_STATE"]].drop_duplicates()
    metros["AREA"] = metros["AREA"].astype(str)
    return metros


# For most multi-state metros, LAUS's series ID uses the same "primary
# state" OEWS reports in PRIM_STATE (verified against Chicago, IL-IN-WI ->
# IL). Two known exceptions found by testing all 393 metros against FRED:
# LAUS picked a different state than OEWS's PRIM_STATE for these.
STATE_OVERRIDES = {
    "19340": "IL",  # Davenport-Moline-Rock Island, IA-IL -> LAUS uses IL, not IA
    "48260": "OH",  # Weirton-Steubenville, WV-OH -> LAUS uses OH, not WV
}


def series_id(state_abbr: str, cbsa_code: str) -> str | None:
    state_abbr = STATE_OVERRIDES.get(cbsa_code, state_abbr)
    fips = STATE_FIPS.get(state_abbr)
    if fips is None:
        return None
    return f"LAUMT{fips}{cbsa_code}00000003A"


def fetch_latest_rate(api_key: str, sid: str) -> tuple[float, str] | None:
    resp = requests.get(
        FRED_OBSERVATIONS_URL,
        params={
            "series_id": sid,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    obs = resp.json().get("observations", [])
    if not obs or obs[0]["value"] == ".":
        return None
    return float(obs[0]["value"]), obs[0]["date"][:4]


def main():
    load_dotenv()
    api_key = os.environ["FRED_API_KEY"]

    metros = load_metro_states()
    rows = []
    misses = []
    for i, row in enumerate(metros.itertuples(), start=1):
        sid = series_id(row.PRIM_STATE, row.AREA)
        result = fetch_latest_rate(api_key, sid) if sid else None
        if result is None:
            misses.append((row.AREA, row.PRIM_STATE, sid))
        else:
            rate, year = result
            rows.append({"area_code": row.AREA, "unemployment_rate": rate, "unemployment_rate_year": year})
        if i % 50 == 0:
            print(f"...{i}/{len(metros)}")
        time.sleep(REQUEST_DELAY_SECONDS)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_FILE, index=False)
    print(f"Wrote {len(out)} rows to {OUT_FILE}")
    print(f"Misses ({len(misses)}): {misses}")


if __name__ == "__main__":
    main()
