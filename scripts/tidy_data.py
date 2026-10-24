"""Remove ships that are no longer in vessels.csv from all logged data, and apply ID changes.

  python scripts/tidy_data.py "OLD=NEW,OLD=NEW,..."

Run inside the "Tidy data" workflow (the data is unlocked there). Positions and last positions
are matched by MMSI, so they always take the ID and name now in vessels.csv. Run records keep only
IDs listed in the mapping (renamed). Prints counts only.
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, LATEST, POSITIONS, RUN_LOG, load_roster, read_json, write_json  # noqa: E402


def main():
    mapping = dict(p.split("=", 1) for p in (sys.argv[1] if len(sys.argv) > 1 else "").replace(" ", "").split(",") if "=" in p)
    by_mmsi = {v["mmsi"]: v for v in load_roster() if v["mmsi"]}

    with open(POSITIONS, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    kept = []
    for r in rows:
        v = by_mmsi.get(r["mmsi"])
        if v:
            r["id"], r["vessel_name"] = v["id"], v["vessel_name"]
            kept.append(r)
    with open(POSITIONS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(kept)

    latest = {}
    for info in read_json(LATEST, {}).values():
        v = by_mmsi.get(str(info.get("mmsi", "")))
        if v:
            info.update(id=v["id"], vessel_name=v["vessel_name"], imo=v["imo"])
            latest[v["id"]] = info
    write_json(LATEST, latest)

    log = read_json(RUN_LOG, {})
    for e in log.get("history", []):
        e["heard_ids"] = [mapping[i] for i in e.get("heard_ids", []) if i in mapping]
        e["vessels_heard"] = len(e["heard_ids"])
    write_json(RUN_LOG, log)

    state_path = os.path.join(DATA_DIR, "alerts_state.json")
    state = read_json(state_path, None)
    if state is not None:
        write_json(state_path, {mapping[k]: v for k, v in state.items() if k in mapping})
    log_path = os.path.join(DATA_DIR, "alerts_log.json")
    alog = read_json(log_path, None)
    if alog is not None:
        for a in alog:
            old = a.get("ship", "")
            if old in mapping and mapping[old] != old:
                a["text"] = re.sub(rf"\b{re.escape(old)}\b(?!-)", mapping[old], a.get("text", ""), count=1)
                a["ship"] = mapping[old]
        write_json(log_path, [a for a in alog if a.get("ship") in mapping.values()])

    print(f"Positions kept {len(kept)} of {len(rows)}; last positions kept {len(latest)}; "
          f"{len(log.get('history', []))} run records updated.")


if __name__ == "__main__":
    main()
