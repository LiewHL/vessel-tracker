"""Alerts after each log run: risk areas, nearby tropical storms, ships gone quiet.

Run inside the logger workflow while the data is unlocked. Sends one email per run that has
something new (to the private EMAIL_TO list) and records each alert in data/alerts_log.json
(locked) for the reports. Public run logs show counts only.

Rules
  Risk areas  config/risk_areas.json (editable). Alert on entering an area; alert on leaving once
              the ship has been heard outside it on 2 runs in a row (avoids flip-flopping at edges).
  Storms      current tropical cyclones from GDACS (gdacs.org); alert once per storm when a ship
              heard in the last 72 h is within storm_distance_nm (default 300 nm) of the storm.
  Gone quiet  not heard for 7 days although its last position was within 30 nm of a port
              (where coverage is normally good); a follow-up when it is heard again.
Only ships inside their tracking period (or without dates) are checked.
"""
import json
import os
import sys
import urllib.request
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    DATA_DIR, LATEST, NEAR_NM, haversine_nm, iso, load_roster, nearest_port, now_utc, parse_iso,
    place_label, read_json, write_json,
)
from insights import SGT, active_in, areas_at, load_areas  # noqa: E402
import notify  # noqa: E402

STATE = os.path.join(DATA_DIR, "alerts_state.json")
LOG = os.path.join(DATA_DIR, "alerts_log.json")
QUIET_DAYS = 7
GDACS_URL = ("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
             "?eventlist=TC&alertlevel=Green;Orange;Red")


def fetch_storms():
    """Current tropical cyclones: [{"id", "name", "level", "lat", "lon", "url"}]. [] if unavailable."""
    try:
        req = urllib.request.Request(GDACS_URL, headers={"User-Agent": "vessel-tracker/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.load(r)
    except Exception as exc:
        print(f"Storm check skipped (GDACS unavailable: {type(exc).__name__}).")
        return None
    out = []
    for f in data.get("features", []):
        p = f.get("properties") or {}
        if str(p.get("iscurrent", "")).lower() != "true":
            continue
        try:
            lon, lat = (float(c) for c in (f.get("geometry") or {}).get("coordinates", [])[:2])
        except (TypeError, ValueError):
            continue
        eid = p.get("eventid")
        out.append({"id": str(eid), "name": p.get("eventname") or p.get("name") or "Tropical cyclone",
                    "level": p.get("alertlevel", ""), "lat": lat, "lon": lon,
                    "url": f"https://www.gdacs.org/report.aspx?eventtype=TC&eventid={eid}"})
    return out


def sgt(dt):
    return dt.astimezone(SGT).strftime("%d %b %H:%M SGT")


def main():
    now = now_utc()
    today = now.astimezone(SGT).date()
    roster = [v for v in load_roster() if active_in(v, today, today)]
    latest = read_json(LATEST, {})
    state = read_json(STATE, {})
    log = read_json(LOG, [])
    areas, cfg = load_areas()
    storm_nm = float(cfg.get("storm_distance_nm", 300))
    storms = fetch_storms()
    alerts = []   # (kind, ship, text)

    for v in roster:
        s = state.setdefault(v["id"], {"areas": [], "out": {}, "quiet": False, "storms": {}, "seen": ""})
        q = latest.get(v["id"]) or {}
        seen = parse_iso(q.get("last_seen_utc"))
        lat, lon = q.get("latitude"), q.get("longitude")
        if seen is None or lat is None or lon is None:
            continue
        where = place_label(lat, lon) or f"{lat:.3f}, {lon:.3f}"
        name = f"{v['id']} {v['vessel_name']}"
        new_fix = q.get("last_seen_utc") != s.get("seen")

        # --- risk areas (only on a new position) ---
        if new_fix:
            now_in = set(areas_at(lat, lon, areas))
            before = set(s.get("areas", []))
            for a in sorted(now_in - before):
                alerts.append(("Entered risk area", name, f"{name} entered {a}. Position {where}, {sgt(seen)}."))
            kept = set()
            for a in before:
                if a in now_in:
                    s["out"].pop(a, None)
                    kept.add(a)
                    continue
                s["out"][a] = s["out"].get(a, 0) + 1
                if s["out"][a] >= 2:
                    s["out"].pop(a, None)
                    alerts.append(("Left risk area", name, f"{name} has left {a}. Position {where}, {sgt(seen)}."))
                else:
                    kept.add(a)
            s["areas"] = sorted(kept | now_in)

        # --- gone quiet / back in contact ---
        age_days = (now - seen).total_seconds() / 86400
        np_ = nearest_port(lat, lon)
        covered = bool(np_ and np_[2] <= NEAR_NM)
        if age_days >= QUIET_DAYS and covered and not s.get("quiet"):
            s["quiet"] = True
            alerts.append(("Gone quiet", name, f"{name} has not been heard for {int(age_days)} days. "
                           f"Last position {where}, {sgt(seen)} (normally good coverage there)."))
        elif age_days < QUIET_DAYS and s.get("quiet"):
            s["quiet"] = False
            alerts.append(("Back in contact", name, f"{name} is being heard again. Position {where}, {sgt(seen)}."))

        # --- storms ---
        if storms and age_days <= 3:
            for st in storms:
                d = haversine_nm(lat, lon, st["lat"], st["lon"])
                if d <= storm_nm and st["id"] not in s["storms"]:
                    s["storms"][st["id"]] = iso(now)
                    lvl = f" ({st['level']} alert)" if st["level"] else ""
                    alerts.append(("Storm nearby", name, f"{name} is about {d:.0f} nm from tropical cyclone "
                                   f"{st['name']}{lvl}. Ship position {where}, {sgt(seen)}. Details: {st['url']}"))
        # forget storms older than 30 days
        s["storms"] = {k: t for k, t in s["storms"].items()
                       if (parse_iso(t) or now) > now - timedelta(days=30)}
        s["seen"] = q.get("last_seen_utc")

    write_json(STATE, state)
    if alerts:
        for kind, ship, text in alerts:
            log.append({"t": iso(now), "kind": kind, "ship": ship.split(" ")[0], "text": text})
        write_json(LOG, log[-2000:])
        order = ["Entered risk area", "Storm nearby", "Gone quiet", "Left risk area", "Back in contact"]
        lines = []
        for kind in order + sorted({k for k, _, _ in alerts} - set(order)):
            items = [t for k, _, t in alerts if k == kind]
            if items:
                lines += [kind.upper(), *[f"- {t}" for t in items], ""]
        lines += [f"Risk area list last updated {cfg.get('updated', '?')} (config/risk_areas.json).",
                  "Positions come from shore-based AIS and may be delayed. Check the dashboard for the latest."]
        first = alerts[0]
        subject = (f"Vessel alert: {first[0].lower()} - {first[1]}" if len(alerts) == 1
                   else f"Vessel alerts: {len(alerts)} new")
        notify.send(subject, "\n".join(lines))
    print(f"Alerts: {len(alerts)} new; storms checked: {'no' if storms is None else len(storms)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
