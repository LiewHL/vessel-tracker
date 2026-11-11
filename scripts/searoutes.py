import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, ROOT, haversine_nm, iso, now_utc, parse_iso, read_json, read_positions, write_json

ROUTES = os.path.join(DATA_DIR, "searoutes.json")
LAND = os.path.join(ROOT, "assets", "countries.geojson")
VERSION = 2
GAP_H = 6
MIN_NM = 20
MAX_PTS = 60
STEP = 0.05
PORT_DEG = 0.15
CELL = 5


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


class Land:
    """Land outlines (Natural Earth, simplified) with a coarse grid for quick point-on-land tests."""

    def __init__(self, path):
        self.grid = {}
        with open(path, encoding="utf-8") as f:
            feats = json.load(f).get("features", [])
        for ft in feats:
            for poly in (ft.get("geometry") or {}).get("coordinates", []):
                if not poly or len(poly[0]) < 4:
                    continue
                ring = [(float(x), float(y)) for x, y in poly[0]]
                xs, ys = [p[0] for p in ring], [p[1] for p in ring]
                rec = (min(xs), min(ys), max(xs), max(ys), ring)
                for cx in range(int(rec[0] // CELL), int(rec[2] // CELL) + 1):
                    for cy in range(int(rec[1] // CELL), int(rec[3] // CELL) + 1):
                        self.grid.setdefault((cx, cy), []).append(rec)

    def on_land(self, lat, lon):
        lon = (lon + 180) % 360 - 180
        for x0, y0, x1, y1, ring in self.grid.get((int(lon // CELL), int(lat // CELL)), ()):
            if not (x0 <= lon <= x1 and y0 <= lat <= y1):
                continue
            inside, j = False, len(ring) - 1
            for i in range(len(ring)):
                xi, yi = ring[i]
                xj, yj = ring[j]
                if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                    inside = not inside
                j = i
            if inside:
                return True
        return False

    def clear(self, p, q, ends=()):
        """True when the straight map line p→q stays at sea (ignoring short coastal clips and the gap's two port ends)."""
        dlat, dlon = q[0] - p[0], q[1] - p[1]
        if dlon > 180:
            dlon -= 360
        elif dlon < -180:
            dlon += 360
        n = max(1, int(max(abs(dlat), abs(dlon)) / STEP))
        run = 0
        for i in range(1, n):
            lat, lon = p[0] + dlat * i / n, p[1] + dlon * i / n
            if any(abs(lat - e[0]) < PORT_DEG and abs(lon - e[1]) < PORT_DEG for e in ends):
                run = 0
                continue
            run = run + 1 if self.on_land(lat, lon) else 0
            if run >= 2:
                return False
        return True


def pull(path, land, ends):
    """Shorten the route: from each point jump to the farthest later point reachable in a straight line at sea."""
    out, i, last = [path[0]], 0, len(path) - 1
    while i < last:
        j = i + 1
        for k in range(last, i + 1, -1):
            if land.clear(path[i], path[k], ends):
                j = k
                break
        out.append(path[j])
        i = j
    return out


def route(a, b, sr, land):
    if land is None or land.clear(a, b, (a, b)):
        return [list(a), list(b)]
    c = sr.searoute([a[1], a[0]], [b[1], b[0]], append_orig_dest=True)["geometry"]["coordinates"]
    path = [(p[1], p[0]) for p in c]
    path[0], path[-1] = tuple(a), tuple(b)
    if land is not None:
        path = pull(path, land, (a, b))
    if len(path) > MAX_PTS:
        step = -(-len(path) // MAX_PTS)
        path = path[::step] + ([path[-1]] if (len(path) - 1) % step else [])
    return [list(p) for p in path]


def main():
    try:
        import searoute as sr
    except ImportError:
        print("Sea routes: library not installed.")
        return 0
    try:
        land = Land(LAND)
    except (OSError, ValueError):
        land = None
    saved = read_json(ROUTES, {})
    old = saved.get("routes", {}) if saved.get("v") == VERSION else {}
    routes, new, failed, straight = {}, 0, 0, 0
    for a, b in gaps(read_positions()):
        k = key(a, b)
        if k in routes:
            continue
        if k in old:
            routes[k] = old[k]
            continue
        try:
            pts = route(a, b, sr, land)
        except Exception:
            failed += 1
            continue
        routes[k] = [[round(p[0], 2), round(p[1], 2)] for p in pts]
        new += 1
        straight += len(pts) == 2
    write_json(ROUTES, {"t": iso(now_utc()), "v": VERSION, "gap_h": GAP_H, "routes": routes})
    print(f"Sea routes: {len(routes)} gap(s), {new} new ({straight} straight at sea)"
          + (f", {failed} failed" if failed else "") + ("; land outlines missing" if land is None else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
