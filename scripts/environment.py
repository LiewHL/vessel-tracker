import base64
import json
import math
import os
import struct
import zlib
import sys
import urllib.parse
import urllib.request
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, LATEST, iso, now_utc, parse_iso, read_json, write_json

CRISIS = os.path.join(DATA_DIR, "crisis.json")
WEATHER = os.path.join(DATA_DIR, "weather.json")
WAVES = os.path.join(DATA_DIR, "waves.json")
WW3 = "https://upwell.pfeg.noaa.gov/erddap/griddap/NWW3_Global_Best.json?Thgt%5B({t})%5D%5B({la0}):2:({la1})%5D%5B(0.0):2:(359.0)%5D"
LAT_MAX = 76.0
GDACS = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventlist={t}&alertlevel={lv}"
TYPES = {"TC": "Tropical cyclone", "EQ": "Earthquake", "TS": "Tsunami", "VO": "Volcano", "FL": "Flood"}
MAX_AGE_H = 48


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "vessel-tracker/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def crisis(now):
    feats, failed, counts = [], 0, {}
    for t in TYPES:
        try:
            data = get(GDACS.format(t=t, lv="Green;Orange;Red" if t == "TC" else "Orange;Red"))
            fs = data.get("features", []) if isinstance(data, dict) else []
            counts[t] = len(fs)
            feats += fs
        except Exception as exc:
            failed += 1
            counts[t] = type(exc).__name__
    if failed == len(TYPES):
        print(f"Crisis events: not updated ({counts}).")
        return
    out = []
    for f in feats:
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
    print(f"Crisis events: {len(out)} current (fetched {counts}).")


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

    h0 = now.replace(minute=0, second=0, microsecond=0)

    def series(block, key):
        h = (block or {}).get("hourly") or {}
        by = {}
        for t, v in zip(h.get("time", []), h.get(key, [])):
            ts = parse_iso(t + ":00Z" if len(t) == 16 else t)
            if ts:
                by[ts] = None if v is None else round(float(v), 1)
        return [by.get(h0 + timedelta(hours=i)) for i in range(48)]

    ships = {}
    for i, (vid, lat, lon, seen) in enumerate(pts):
        w = wind[i] if i < len(wind) else {}
        s = sea[i] if i < len(sea) else {}
        cw, cs = (w or {}).get("current") or {}, (s or {}).get("current") or {}
        rec = {"at": seen, "lat": lat, "lon": lon,
               "wind_kn": cw.get("wind_speed_10m"), "wind_dir": cw.get("wind_direction_10m"),
               "gust_kn": cw.get("wind_gusts_10m"), "wave_m": cs.get("wave_height"),
               "max24_wind_kn": next24(w, "wind_speed_10m"), "max24_gust_kn": next24(w, "wind_gusts_10m"),
               "max24_wave_m": next24(s, "wave_height"),
               "series": {"start": iso(h0), "wave": series(s, "wave_height"), "wind": series(w, "wind_speed_10m"),
                          "gust": series(w, "wind_gusts_10m")}}
        if wind is None and vid in old:
            rec.update({k: old[vid].get(k) for k in ("wind_kn", "wind_dir", "gust_kn", "max24_wind_kn", "max24_gust_kn")})
        ships[vid] = rec
    write_json(WEATHER, {"t": iso(now), "ships": ships})
    print(f"Weather: {len(ships)} ship position(s) updated.")


def _png(w, h, rows):
    raw = b"".join(b"\x00" + r for r in rows)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


RAMP = [(0.0, (198, 233, 247)), (1.0, (120, 198, 230)), (2.0, (65, 160, 210)), (3.0, (90, 190, 120)),
        (4.0, (240, 210, 70)), (5.0, (240, 150, 50)), (6.0, (220, 70, 50)), (8.0, (150, 30, 90)), (12.0, (90, 20, 110))]


def _colour(v):
    for (a, ca), (b, cb) in zip(RAMP, RAMP[1:]):
        if v <= b:
            f = 0 if b == a else max(0.0, (v - a) / (b - a))
            return tuple(round(x + (y - x) * f) for x, y in zip(ca, cb))
    return RAMP[-1][1]


def waves(now):
    """Current wave-height field (NOAA WaveWatch III, 1-degree) as a small Mercator PNG for the map."""
    prev = parse_iso(read_json(WAVES, {}).get("t"))
    if prev and now - prev < timedelta(hours=3) - timedelta(minutes=10):
        return
    t = now.replace(minute=0, second=0, microsecond=0)
    data = None
    for la0, la1 in ((-LAT_MAX, LAT_MAX), (LAT_MAX, -LAT_MAX)):
        for back in (0, 1, 2, 3, 6):
            try:
                data = get(WW3.format(t=(t - timedelta(hours=back)).strftime("%Y-%m-%dT%H:%M:%SZ"), la0=la0, la1=la1), timeout=60)
                break
            except Exception:
                data = None
        if data:
            break
    if not data:
        print("Waves map: not updated.")
        return
    tbl = data.get("table", {})
    cols = tbl.get("columnNames", [])
    try:
        it, ila, ilo, iv = (cols.index(c) for c in ("time", "latitude", "longitude", "Thgt"))
    except ValueError:
        print("Waves map: unexpected format.")
        return
    grid, when = {}, ""
    for r in tbl.get("rows", []):
        if r[iv] is None:
            continue
        lo = float(r[ilo]); lo = lo - 360 if lo >= 180 else lo
        grid[(round(float(r[ila])), round(lo))] = float(r[iv])
        when = r[it]
    if not grid:
        print("Waves map: no data.")
        return
    W = 360
    ymax = math.log(math.tan(math.pi / 4 + math.radians(LAT_MAX) / 2))
    H = round(W * 2 * ymax / (2 * math.pi))
    rows = []
    for j in range(H):
        y = ymax - (j + 0.5) * (2 * ymax / H)
        lat = math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)
        la = round(lat)
        row = bytearray()
        for i in range(W):
            v = grid.get((la, -180 + i)) or grid.get((la, -180 + i + (1 if i % 2 else -1)))
            if v is None:
                row += b"\x00\x00\x00\x00"
            else:
                row += bytes(_colour(v)) + bytes([200])
        rows.append(bytes(row))
    png = _png(W, H, rows)
    write_json(WAVES, {"t": iso(now), "model_time": when, "lat_max": LAT_MAX, "png": base64.b64encode(png).decode("ascii")})
    print(f"Waves map: updated ({len(png) // 1024} KB).")


def main():
    now = now_utc()
    crisis(now)
    weather(now)
    waves(now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
