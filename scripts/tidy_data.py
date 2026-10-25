"""Remove ships that are no longer in vessels.csv from all logged data, and apply ID changes.

Records are kept when their ship (MMSI) appears in any stint of the (renamed) ID, so a place's
history on an earlier vessel is kept.

  python scripts/tidy_data.py "OLD=NEW,OLD=NEW,..."

Run inside the "Tidy data" workflow (the data is unlocked there). Positions and last positions
are matched by MMSI, so they always take the ID and name now in vessels.csv. Run records keep only
IDs with a stint on that ship (renamed where mapped). Prints counts only.
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, LATEST, POSITIONS, RUN_LOG, read_json, roster_rows, write_json  # noqa: E402


def main():
    mapping = dict(p.split("=", 1) for p in (sys.argv[1] if len(sys.argv) > 1 else "").replace(" ", "").split(",") if "=" in p)
    # every stint's ship counts, so history on an earlier vessel is kept
    stint_mmsis = {}
    for r in roster_rows():
        if r["mmsi"]:
            stint_mmsis.setdefault(r["id"], {})[r["mmsi"]] = r["vessel_name"]

    def target(old_id, mmsi):
        """New ID for a record of old_id heard on mmsi, or None to drop it."""
        nid = mapping.get(old_id, old_id) if mapping else old_id
        return nid if mmsi in stint_mmsis.get(nid, {}) else None

    with open(POSITIONS, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    kept = []
    for r in rows:
        nid = target(r["id"], r["mmsi"])
        if nid:
            r["id"], r["vessel_name"] = nid, stint_mmsis[nid][r["mmsi"]]
            kept.append(r)
    with open(POSITIONS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(kept)

    latest = {}
    for old_id, info in read_json(LATEST, {}).items():
        nid = target(old_id, str(info.get("mmsi", "")))
        if nid:
            info.update(id=nid, vessel_name=stint_mmsis[nid][str(info.get("mmsi", ""))])
            latest[nid] = info
    write_json(LATEST, latest)

    log = read_json(RUN_LOG, {})
    for e in log.get("history", []):
        e["heard_ids"] = [mapping.get(i, i) for i in e.get("heard_ids", []) if mapping.get(i, i) in stint_mmsis]
        e["vessels_heard"] = len(e["heard_ids"])
    write_json(RUN_LOG, log)

    state_path = os.path.join(DATA_DIR, "alerts_state.json")
    state = read_json(state_path, None)
    if state is not None:
        write_json(state_path, {mapping.get(k, k): v for k, v in state.items() if mapping.get(k, k) in stint_mmsis})
    log_path = os.path.join(DATA_DIR, "alerts_log.json")
    alog = read_json(log_path, None)
    if alog is not None:
        for a in alog:
            old = a.get("ship", "")
            if old in mapping and mapping[old] != old:
                a["text"] = re.sub(rf"\b{re.escape(old)}\b(?!-)", mapping[old], a.get("text", ""), count=1)
                a["ship"] = mapping[old]
        write_json(log_path, [a for a in alog if a.get("ship") in stint_mmsis])

    print(f"Positions kept {len(kept)} of {len(rows)}; last positions kept {len(latest)}; "
          f"{len(log.get('history', []))} run records updated.")


if __name__ == "__main__":
    main()
