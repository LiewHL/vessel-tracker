"""Port visits from Global Fishing Watch (satellite + terrestrial AIS, a few days behind), turned into position rows
that fill the gaps in the tracker's own AIS log. Fetched once a day; stored locked in the vault."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, haversine_nm, iso, now_utc, parse_iso, read_json, read_positions, roster_rows, write_json

OUT = os.path.join(DATA_DIR, "gfw.json")
API = "https://gateway.api.globalfishingwatch.org/v3"
EVERY_H = 20
MAX_DAYS = 400
MIN_CONF = 3
STEP_H = 24
NEAR_AIS_NM = 20
NEAR_AIS_H = 6
VERSION = 2


def gtime(t):
    """GFW times look like 2026-11-10T02:13:00.000Z; return an aware UTC datetime or None."""
    if not t:
        return None
    try:
        d = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)


def call(path, params, token):
    url = API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                                               "User-Agent": "voyage-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def vessel_ids(mmsi, token):
    d = call("/vessels/search", {"query": mmsi, "datasets[0]": "public-global-vessel-identity:latest"}, token)
    ids = []
    for e in d.get("entries") or []:
        for s in e.get("selfReportedInfo") or []:
            if str(s.get("ssvid")) == mmsi and s.get("id") and s["id"] not in ids:
                ids.append(s["id"])
    return ids


def port_visits(ids, start, end, token):
    out, offset = [], 0
    while True:
        p = {"datasets[0]": "public-global-port-visits-events:latest", "start-date": start, "end-date": end,
             "limit": 100, "offset": offset}
        p.update({f"vessels[{i}]": v for i, v in enumerate(ids)})
        d = call("/events", p, token)
        ent = d.get("entries") or []
        out += ent
        nxt = d.get("nextOffset")
        if not ent or nxt in (None, "", offset) or len(out) >= 2000:
            return out
        offset = nxt


def _conf(e):
    try:
        return int((e.get("port_visit") or {}).get("confidence") or e.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0


def windows(today):
    """MMSI → list of (code, vessel_name, start, end) periods worth fetching."""
    out = {}
    floor = today - timedelta(days=MAX_DAYS)
    for r in roster_rows():
        m = (r.get("mmsi") or "").strip()
        try:
            s = date.fromisoformat((r.get("start_date") or "").strip())
        except ValueError:
            continue
        e_txt = (r.get("end_date") or "").strip()
        try:
            e = date.fromisoformat(e_txt) if e_txt else today
        except ValueError:
            e = today
        if not m.isdigit() or s > today or e < floor:
            continue
        out.setdefault(m, []).append((r.get("id", "").strip(), r.get("vessel_name", "").strip(), max(s, floor), min(e, today)))
    return out


def ais_index():
    by = {}
    for p in read_positions():
        t = parse_iso(p.get("ais_time_utc"))
        try:
            by.setdefault(p.get("id", ""), []).append((t, float(p["latitude"]), float(p["longitude"])))
        except (KeyError, TypeError, ValueError):
            continue
    return by


def heard(ais, code, s, e, lat, lon):
    lo, hi = s - timedelta(hours=NEAR_AIS_H), e + timedelta(hours=NEAR_AIS_H)
    return any(t and lo <= t <= hi and haversine_nm(lat, lon, a, o) <= NEAR_AIS_NM for t, a, o in ais.get(code, ()))


def rows_for(visit, code, name, mmsi):
    pos = visit.get("position") or {}
    pv = visit.get("port_visit") or {}
    anch = pv.get("startAnchorage") or pv.get("endAnchorage") or {}
    lat, lon = pos.get("lat", anch.get("lat")), pos.get("lon", anch.get("lon"))
    s, e = gtime(visit.get("start")), gtime(visit.get("end"))
    if lat is None or lon is None or not s:
        return [], None
    e = e or s
    status = "Moored" if anch.get("atDock") else "At anchor"
    times, t = [s], s + timedelta(hours=STEP_H)
    while t < e:
        times.append(t)
        t += timedelta(hours=STEP_H)
    if e > s:
        times.append(e)
    rows = [{"id": code, "vessel_name": name, "mmsi": mmsi, "latitude": round(float(lat), 4), "longitude": round(float(lon), 4),
             "ais_time_utc": iso(x), "speed_kn": "0", "nav_status": status, "destination": "", "src": "gfw",
             "port": anch.get("name", "")} for x in times]
    return rows, (s, e, float(lat), float(lon))


def main(force=False):
    token = os.environ.get("GFW_TOKEN", "").strip()
    now = now_utc()
    old = read_json(OUT, {})
    prev = parse_iso(old.get("t"))
    if not token:
        print("Port visits (GFW): token not set.")
        return 0
    if not force and prev and old.get("v") == VERSION and now - prev < timedelta(hours=EVERY_H):
        return 0
    today = now.date()
    ais = ais_index()
    rows, n_vis, n_kept, failed = [], 0, 0, 0
    for mmsi, per in windows(today).items():
        try:
            ids = vessel_ids(mmsi, token)
            if not ids:
                continue
            visits = port_visits(ids, min(p[2] for p in per).isoformat(), (today + timedelta(days=1)).isoformat(), token)
        except (urllib.error.URLError, OSError, ValueError):
            failed += 1
            continue
        for v in visits:
            if _conf(v) < MIN_CONF:
                continue
            n_vis += 1
            s = gtime(v.get("start"))
            if not s:
                continue
            for code, name, ps, pe in per:
                if not (ps <= s.date() <= pe):
                    continue
                r, span = rows_for(v, code, name, mmsi)
                if not r or heard(ais, code, *span):
                    continue
                rows += r
                n_kept += 1
    if failed and not rows and old.get("rows"):
        print(f"Port visits (GFW): not updated ({failed} ship(s) failed); keeping the previous data.")
        return 0
    rows.sort(key=lambda r: (r["id"], r["ais_time_utc"]))
    write_json(OUT, {"t": iso(now), "v": VERSION, "source": "Global Fishing Watch", "rows": rows})
    print(f"Port visits (GFW): {n_vis} visit(s) found, {n_kept} added where our own AIS had no record"
          + (f"; {failed} ship(s) failed" if failed else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
