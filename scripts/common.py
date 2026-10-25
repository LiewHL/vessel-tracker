"""Shared helpers for the vessel tracker scripts."""
import csv
import json
import math
import os
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROSTER = os.path.join(ROOT, "vessels.csv")
DATA_DIR = os.path.join(ROOT, "data")
POSITIONS = os.path.join(DATA_DIR, "positions.csv")
LATEST = os.path.join(DATA_DIR, "latest.json")
RUN_LOG = os.path.join(DATA_DIR, "run_log.json")
STATUS = os.path.join(DATA_DIR, "status.json")      # public run health: counts only
REPORTS_DIR = os.path.join(ROOT, "reports")
REPORT_INDEX = os.path.join(REPORTS_DIR, "index.json")

POSITION_FIELDS = [
    "logged_at_utc", "id", "vessel_name", "mmsi", "latitude", "longitude",
    "speed_kn", "course_deg", "nav_status", "destination", "ais_time_utc",
]

NAV_STATUS = {
    0: "Under way (engine)", 1: "At anchor", 2: "Not under command",
    3: "Restricted manoeuvrability", 4: "Constrained by draught", 5: "Moored",
    6: "Aground", 7: "Fishing", 8: "Under way (sailing)", 15: "Not defined",
}


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def clean_digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


REQUIRED_DAYS = 182      # 26 weeks on board


def _date(s):
    try:
        return date.fromisoformat(s or "")
    except ValueError:
        return None


def roster_rows():
    """Every row of vessels.csv as written (one row per stint), cleaned."""
    rows = []
    with open(ROSTER, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("id"):
                continue
            row["mmsi"] = clean_digits(row.get("mmsi"))
            row["imo"] = clean_digits(row.get("imo"))
            row["standby"] = not row["mmsi"] and not row["imo"]
            rows.append(row)
    return rows


def period_info(stints, today):
    """Time on board across stints (sign-on start_date -> sign-off end_date; blank end = still on board).

    Returns {"status": onboard|paused|upcoming|completed|nodates, "days": days on board so far,
    "expected_end": date or None, "paused_since": date or None, "next_start": date or None}."""
    dated = [s for s in stints if s["start"]]
    info = {"status": "nodates", "days": 0, "expected_end": None, "paused_since": None, "next_start": None}
    if not dated:
        return info
    started = [s for s in dated if s["start"] <= today]
    future = [s for s in dated if s["start"] > today]
    info["next_start"] = future[0]["start"] if future else None
    days = 0
    for s in started:
        stop = min(s["end"], today) if s["end"] else today
        if stop >= s["start"]:
            days += (stop - s["start"]).days + 1
    info["days"] = days
    cur = started[-1] if started else None
    if days >= REQUIRED_DAYS:
        info["status"] = "completed"
    elif cur is None:
        info["status"] = "upcoming"
    elif cur["end"] is None or cur["end"] >= today:
        info["status"] = "onboard"
        # 26 weeks after sign-on, pushed back by any days spent signed off
        info["expected_end"] = today + timedelta(days=REQUIRED_DAYS - days + 1)
    else:
        info["status"] = "paused"
        info["paused_since"] = cur["end"]
    if info["status"] in ("paused", "upcoming") and info["next_start"]:
        before = days
        info["expected_end"] = info["next_start"] + timedelta(days=REQUIRED_DAYS - before)
    return info


def load_roster(include_standby=False, today=None):
    """One entry per ID from vessels.csv (rows sharing an ID are stints: sign-off and sign-on again,
    possibly on another vessel). Vessel details come from the current stint (the latest one that has
    started, else the first). Each entry has "stints" and "period" (see period_info).

    Places with neither MMSI nor IMO are standby (no vessel assigned yet). They are left out unless
    include_standby is True; then each entry has "standby": True/False."""
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    by_id = {}
    for row in roster_rows():
        by_id.setdefault(row["id"], []).append(row)
    out = []
    for vid, rows in by_id.items():
        stints = [{"start": _date(r.get("start_date")), "end": _date(r.get("end_date")), "row": r} for r in rows]
        stints.sort(key=lambda s: (s["start"] is None, s["start"] or date.max))
        started = [s for s in stints if s["start"] and s["start"] <= today]
        cur = (started[-1] if started else stints[0])["row"]
        v = dict(cur)
        v["stints"] = [{"start": s["start"], "end": s["end"], "vessel_name": s["row"].get("vessel_name", ""),
                        "imo": s["row"]["imo"], "mmsi": s["row"]["mmsi"]} for s in stints]
        v["period"] = period_info(v["stints"], today)
        firsts = [s["start"] for s in stints if s["start"]]
        v["start_date"] = firsts[0].isoformat() if firsts else ""
        v["end_date"] = v["period"]["expected_end"].isoformat() if v["period"]["expected_end"] else (cur.get("end_date") or "")
        if v["standby"] and not include_standby:
            continue
        out.append(v)
    return out


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_positions():
    try:
        with open(POSITIONS, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def append_positions(rows):
    os.makedirs(DATA_DIR, exist_ok=True)
    new_file = not os.path.exists(POSITIONS) or os.path.getsize(POSITIONS) == 0
    with open(POSITIONS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=POSITION_FIELDS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def haversine_nm(lat1, lon1, lat2, lon2):
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_nm * math.asin(math.sqrt(a))


def freshness(last_seen, ref=None):
    """Classify how old the last position is: fresh / stale / old / none."""
    if not last_seen:
        return "none"
    ref = ref or now_utc()
    age_h = (ref - last_seen).total_seconds() / 3600
    if age_h <= 72:
        return "fresh"
    if age_h <= 24 * 7:
        return "stale"
    return "old"


# ---------------------------------------------------------------------------
# Nearest port lookup (World Port Index, see assets/ports.json)
PORTS_FILE = os.path.join(ROOT, "assets", "ports.json")
_PORTS = None
NEAR_NM = 30          # within this distance a position counts as "at/near" a port
DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _ports():
    global _PORTS
    if _PORTS is None:
        _PORTS = read_json(PORTS_FILE, {}).get("ports", [])
    return _PORTS


def nearest_port(lat, lon):
    """Return (name, country, distance_nm, direction_from_port) or None."""
    best = None
    coslat = math.cos(math.radians(lat))
    for name, country, plat, plon in _ports():
        dlon = (plon - lon + 540) % 360 - 180
        rough = (plat - lat) ** 2 + (dlon * coslat) ** 2   # quick pre-filter in degrees
        if best is None or rough < best[0]:
            best = (rough, name, country, plat, plon)
    if best is None:
        return None
    _, name, country, plat, plon = best
    dist = haversine_nm(plat, plon, lat, lon)
    y = math.sin(math.radians(lon - plon)) * math.cos(math.radians(lat))
    x = (math.cos(math.radians(plat)) * math.sin(math.radians(lat))
         - math.sin(math.radians(plat)) * math.cos(math.radians(lat)) * math.cos(math.radians(lon - plon)))
    brg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return name, country, dist, DIRS[int((brg + 22.5) // 45) % 8]


def _where(name, country):
    return f"{name}, {country}" if country and country.lower() != name.lower() else name


def place_label(lat, lon):
    """Plain-language place, e.g. 'At Keppel, Singapore' or 'At sea, 240 nm SW of Colombo'."""
    np_ = nearest_port(lat, lon)
    if not np_:
        return ""
    name, country, dist, direction = np_
    where = _where(name, country)
    if dist <= 3:
        return f"At {where}"
    if dist <= NEAR_NM:
        return f"{dist:.0f} nm {direction} of {where}"
    return f"At sea, {dist:.0f} nm {direction} of {where}"


def places_visited(fixes):
    """Ports a list of fixes came within NEAR_NM of, in order of first visit."""
    seen, out = set(), []
    for f in fixes:
        np_ = nearest_port(f["lat"], f["lon"])
        if np_ and np_[2] <= NEAR_NM:
            key = _where(np_[0], np_[1])
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out
