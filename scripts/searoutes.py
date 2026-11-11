import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, haversine_nm, iso, now_utc, parse_iso, read_json, read_positions, write_json

ROUTES = os.path.join(DATA_DIR, "searoutes.json")
GAP_H = 6
MIN_NM = 20
MAX_PTS = 60


def key(a, b):
    return f"{a[0]:.3f},{a[1]:.3f}|{b[0]:.3f},{b[1]:.3f}"


def gaps(rows):
    by = {}
    for r in rows:
        t = parse_iso(r.get("ais_time_utc") or r.get("logged_at_utc"))
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if t:
            by.setdefault(r.get("id", ""), []).append((t, lat, lon))
    for pts in by.values():
        pts.sort()
        for (t1, a1, o1), (t2, a2, o2) in zip(pts, pts[1:]):
            if t2 - t1 > timedelta(hours=GAP_H) and haversine_nm(a1, o1, a2, o2) >= MIN_NM:
                yield (a1, o1), (a2, o2)


def main():
    try:
        import searoute as sr
    except ImportError:
        print("Sea routes: library not installed.")
        return 0
    old = read_json(ROUTES, {}).get("routes", {})
    routes, new, failed = {}, 0, 0
    for a, b in gaps(read_positions()):
        k = key(a, b)
        if k in routes:
            continue
        if k in old:
            routes[k] = old[k]
            continue
        try:
            c = sr.searoute([a[1], a[0]], [b[1], b[0]], append_orig_dest=True)["geometry"]["coordinates"]
        except Exception:
            failed += 1
            continue
        step = max(1, -(-len(c) // MAX_PTS))
        pts = c[::step] + ([c[-1]] if (len(c) - 1) % step else [])
        routes[k] = [[round(p[1], 2), round(p[0], 2)] for p in pts]
        new += 1
    write_json(ROUTES, {"t": iso(now_utc()), "gap_h": GAP_H, "routes": routes})
    print(f"Sea routes: {len(routes)} gap(s), {new} new" + (f", {failed} failed" if failed else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
