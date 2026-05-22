#!/usr/bin/env python3
"""
COT (Commitments of Traders) Report Fetcher
Downloads CFTC COT data, saves CSV, and prints a formatted summary.

CFTC publishes updated files every Friday ~3:30 PM ET.
Files have no header row — column positions are hardcoded per CFTC layout spec.
"""

import csv
import io
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

warnings.filterwarnings("ignore")  # suppress urllib3/ssl warnings on macOS

try:
    import requests
except ImportError:
    print("Missing dependency: pip install --user requests")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Output path for cot_summary.json.
# CI (GitHub Actions): set COT_OUTPUT_DIR env var to repo workspace root.
# Local: defaults to Google Drive sync folder so the Claude routine can read it.
import os as _os
_env_out = _os.environ.get("COT_OUTPUT_DIR")
GDRIVE_COT = Path(_env_out) if _env_out else Path.home() / "Library/CloudStorage/GoogleDrive-hugo@tlight617.com/My Drive/COT"

COT_URLS = {
    "legacy":   "https://www.cftc.gov/dea/newcot/deafut.txt",
    "tff":      "https://www.cftc.gov/dea/newcot/FinFutWk.txt",
    "disagg":   "https://www.cftc.gov/dea/newcot/f_disagg.txt",
}

# ── Column positions (0-indexed, verified against live CFTC files) ─────────────
# Legacy futures (deafut.txt)
L_MARKET   = 0
L_DATE     = 2   # YYYY-MM-DD
L_OI       = 7
L_NC_L     = 8   # Non-Commercial Long (large speculators)
L_NC_S     = 9   # Non-Commercial Short
L_C_L      = 11  # Commercial Long (hedgers)
L_C_S      = 12  # Commercial Short
L_CHG_NC_L = 38  # Change in Non-Commercial Long
L_CHG_NC_S = 39  # Change in Non-Commercial Short
L_CHG_C_L  = 41  # Change in Commercial Long
L_CHG_C_S  = 42  # Change in Commercial Short

# TFF (FinFutWk.txt)
T_MARKET   = 0
T_DATE     = 2
T_OI       = 7
T_AM_L     = 11  # Asset Manager Long (institutions)
T_AM_S     = 12  # Asset Manager Short
T_LEV_L    = 14  # Leveraged Money Long (hedge funds)
T_LEV_S    = 15  # Leveraged Money Short
T_CHG_AM_L = 28  # Change in AM Long
T_CHG_AM_S = 29  # Change in AM Short
T_CHG_LV_L = 31  # Change in Leveraged Long
T_CHG_LV_S = 32  # Change in Leveraged Short

# Disaggregated (f_disagg.txt)
D_MARKET   = 0
D_DATE     = 2
D_OI       = 7
D_PR_L     = 8   # Producer/Merchant Long
D_PR_S     = 9   # Producer/Merchant Short
D_MM_L     = 14  # Managed Money Long
D_MM_S     = 15  # Managed Money Short
D_CHG_PR_L = 25  # Change in Producer Long
D_CHG_PR_S = 26  # Change in Producer Short
D_CHG_MM_L = 31  # Change in Managed Money Long
D_CHG_MM_S = 32  # Change in Managed Money Short


def _v(row: list, col: int) -> int:
    try:
        return int(str(row[col]).replace(",", "").strip())
    except (IndexError, ValueError):
        return 0


def fetch_rows(url: str, label: str) -> List[list]:
    print(f"  Downloading {label} ...", end=" ", flush=True)
    r = requests.get(url, timeout=60, headers={"User-Agent": "COT-Fetcher/1.0"})
    r.raise_for_status()
    rows = [row for row in csv.reader(io.StringIO(r.text)) if row]
    print(f"{len(rows)} rows")
    return rows


def latest_rows(rows: List[list], date_col: int) -> Tuple[str, List[list]]:
    def _parse(d: str) -> datetime:
        d = d.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(d, fmt)
            except ValueError:
                pass
        return datetime.min

    dates = {row[date_col].strip() for row in rows if len(row) > date_col and row[date_col].strip()}
    if not dates:
        return "", rows
    latest = max(dates, key=_parse)
    return latest, [r for r in rows if len(r) > date_col and r[date_col].strip() == latest]


def save_csv(rows: List[list], name: str, date_str: str) -> Path:
    try:
        stamp = datetime.strptime(date_str.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        try:
            stamp = datetime.strptime(date_str.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            stamp = datetime.now().strftime("%Y-%m-%d")
    year = stamp[:4]
    # data/YYYY/report_type/cot_type_YYYY-MM-DD.csv
    path = DATA_DIR / year / name / f"cot_{name}_{stamp}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return path


W = 86

def _s(n: int) -> str:
    return "+" if n >= 0 else ""


def print_legacy_summary(rows: List[list], date_str: str):
    print(f"\n{'━'*W}")
    print(f"  COT LEGACY FUTURES  —  {date_str}")
    print(f"  Net Spec = Non-Commercial (large speculators) | Net Comm = Commercial (hedgers)")
    print(f"{'━'*W}")
    print(f"{'Market':<46} {'Net Spec':>11} {'Chg Spec':>10} {'Net Comm':>11} {'Open Int':>10}")
    print(f"{'─'*46} {'─'*11} {'─'*10} {'─'*11} {'─'*10}")

    results = []
    for row in rows:
        market   = row[L_MARKET].strip().strip('"')
        oi       = _v(row, L_OI)
        net_spec = _v(row, L_NC_L) - _v(row, L_NC_S)
        net_comm = _v(row, L_C_L)  - _v(row, L_C_S)
        chg_spec = _v(row, L_CHG_NC_L) - _v(row, L_CHG_NC_S)
        results.append((market, net_spec, chg_spec, net_comm, oi))

    for market, net_spec, chg_spec, net_comm, oi in sorted(results, key=lambda x: x[4], reverse=True):
        print(f"{market[:46]:<46} {net_spec:>+11,} {_s(chg_spec)}{chg_spec:>9,} {net_comm:>+11,} {oi:>10,}")


def print_tff_summary(rows: List[list], date_str: str):
    print(f"\n{'━'*W}")
    print(f"  TRADERS IN FINANCIAL FUTURES (TFF)  —  {date_str}")
    print(f"  Lev = Leveraged Money (hedge funds) | AM = Asset Manager / Institutional")
    print(f"{'━'*W}")
    print(f"{'Market':<46} {'Lev Net':>10} {'Chg Lev':>9} {'AM Net':>10} {'Chg AM':>9}")
    print(f"{'─'*46} {'─'*10} {'─'*9} {'─'*10} {'─'*9}")

    results = []
    for row in rows:
        market  = row[T_MARKET].strip().strip('"')
        oi      = _v(row, T_OI)
        net_lev = _v(row, T_LEV_L) - _v(row, T_LEV_S)
        net_am  = _v(row, T_AM_L)  - _v(row, T_AM_S)
        chg_lev = _v(row, T_CHG_LV_L) - _v(row, T_CHG_LV_S)
        chg_am  = _v(row, T_CHG_AM_L) - _v(row, T_CHG_AM_S)
        results.append((market, net_lev, chg_lev, net_am, chg_am, oi))

    for market, net_lev, chg_lev, net_am, chg_am, _ in sorted(results, key=lambda x: x[5], reverse=True):
        print(f"{market[:46]:<46} {net_lev:>+10,} {_s(chg_lev)}{chg_lev:>8,} {net_am:>+10,} {_s(chg_am)}{chg_am:>8,}")


def print_disagg_summary(rows: List[list], date_str: str):
    print(f"\n{'━'*W}")
    print(f"  DISAGGREGATED FUTURES  —  {date_str}")
    print(f"  MM = Managed Money (speculators) | Prod = Producer/Merchant (commercials)")
    print(f"{'━'*W}")
    print(f"{'Market':<46} {'MM Net':>10} {'Chg MM':>9} {'Prod Net':>10} {'Chg Prod':>9}")
    print(f"{'─'*46} {'─'*10} {'─'*9} {'─'*10} {'─'*9}")

    results = []
    for row in rows:
        market   = row[D_MARKET].strip().strip('"')
        oi       = _v(row, D_OI)
        net_mm   = _v(row, D_MM_L)  - _v(row, D_MM_S)
        net_prod = _v(row, D_PR_L)  - _v(row, D_PR_S)
        chg_mm   = _v(row, D_CHG_MM_L) - _v(row, D_CHG_MM_S)
        chg_prod = _v(row, D_CHG_PR_L) - _v(row, D_CHG_PR_S)
        results.append((market, net_mm, chg_mm, net_prod, chg_prod, oi))

    for market, net_mm, chg_mm, net_prod, chg_prod, _ in sorted(results, key=lambda x: x[5], reverse=True):
        print(f"{market[:46]:<46} {net_mm:>+10,} {_s(chg_mm)}{chg_mm:>8,} {net_prod:>+10,} {_s(chg_prod)}{chg_prod:>8,}")


def build_gdrive_json(tff_latest: List[list], tff_date: str,
                      disagg_latest: List[list]) -> dict:
    """Build the compact JSON summary written to Google Drive for the Claude routine."""
    TFF_TARGETS = [
        ("BITCOIN - CHICAGO MERCANTILE EXCHANGE",            "BTC"),
        ("ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE", "ETH"),
        ("EURO FX - CHICAGO MERCANTILE EXCHANGE",            "EUR"),
        ("JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",       "JPY"),
        ("BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",      "GBP"),
        ("AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",  "AUD"),
        ("CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",    "CAD"),
        ("SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",        "CHF"),
    ]
    DISAGG_TARGETS = [
        ("GOLD - COMMODITY EXCHANGE INC.",   "GOLD"),
        ("SILVER - COMMODITY EXCHANGE INC.", "SILVER"),
    ]

    tff_map = {r[T_MARKET].strip().strip('"'): r for r in tff_latest}
    disagg_map = {r[D_MARKET].strip().strip('"'): r for r in disagg_latest}

    summary: dict = {"report_date": tff_date, "generated_at": datetime.utcnow().isoformat() + "Z", "tff": {}, "disagg": {}}

    for full, short in TFF_TARGETS:
        row = tff_map.get(full)
        if not row:
            continue
        summary["tff"][short] = {
            "oi":      _v(row, T_OI),
            "lev_net": _v(row, T_LEV_L) - _v(row, T_LEV_S),
            "lev_chg": _v(row, T_CHG_LV_L) - _v(row, T_CHG_LV_S),
            "am_net":  _v(row, T_AM_L) - _v(row, T_AM_S),
            "am_chg":  _v(row, T_CHG_AM_L) - _v(row, T_CHG_AM_S),
        }

    for full, short in DISAGG_TARGETS:
        row = disagg_map.get(full)
        if not row:
            continue
        summary["disagg"][short] = {
            "oi":       _v(row, D_OI),
            "mm_net":   _v(row, D_MM_L) - _v(row, D_MM_S),
            "mm_chg":   _v(row, D_CHG_MM_L) - _v(row, D_CHG_MM_S),
            "prod_net": _v(row, D_PR_L) - _v(row, D_PR_S),
            "prod_chg": _v(row, D_CHG_PR_L) - _v(row, D_CHG_PR_S),
        }

    return summary


def save_gdrive_json(summary: dict) -> None:
    """Write cot_summary.json to the Google Drive COT folder so the Claude routine can read it."""
    if not GDRIVE_COT.exists():
        print(f"  WARN: Google Drive COT folder not found at {GDRIVE_COT}, skipping Drive export.")
        return
    path = GDRIVE_COT / "cot_summary.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"  Google Drive  ->  {path}")


def main():
    print(f"\n{'━'*W}")
    print(f"  COT Report Fetcher  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'━'*W}\n")

    saved = []
    tff_latest, tff_date_str, disagg_latest = [], "", []

    print("[1/3] Legacy Futures (all commodity + financial markets)")
    try:
        rows = fetch_rows(COT_URLS["legacy"], "Legacy Futures")
        date_str, latest = latest_rows(rows, L_DATE)
        if latest:
            f = save_csv(latest, "legacy", date_str)
            saved.append(f)
            print(f"  Report date: {date_str}  |  {len(latest)} markets  ->  {f.name}")
            print_legacy_summary(latest, date_str)
    except Exception as e:
        print(f"  ERROR: {e}")

    print("\n[2/3] Traders in Financial Futures (TFF)")
    try:
        rows = fetch_rows(COT_URLS["tff"], "TFF Futures")
        tff_date_str, tff_latest = latest_rows(rows, T_DATE)
        if tff_latest:
            f = save_csv(tff_latest, "tff", tff_date_str)
            saved.append(f)
            print(f"  Report date: {tff_date_str}  |  {len(tff_latest)} markets  ->  {f.name}")
            print_tff_summary(tff_latest, tff_date_str)
    except Exception as e:
        print(f"  ERROR: {e}")

    print("\n[3/3] Disaggregated Futures (metals, energy, agriculture)")
    try:
        rows = fetch_rows(COT_URLS["disagg"], "Disaggregated Futures")
        date_str, disagg_latest = latest_rows(rows, D_DATE)
        if disagg_latest:
            f = save_csv(disagg_latest, "disagg", date_str)
            saved.append(f)
            print(f"  Report date: {date_str}  |  {len(disagg_latest)} markets  ->  {f.name}")
            print_disagg_summary(disagg_latest, date_str)
    except Exception as e:
        print(f"  ERROR: {e}")

    # Write compact JSON to Google Drive for the Claude routine to read
    if tff_latest and disagg_latest:
        print(f"\n[+] Writing summary JSON to Google Drive ...")
        summary = build_gdrive_json(tff_latest, tff_date_str, disagg_latest)
        save_gdrive_json(summary)

    print(f"\n{'━'*W}")
    print(f"  Done. {len(saved)} file(s) saved to: {DATA_DIR}/")
    for f in saved:
        print(f"    {f.name}")
    print()


if __name__ == "__main__":
    main()
