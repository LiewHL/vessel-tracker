import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, LATEST, iso, now_utc, parse_iso, read_json, write_json

CRISIS = os.path.join(DATA_DIR, "crisis.json")
WEATHER = os.path.join(DATA_DIR, "weather.json")
GDACS = ("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
         "?eventlist=TC;EQ;TS;VO;FL&alertlevel=Green;Orange;Red")
TYPES = {"TC": "Tropical cyclone", "EQ": "Earthquake", "TS": "Tsunami", "VO": "Volcano", "FL": "Flood"}
MAX_AGE_H = 48


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "vessel-tracker/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def crisis(now):
    try:
        data = get(GDACS)
    except Exception as exc:
        print(f"Crisis events: not updated ({type(exc).__name__}).")
        return
    out = []
    for f in data.get("features", []):
        p = f.get("properties") or {}
        if str(p.get("iscurrent", "")).lower() != "true":
            continue
        t, lvl = p.get("eventtype", ""), p.get("alertlevel", "")
        if t != "TC" and lvl not in ("Orange", "Red"):
            continue
        try:
            lon, lat = (float(c) for c in (f.get("geometry") or {}).get("coordinates", [])[:2])
        except (TypeError, ValueError):
            continue
        eid = p.get("eventid")
        out.append({"type": t, "kind": TYPES.get(t, t), "name": p.get("eventname") or p.get("name") or TYPES.get(t, t),
                    "level": lvl, "lat": lat, "lon": lon, "from": p.get("fromdate", ""), "to": p.get("todate", ""),
                    "country": p.get("country", ""),
                    "url": f"https://www.gdacs.org/report.aspx?eventtype={t}&eventid={eid}"})
    write_json(CRISIS, {"t": iso(now), "events": out})
    print(f"Crisis events: {len(out)} current.")


def weather(now):
    latest = read_json(LATEST, {})
    pts = []
    for vid, q in latest.items():
        seen = parse_iso(q.get("last_seen_utc"))
        lat, lon = q.get("latitude"), q.get("longitude")
        if seen and lat is not None and lon is not None and now - seen <= timedelta(hours=MAX_AGE_H):
            pts.append((vid, round(float(lat), 3), round(float(lon), 3), q.get("last_seen_utc")))
    old = read_json(WEATHER, {}).get("ships", {})
    if not pts:
        write_json(WEATHER, {"t": iso(now), "ships": {}})
        print("Weather: no recent positions.")
        return
    lats = ",".join(str(p[1]) for p in pts)
    lons = ",".join(str(p[2]) for p in pts)
    q = {"latitude": lats, "longitude": lons, "forecast_days": 2, "timezone": "UTC"}
    try:
        wind = get("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(dict(q,
                   current="wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                   hourly="wind_speed_10m,wind_gusts_10m", wind_speed_unit="kn")))
    except Exception as exc:
        print(f"Weather: wind not updated ({type(exc).__name__}).")
        wind = None
    try:
        sea = get("https://marine-api.open-meteo.com/v1/marine?" + urllib.parse.urlencode(dict(q,
                  current="wave_height,wave_direction", hourly="wave_height")))
    except Exception as exc:
        print(f"Weather: waves not updated ({type(exc).__name__}).")
        sea = None
    if wind is None and sea is None:
        return
    as_list = lambda d: d if isinstance(d, list) else ([d] if d else [])
    wind, sea = as_list(wind), as_list(sea)
    end = now + timedelta(hours=24)

    def next24(block, key):
        h = (block or {}).get("hourly") or {}
        vals = []
        for t, v in zip(h.get("time", []), h.get(key, [])):
            ts = parse_iso(t + ":00Z" if len(t) == 16 else t)
            if v is not None and ts and now - timedelta(hours=1) <= ts <= end:
                vals.append(v)
        return max(vals) if vals else None

    ships = {}
    for i, (vid, lat, lon, seen) in enumerate(pts):
        w = wind[i] if i < len(wind) else {}
        s = sea[i] if i < len(sea) else {}
        cw, cs = (w or {}).get("current") or {}, (s or {}).get("current") or {}
        rec = {"at": seen, "lat": lat, "lon": lon,
               "wind_kn": cw.get("wind_speed_10m"), "wind_dir": cw.get("wind_direction_10m"),
               "gust_kn": cw.get("wind_gusts_10m"), "wave_m": cs.get("wave_height"),
               "max24_wind_kn": next24(w, "wind_speed_10m"), "max24_gust_kn": next24(w, "wind_gusts_10m"),
               "max24_wave_m": next24(s, "wave_height")}
        if wind is None and vid in old:
            rec.update({k: old[vid].get(k) for k in ("wind_kn", "wind_dir", "gust_kn", "max24_wind_kn", "max24_gust_kn")})
        ships[vid] = rec
    write_json(WEATHER, {"t": iso(now), "ships": ships})
    print(f"Weather: {len(ships)} ship position(s) updated.")


def main():
    now = now_utc()
    crisis(now)
    weather(now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
