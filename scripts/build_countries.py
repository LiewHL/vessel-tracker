import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALIAS = {
    "United States of America": "United States", "United Republic of Tanzania": "Tanzania",
    "The Bahamas": "Bahamas", "Republic of Serbia": "Serbia", "Hong Kong S.A.R.": "Hong Kong",
    "Macao S.A.R": "Macao", "Guinea Bissau": "Guinea-Bissau", "East Timor": "Timor-Leste",
    "Federated States of Micronesia": "Micronesia", "Ivory Coast": "Côte d'Ivoire",
    "Republic of the Congo": "Republic of the Congo", "Democratic Republic of the Congo": "Democratic Republic of the Congo",
    "Cabo Verde": "Cabo Verde", "Cape Verde": "Cabo Verde", "Curaçao": "Curaçao", "Sint Maarten": "Sint Maarten",
    "eSwatini": "Eswatini", "Czechia": "Czech Republic", "North Macedonia": "North Macedonia",
    "Falkland Islands": "Falkland Islands", "Faroe Islands": "Faroe Islands", "Saint Lucia": "Saint Lucia",
    "Saint Vincent and the Grenadines": "Saint Vincent and the Grenadines", "Turks and Caicos Islands": "Turks and Caicos Islands",
    "British Virgin Islands": "British Virgin Islands", "United States Virgin Islands": "U.S. Virgin Islands",
    "South Korea": "South Korea", "North Korea": "North Korea", "Republic of Korea": "South Korea",
    "Brunei": "Brunei", "Myanmar": "Myanmar", "Vietnam": "Vietnam", "Russia": "Russia", "Taiwan": "Taiwan",
    "São Tomé and Principe": "São Tomé and Príncipe", "Sao Tome and Principe": "São Tomé and Príncipe",
}


def simplify(pts, tol):
    if len(pts) < 5:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1e-12
        best, idx = 0, None
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / L
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    out = [p for p, k in zip(pts, keep) if k]
    return out if len(out) >= 4 else pts


def ring(r, tol):
    s = simplify(r, tol)
    return [[round(x, 2), round(y, 2)] for x, y in s]


def main():
    src = json.load(open(sys.argv[1], encoding="utf-8"))
    ports = json.load(open(os.path.join(ROOT, "assets", "ports.json"), encoding="utf-8"))["ports"]
    wanted = {p[1] for p in ports}
    feats, have = [], set()
    for f in src["features"]:
        p = f["properties"]
        cands = [p.get("ADMIN"), p.get("NAME"), p.get("NAME_LONG"), p.get("NAME_EN"), p.get("GEOUNIT")]
        name = next((ALIAS[c] for c in cands if c in ALIAS), None) or next((c for c in cands if c in wanted), None) or p.get("ADMIN")
        g = f["geometry"]
        area_small = p.get("LABELRANK", 5) >= 6
        tol = 0.01 if area_small else 0.04
        if g["type"] == "Polygon":
            coords = [[ring(r, tol) for r in g["coordinates"]]]
        else:
            coords = [[ring(r, tol) for r in poly] for poly in g["coordinates"]]
        feats.append({"type": "Feature", "properties": {"name": name},
                      "geometry": {"type": "MultiPolygon", "coordinates": coords}})
        have.add(name)
    out = os.path.join(ROOT, "assets", "countries.geojson")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "source": "Natural Earth 1:50m (public domain), simplified",
                   "features": feats}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(feats)} countries, {os.path.getsize(out) // 1024} KB")
    missing = sorted(wanted - have - {"Unassigned"})
    print("Port countries without an outline (shown as port dots only):", ", ".join(missing))


if __name__ == "__main__":
    main()
