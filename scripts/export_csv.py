"""CSV files sent with the report emails.

  python scripts/export_csv.py weekly  <out_dir>
  python scripts/export_csv.py monthly <out_dir> [YYYY-MM]
  python scripts/export_csv.py quarterly <out_dir> [YYYY-Qn]

Writes four Excel-friendly CSV files (UTF-8 with BOM) and prints their paths:
  positions_<period>.csv     every logged position in the period
  ship_summary_<period>.csv  one row per ship for the period
  port_calls_<period>.csv    port calls / stops detected in the period
  full_history_<date>.csv    every position logged so far
"""
import csv
import os
import sys
from datetime import timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import haversine_nm, load_roster, now_utc, place_label, places_visited, read_positions  # noqa: E402
from weekly_report import period_progress, load_fixes, period_bounds  # noqa: E402
from insights import port_calls  # noqa: E402

SGT = timezone(timedelta(hours=8))


def sgt(dt):
    return dt.astimezone(SGT).strftime("%Y-%m-%d %H:%M") if dt else ""


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def position_rows(fixes_by_id, roster, start=None, end=None):
    by_id = {v["id"]: v for v in roster}
    rows = []
    for vid, fixes in fixes_by_id.items():
        v = by_id.get(vid, {})
        for f in fixes:
            if (start and f["t"] < start) or (end and f["t"] > end):
                continue
            rows.append((f["t"], [
                sgt(f["t"]), vid, v.get("vessel_name", ""), v.get("category", ""),
                place_label(f["lat"], f["lon"]), f["lat"], f["lon"],
                "" if f["speed_kn"] is None else f["speed_kn"], f["nav_status"], f["destination"],
            ]))
    rows.sort(key=lambda r: (r[0], r[1][1]))
    return [r[1] for r in rows]


POS_HEADER = ["Time (SGT)", "ID", "Vessel", "Category", "Place", "Latitude", "Longitude",
              "Speed (kn)", "Status", "Destination (AIS)"]


def main():
    kind, out_dir = sys.argv[1], sys.argv[2]
    month = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
    os.makedirs(out_dir, exist_ok=True)
    ref = now_utc()
    start, end, _period, tag, ndays = period_bounds(kind, ref, month)
    as_of = min(end, ref)
    roster = load_roster()
    fixes = load_fixes(read_positions())
    label = f"{kind}_{tag}"

    paths = [write(os.path.join(out_dir, f"positions_{label}.csv"), POS_HEADER,
                   position_rows(fixes, roster, start, as_of))]

    summary = []
    for v in roster:
        hist = [f for f in fixes.get(v["id"], []) if f["t"] <= as_of]
        period = [f for f in hist if f["t"] >= start]
        last = hist[-1] if hist else None
        dist = sum(haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(period, period[1:]))
        prog, _ = period_progress(v, as_of.astimezone(SGT).date())
        summary.append([
            v["id"], v["vessel_name"], v.get("company", ""), v.get("category", ""), v["imo"], v["mmsi"],
            v.get("start_date", ""), v.get("end_date", ""), prog,
            sgt(last["t"]) if last else "", place_label(last["lat"], last["lon"]) if last else "",
            last["lat"] if last else "", last["lon"] if last else "",
            f"{len({f['t'].astimezone(SGT).date() for f in period})}/{ndays}", len(period), round(dist),
            " -> ".join(places_visited(period)),
        ])
    paths.append(write(os.path.join(out_dir, f"ship_summary_{label}.csv"), [
        "ID", "Vessel", "Company", "Category", "IMO", "MMSI", "First sign-on", "Expected finish (182 days on board)",
        "Progress (days on board)", "Last seen (SGT)", "Last place", "Last latitude", "Last longitude",
        "Days heard", "Positions in period", "Distance logged (nm)", "Places visited (within 30 nm)",
    ], summary))

    calls = []
    for v in roster:
        hist = [f for f in fixes.get(v["id"], []) if f["t"] <= as_of]
        for c in port_calls(hist):
            if c["end"] >= start and c["start"] <= as_of:
                calls.append([v["id"], v["vessel_name"], c["kind"], c["place"], c["country"],
                              sgt(c["start"]), sgt(c["end"]), sgt(c["departed"]), c["hours"],
                              round((c["departed"] - c["start"]).total_seconds() / 3600, 1) if c["departed"] else "",
                              c["lat"], c["lon"]])
    paths.append(write(os.path.join(out_dir, f"port_calls_{label}.csv"), [
        "ID", "Vessel", "Type", "Place", "Country", "First logged stopped (SGT)", "Last logged stopped (SGT)",
        "Logged under way again (SGT)", "Stopped at least (h)", "Stopped at most (h)", "Latitude", "Longitude",
    ], calls))

    paths.append(write(os.path.join(out_dir, f"full_history_to_{ref.astimezone(SGT).date().isoformat()}.csv"),
                       POS_HEADER, position_rows(fixes, roster)))
    print("\n".join(paths))


if __name__ == "__main__":
    main()
