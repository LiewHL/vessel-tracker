"""Shared analysis helpers: flags, ship types, port calls, countries, risk areas, periods, timeline.

The dashboard (index.html) uses the same rules for port calls, so keep both in step.
"""
import html
import math
import os
from datetime import date, datetime, timedelta, timezone

from common import NEAR_NM, ROOT, _where, haversine_nm, nearest_port, read_json

SGT = timezone(timedelta(hours=8))
MID_FILE = os.path.join(ROOT, "assets", "mid.json")
AREAS_FILE = os.path.join(ROOT, "config", "risk_areas.json")

# --- port-call rules (same as index.html) ---
STOP_KN = 0.5          # slower than this counts as stopped
BERTH_NM = 5           # stopped within this of a port (or AIS "Moored") = berthed
CALL_GAP_H = 36        # a gap longer than this between logged positions closes a call


_MID = None


def flag_of(mmsi):
    """Flag state from the first 3 digits of the MMSI (ITU Maritime Identification Digits)."""
    global _MID
    if _MID is None:
        _MID = read_json(MID_FILE, {}).get("mid", {})
    return _MID.get(str(mmsi or "")[:3], "")


def ship_type_text(code):
    try:
        c = int(code)
    except (TypeError, ValueError):
        return ""
    groups = [(20, 29, "Wing in ground"), (30, 30, "Fishing"), (31, 32, "Towing"), (33, 33, "Dredging"),
              (34, 34, "Diving"), (35, 35, "Military"), (36, 36, "Sailing"), (37, 37, "Pleasure craft"),
              (40, 49, "High-speed craft"), (50, 50, "Pilot"), (51, 51, "Search and rescue"), (52, 52, "Tug"),
              (53, 53, "Port tender"), (54, 54, "Anti-pollution"), (55, 55, "Law enforcement"),
              (58, 58, "Medical transport"), (60, 69, "Passenger"), (70, 79, "Cargo"), (80, 89, "Tanker"),
              (90, 99, "Other")]
    for lo, hi, name in groups:
        if lo <= c <= hi:
            return name
    return ""


def zone_offset(lon):
    """Nautical time zone (whole hours from UTC) for a longitude. Ships often keep this time at sea."""
    return max(-12, min(12, int(math.floor((lon + 7.5) / 15))))


# ---------------------------------------------------------------- port calls
def _stopped(f):
    sp = f.get("speed_kn")
    st = (f.get("nav_status") or "").lower()
    return st in ("moored", "at anchor") or (sp is not None and sp < STOP_KN)


def port_calls(fixes):
    """Group stopped positions into calls.

    fixes: list of {"t", "lat", "lon", "speed_kn", "nav_status"} sorted by time.
    Returns [{"kind": "Berthed"|"At anchor"|"Stopped offshore", "place", "country", "start", "end",
              "departed", "hours", "fixes", "lat", "lon"}]. start/end are the first/last logged
    positions while stopped; departed is the first logged position under way afterwards (or None).
    """
    calls, cur = [], None

    def close(departed=None):
        nonlocal cur
        if cur:
            cur["departed"] = departed
            cur["hours"] = round((cur["end"] - cur["start"]).total_seconds() / 3600, 1)
            calls.append(cur)
        cur = None

    for f in fixes:
        if cur and (f["t"] - cur["end"]).total_seconds() > CALL_GAP_H * 3600:
            close()
        if not _stopped(f):
            close(f["t"])
            continue
        np_ = nearest_port(f["lat"], f["lon"])
        dist = np_[2] if np_ else 1e9
        st = (f.get("nav_status") or "").lower()
        if st == "moored" or (st != "at anchor" and dist <= BERTH_NM):
            kind = "Berthed"
        elif dist <= NEAR_NM:
            kind = "At anchor"
        else:
            kind = "Stopped offshore"
        place = _where(np_[0], np_[1]) if np_ and dist <= NEAR_NM else (f"{dist:.0f} nm from {_where(np_[0], np_[1])}" if np_ else "")
        if cur and cur["kind"] == kind and haversine_nm(cur["lat"], cur["lon"], f["lat"], f["lon"]) <= 10:
            cur["end"] = f["t"]
            cur["fixes"] += 1
            continue
        close(f["t"])
        cur = {"kind": kind, "place": place, "country": np_[1] if np_ and dist <= NEAR_NM else "",
               "start": f["t"], "end": f["t"], "fixes": 1, "lat": f["lat"], "lon": f["lon"]}
    if cur:
        cur["departed"] = None
        cur["hours"] = round((cur["end"] - cur["start"]).total_seconds() / 3600, 1)
        calls.append(cur)
    return calls


def countries_visited(fixes):
    """Countries of ports a ship came within NEAR_NM of, in order of first visit."""
    seen, out = set(), []
    for f in fixes:
        np_ = nearest_port(f["lat"], f["lon"])
        if np_ and np_[2] <= NEAR_NM and np_[1] and np_[1] not in seen:
            seen.add(np_[1])
            out.append(np_[1])
    return out


# ---------------------------------------------------------------- risk areas
def load_areas():
    cfg = read_json(AREAS_FILE, {})
    return [a for a in cfg.get("areas", []) if a.get("active", True) and len(a.get("polygon", [])) >= 3], cfg


def in_polygon(lat, lon, poly):
    """Ray casting; poly is [[lat, lon], ...]. Fine for areas that don't cross the date line."""
    inside = False
    n = len(poly)
    for i in range(n):
        y1, x1 = poly[i]
        y2, x2 = poly[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x:
                inside = not inside
    return inside


def areas_at(lat, lon, areas):
    return [a["name"] for a in areas if in_polygon(lat, lon, a["polygon"])]


# ---------------------------------------------------------------- periods
def _d(s):
    try:
        return date.fromisoformat(s or "")
    except ValueError:
        return None


def upcoming_changes(roster, today, days=14):
    """Ships whose period starts or ends within `days` of today (inclusive)."""
    soon_end, soon_start = [], []
    for v in roster:
        s, e = _d(v.get("start_date")), _d(v.get("end_date"))
        if e and 0 <= (e - today).days <= days:
            soon_end.append((e, v))
        if s and 0 <= (s - today).days <= days:
            soon_start.append((s, v))
    return sorted(soon_end, key=lambda x: x[0]), sorted(soon_start, key=lambda x: x[0])


def active_in(v, start, end):
    """True if the ship's period overlaps [start, end] (dates). Ships without dates count as active."""
    s, e = _d(v.get("start_date")), _d(v.get("end_date"))
    if not s or not e:
        return True
    return s <= end and e >= start


# ---------------------------------------------------------------- timeline (SVG)
def timeline_svg(roster, colours, today, window_start=None, window_end=None, highlight=None):
    """Bars of each ship's period, grouped as given (roster order). colours: {category: hex}.
    highlight: optional (start_date, end_date) shaded as the report period."""
    rows = [(v, _d(v.get("start_date")), _d(v.get("end_date"))) for v in roster]
    rows = [r for r in rows if r[1] and r[2]]
    if not rows:
        return '<p class="sub">No tracking periods set in vessels.csv.</p>'
    lo = window_start or min(r[1] for r in rows)
    hi = window_end or max(r[2] for r in rows)
    lo = date(lo.year, lo.month, 1)
    hi = (date(hi.year + (hi.month == 12), hi.month % 12 + 1, 1))
    span = max(1, (hi - lo).days)
    label_w, w, row_h, top = 150, 900, 22, 26
    h = top + row_h * len(rows) + 8
    x = lambda d: label_w + (w - label_w) * max(0, min(span, (d - lo).days)) / span
    e = html.escape
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Timeline of tracking periods" '
           f'style="font:11px system-ui,sans-serif">']
    if highlight:
        hx1, hx2 = x(highlight[0]), x(highlight[1])
        out.append(f'<rect x="{hx1:.1f}" y="{top - 6}" width="{max(1, hx2 - hx1):.1f}" height="{h - top}" fill="#0b4f7a" opacity=".07"/>')
    m = lo
    while m < hi:
        xx = x(m)
        out.append(f'<line x1="{xx:.1f}" y1="{top - 6}" x2="{xx:.1f}" y2="{h}" stroke="#dde3e8"/>')
        lbl = m.strftime("%b %Y") if (m == lo or m.month == 1) else m.strftime("%b")
        out.append(f'<text x="{xx + 3:.1f}" y="{top - 10}" fill="#5b6b78">{lbl}</text>')
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    for i, (v, s, en) in enumerate(rows):
        y = top + i * row_h
        col = colours.get(v.get("category", ""), "#8a96a0")
        out.append(f'<text x="0" y="{y + 14}" fill="#14212b"><tspan font-weight="700">{e(v["id"])}</tspan> {e(v["vessel_name"][:16])}</text>')
        x1, x2 = x(s), x(en)
        out.append(f'<rect x="{x1:.1f}" y="{y + 4}" width="{max(2, x2 - x1):.1f}" height="{row_h - 8}" rx="3" fill="{col}">'
                   f'<title>{e(v["id"])} {e(v["vessel_name"])}: {s:%d %b %Y} – {en:%d %b %Y}</title></rect>')
    if lo <= today <= hi:
        tx = x(today)
        out.append(f'<line x1="{tx:.1f}" y1="{top - 6}" x2="{tx:.1f}" y2="{h}" stroke="#c0392b" stroke-width="1.5"/>')
        out.append(f'<text x="{tx + 3:.1f}" y="{h - 2}" fill="#c0392b">today</text>')
    out.append("</svg>")
    return "".join(out)


CAT_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]


def category_colours(roster):
    order = []
    for v in roster:
        c = v.get("category", "")
        if c and c not in order:
            order.append(c)
    return {c: CAT_COLOURS[i % len(CAT_COLOURS)] for i, c in enumerate(order)}
