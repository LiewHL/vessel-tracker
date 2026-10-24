"""Check vessels.csv for mistakes that would stop a ship being tracked.

Exit 0 if fine, 1 if problems were found (emailed to the private list when --email is given).
Run logs show the number of problems only.
"""
import csv
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROSTER  # noqa: E402
from insights import flag_of  # noqa: E402

REQUIRED = ["id", "vessel_name", "imo", "mmsi"]


def imo_ok(imo):
    if not re.fullmatch(r"\d{7}", imo):
        return False
    d = [int(c) for c in imo]
    return sum(d[i] * (7 - i) for i in range(6)) % 10 == d[6]


def check(path=ROSTER):
    problems, warnings = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = [c.strip() for c in reader.fieldnames or []]
        for c in REQUIRED:
            if c not in cols:
                problems.append(f"Header: column '{c}' is missing (first line of vessels.csv).")
        ids = {}
        for n, raw in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            if not any(row.values()):
                continue
            vid = row.get("id", "")
            who = f"Line {n} ({vid or 'no ID'} {row.get('vessel_name', '')})".strip()
            if not vid:
                problems.append(f"{who}: ID is empty.")
            elif vid in ids:
                problems.append(f"{who}: ID {vid} is also used on line {ids[vid]}.")
            else:
                ids[vid] = n
            mmsi, imo = re.sub(r"\D", "", row.get("mmsi", "")), re.sub(r"\D", "", row.get("imo", ""))
            if len(mmsi) != 9:
                problems.append(f"{who}: MMSI '{row.get('mmsi', '')}' must be 9 digits (needed for logging).")
            elif not flag_of(mmsi):
                warnings.append(f"{who}: MMSI {mmsi} does not start with a known country code; please double-check it.")
            if imo and not imo_ok(imo):
                problems.append(f"{who}: IMO {imo} is not a valid IMO number (check digit wrong); the live map will not work.")
            elif not imo:
                warnings.append(f"{who}: no IMO number (the live VesselFinder map needs it).")
            s, e = row.get("start_date", ""), row.get("end_date", "")
            ds = de = None
            for label, val in (("start_date", s), ("end_date", e)):
                if val:
                    try:
                        d = date.fromisoformat(val)
                        ds, de = (d, de) if label == "start_date" else (ds, d)
                    except ValueError:
                        problems.append(f"{who}: {label} '{val}' must be written as YYYY-MM-DD.")
            if ds and de and de < ds:
                problems.append(f"{who}: end_date is before start_date.")
    return problems, warnings


def main():
    problems, warnings = check()
    if "--email" in sys.argv and (problems or warnings):
        import notify
        body = []
        if problems:
            body += ["Problems (fix these in vessels.csv):", *[f"- {p}" for p in problems], ""]
        if warnings:
            body += ["Worth checking:", *[f"- {w}" for w in warnings], ""]
        body.append("Edit vessels.csv on GitHub (pencil icon), then save. This check runs again automatically.")
        notify.send(f"Vessel list check: {len(problems)} problem(s), {len(warnings)} to check", "\n".join(body))
    print(f"vessels.csv: {len(problems)} problem(s), {len(warnings)} warning(s).")
    if problems and os.environ.get("GITHUB_ACTIONS"):
        print(f"::error::vessels.csv has {len(problems)} problem(s); details were emailed.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
