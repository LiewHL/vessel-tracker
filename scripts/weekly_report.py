"""Weekly, monthly and quarterly summary reports.

  python scripts/weekly_report.py --quarterly [--quarter 2026-Q4]   quarterly one-page summary

  python scripts/weekly_report.py             weekly report (last 7 days)
  python scripts/weekly_report.py --monthly   monthly report (previous calendar month)
  python scripts/weekly_report.py --monthly --month 2026-10   a specific month

Reads vessels.csv, data/positions.csv and data/latest.json and writes:
  reports/weekly-YYYY-MM-DD.html or reports/monthly-YYYY-MM.html
                                     printable report (open, then Print > Save as PDF)
  reports/index.json                 list of reports shown on the dashboard
  reports/latest-summary.md          short text for the weekly GitHub email
  reports/latest-monthly-summary.md  short text for the monthly GitHub email
"""
import argparse
import calendar
import html
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from insights import (  # noqa: E402
    active_in, category_colours, countries_visited, port_calls, timeline_svg, upcoming_changes,
)
from common import (  # noqa: E402
    DATA_DIR, LATEST, REPORT_INDEX, REPORTS_DIR, freshness, haversine_nm, load_roster,
    now_utc, parse_iso, place_label, places_visited, read_json, read_positions,
    write_json,
)

SGT = timezone(timedelta(hours=8))
ALERT_LOG = os.path.join(DATA_DIR, "alerts_log.json")
WORD = {"weekly": "week", "monthly": "month", "quarterly": "quarter"}
LABEL = {"fresh": "Seen in last 3 days", "stale": "3 to 7 days old",
         "old": "Over 7 days old", "none": "No position yet"}


def fmt_coord(lat, lon):
    def part(v, pos, neg):
        hemi = pos if v >= 0 else neg
        v = abs(v)
        d = int(v)
        m = (v - d) * 60
        return f"{d}°{m:04.1f}′{hemi}"
    return f"{part(lat, 'N', 'S')} {part(lon, 'E', 'W')}"


def fmt_sgt(dt, with_year=True):
    if not dt:
        return "—"
    return dt.astimezone(SGT).strftime("%d %b %Y %H:%M" if with_year else "%d %b %H:%M")


def age_text(dt, ref):
    if not dt:
        return "—"
    hours = (ref - dt).total_seconds() / 3600
    if hours < 1:
        return "under 1 hour ago"
    if hours < 48:
        return f"{int(hours)} hours ago"
    return f"{int(hours // 24)} days ago"


def period_progress(v, today):
    try:
        s = date.fromisoformat(v.get("start_date", ""))
        e = date.fromisoformat(v.get("end_date", ""))
    except ValueError:
        return "—", None
    total = (e - s).days + 1
    if today < s:
        return f"Starts {s.strftime('%d %b')}", 0
    if today > e:
        return "Completed", 100
    day = (today - s).days + 1
    return f"Day {day} of {total}", round(100 * day / total)


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_fixes(positions):
    """All logged positions grouped by ship ID, sorted by time."""
    by_id = defaultdict(list)
    for p in positions:
        t = parse_iso(p.get("ais_time_utc"))
        lat, lon = _fnum(p.get("latitude")), _fnum(p.get("longitude"))
        if t is None or lat is None or lon is None:
            continue
        by_id[p.get("id", "")].append({
            "t": t, "lat": lat, "lon": lon, "speed_kn": _fnum(p.get("speed_kn")),
            "nav_status": p.get("nav_status", ""), "destination": p.get("destination", ""),
        })
    for fixes in by_id.values():
        fixes.sort(key=lambda f: f["t"])
    return by_id


def period_bounds(kind, ref, month=None):
    """Return (start_utc, end_utc, label, tag, days_in_period)."""
    if kind == "weekly":
        start = ref - timedelta(days=7)
        label = f"{start.astimezone(SGT).strftime('%d %b')} – {ref.astimezone(SGT).strftime('%d %b %Y')}"
        return start, ref, label, ref.astimezone(SGT).date().isoformat(), 7
    if kind == "quarterly":
        if month:                       # "2026-Q4"
            y, q = int(month[:4]), int(month[-1])
        else:                           # previous quarter in Singapore time
            local = ref.astimezone(SGT)
            q = (local.month - 1) // 3      # 0 = we are in Q1, so report the previous year's Q4
            y, q = (local.year, q) if q else (local.year - 1, 4)
        sm = 3 * (q - 1) + 1
        start = datetime(y, sm, 1, tzinfo=SGT)
        end = datetime(y + (sm == 10), (sm + 2) % 12 + 1, 1, tzinfo=SGT)
        days = (end.date() - start.date()).days
        return (start.astimezone(timezone.utc), end.astimezone(timezone.utc),
                f"Q{q} {y} ({start:%b}–{(end - timedelta(days=1)):%b %Y})", f"{y:04d}-Q{q}", days)
    if month:
        y, m = (int(x) for x in month.split("-"))
    else:  # previous calendar month in Singapore time
        local = ref.astimezone(SGT)
        y, m = (local.year, local.month - 1) if local.month > 1 else (local.year - 1, 12)
    start = datetime(y, m, 1, tzinfo=SGT)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=SGT)
    days = calendar.monthrange(y, m)[1]
    return (start.astimezone(timezone.utc), end.astimezone(timezone.utc),
            start.strftime("%B %Y"), f"{y:04d}-{m:02d}", days)


def build(kind="weekly", ref=None, month=None):
    ref = ref or now_utc()
    start, end, period, tag, ndays = period_bounds(kind, ref, month)
    as_of = min(end, ref)                 # status is judged at the end of the period
    roster = load_roster()
    latest = read_json(LATEST, {})
    all_fixes = load_fixes(read_positions())

    rows, counts, follow_up = [], defaultdict(int), []
    total_fixes = heard_ships = 0
    for v in roster:
        history = [f for f in all_fixes.get(v["id"], []) if f["t"] <= as_of]
        in_period = [f for f in history if f["t"] >= start]
        if kind == "weekly" and v["id"] in latest:
            info = latest[v["id"]]
            last = {"t": parse_iso(info.get("last_seen_utc")), "lat": info.get("latitude"),
                    "lon": info.get("longitude"), "speed_kn": info.get("speed_kn"),
                    "nav_status": info.get("nav_status", ""), "destination": info.get("destination", "")}
            if last["t"] is None or last["lat"] is None:
                last = history[-1] if history else None
        else:
            last = history[-1] if history else None
        seen = last["t"] if last else None
        state = freshness(seen, as_of)
        counts[state] += 1
        dist = sum(haversine_nm(a["lat"], a["lon"], b["lat"], b["lon"])
                   for a, b in zip(in_period, in_period[1:]))
        days_heard = len({f["t"].astimezone(SGT).date() for f in in_period})
        total_fixes += len(in_period)
        heard_ships += 1 if in_period else 0
        prog_text, prog_pct = period_progress(v, as_of.astimezone(SGT).date())
        if state in ("old", "none") and prog_text != "Completed":
            follow_up.append(v)
        calls = [c for c in port_calls(history) if c["end"] >= start and c["start"] <= as_of]
        rows.append({
            "v": v, "last": last, "seen": seen, "state": state, "track": in_period,
            "dist": dist, "days": days_heard, "prog": prog_text, "pct": prog_pct,
            "first": in_period[0] if in_period else None,
            "calls": calls, "countries": countries_visited(in_period),
            "active": active_in(v, start.astimezone(SGT).date(), as_of.astimezone(SGT).date()),
        })

    today = ref.astimezone(SGT).date()
    soon_end, soon_start = upcoming_changes(roster, today, 14)
    alerts = [a for a in read_json(ALERT_LOG, []) if start <= (parse_iso(a.get("t")) or start) <= as_of]
    ctx = {"roster": roster, "today": today, "start": start, "soon_end": soon_end, "soon_start": soon_start,
           "alerts": alerts}

    os.makedirs(REPORTS_DIR, exist_ok=True)
    fname = f"{kind}-{tag}.html"
    with open(os.path.join(REPORTS_DIR, fname), "w", encoding="utf-8") as f:
        f.write(render_html(kind, rows, counts, follow_up, period, as_of, ref, ndays,
                            total_fixes, heard_ships, ctx))

    summary = {
        "kind": kind, "date": tag, "file": fname, "period": period,
        "tracked": len(roster), "fresh": counts["fresh"], "stale": counts["stale"],
        "old": counts["old"], "none": counts["none"], "heard": heard_ships,
        "positions": total_fixes, "follow_up": [v["id"] for v in follow_up],
        "port_calls": sum(len(r["calls"]) for r in rows), "alerts": len(alerts),
    }
    index = [r for r in read_json(REPORT_INDEX, []) if r.get("file") != fname]
    for r in index:
        r.setdefault("kind", "weekly")
    index = sorted([summary] + index, key=lambda r: r.get("date", ""), reverse=True)
    write_json(REPORT_INDEX, index[:160])

    title = kind.capitalize()
    w = WORD[kind]
    lines = [f"{title} vessel tracking summary for {period}.", "",
             f"- Ships tracked: {len(roster)}"]
    if kind != "weekly":
        lines += [f"- Ships heard at least once this {w}: {heard_ships}",
                  f"- Positions logged this {w}: {total_fixes}"]
    lines += [f"- Port calls / stops this {w}: {summary['port_calls']}",
              f"- Alerts this {w}: {len(alerts)}"]
    lines += [
        f"- Position in last 3 days{' of the ' + w if kind != 'weekly' else ''}: {counts['fresh']}",
        f"- Position 3 to 7 days old: {counts['stale']}",
        f"- Position over 7 days old: {counts['old']}",
        f"- No position yet: {counts['none']}",
    ]
    if follow_up:
        lines += ["", "Ships to follow up (no recent position): "
                  + ", ".join(f"{v['id']} ({v['vessel_name']})" for v in follow_up)]
    if soon_end or soon_start:
        lines += ["", "Coming up in the next 14 days:"]
        lines += [f"- {v['id']} {v['vessel_name']}: period ends {d:%d %b %Y}" for d, v in soon_end]
        lines += [f"- {v['id']} {v['vessel_name']}: period starts {d:%d %b %Y}" for d, v in soon_start]
    lines += ["", "The full report is attached, and is also under Reports on the dashboard."]
    md = {"weekly": "latest-summary.md", "monthly": "latest-monthly-summary.md",
          "quarterly": "latest-quarterly-summary.md"}[kind]
    with open(os.path.join(REPORTS_DIR, md), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return summary


def latest_category(cats):
    """The category shown open by default: the highest-numbered one (e.g. 2620 before 2615),
    skipping test categories marked TS. Others start collapsed."""
    cats = [c for c in cats if c]
    pool = [c for c in cats if not re.search(r"\bTS\b", c, re.I)] or cats
    if not pool:
        return ""
    def num(c):
        m = re.search(r"\d+", c)
        return int(m.group()) if m else -1
    best = max(num(c) for c in pool)
    return [c for c in pool if num(c) == best][-1]


def category_rank(cat, open_cat):
    """Section order: the open (latest) category first, then newest number first, test (TS) and
    uncategorised last."""
    m = re.search(r"\d+", cat or "")
    return (cat != open_cat, not cat or "No category" in cat, bool(re.search(r"\bTS\b", cat or "", re.I)),
            -(int(m.group()) if m else -1), cat)


def fmt_h(h):
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.1f} d"


def stay_text(c):
    """Stopped time as a range: at least end-start, at most departed-start (when known)."""
    lo = c["hours"]
    if c["departed"]:
        hi = (c["departed"] - c["start"]).total_seconds() / 3600
        return f"{fmt_h(lo)}–{fmt_h(hi)}" if fmt_h(lo) != fmt_h(hi) else f"about {fmt_h(hi)}"
    return f"at least {fmt_h(lo)}"


def calls_table(rows, w):
    e = html.escape
    trs = []
    for r in rows:
        for c in r["calls"]:
            dep = fmt_sgt(c["departed"], False) if c["departed"] else "still there at last report"
            trs.append(f"<tr><td><b>{e(r['v']['id'])}</b> {e(r['v']['vessel_name'])}</td><td>{e(c['kind'])}</td>"
                       f"<td>{e(c['place'] or '—')}</td><td class=mono>{e(fmt_sgt(c['start'], False))}</td>"
                       f"<td class=mono>{e(dep)}</td><td class=num>{e(stay_text(c))}</td></tr>")
    if not trs:
        return f'<p class="sub">No port calls or stops detected this {w}.</p>'
    table = ('<div class="tablewrap"><table class="small"><thead><tr><th>Ship</th><th>Type</th><th>Place</th>'
            '<th>First logged stopped (SGT)</th><th>Logged under way again</th><th class=num>Stopped for</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></div>'
            '<p class="sub">Detected from logged positions: stopped (under 0.5 kn) or AIS status Moored / At anchor. '
            '"Berthed" = within 5 nm of a port or Moored; "At anchor" = within 30 nm; "Stopped offshore" = further out '
            '(possible anchorage or ship-to-ship work). Times are when the logger heard the ship, so real arrival is earlier '
            'and departure later. "Stopped for" gives the range the logged positions allow.</p>')
    if len(trs) <= 8:
        return table
    return f'<details class="grp"><summary><b>{len(trs)} port calls / stops</b> <span class="sub">· click to show</span></summary><div style="padding:0 8px 8px">{table}</div></details>'


def coming_up(ctx):
    e = html.escape
    items = [f"<li><b>{e(v['id'])}</b> {e(v['vessel_name'])}: period <b>ends</b> {d:%a %d %b %Y}</li>" for d, v in ctx["soon_end"]]
    items += [f"<li><b>{e(v['id'])}</b> {e(v['vessel_name'])}: period <b>starts</b> {d:%a %d %b %Y}</li>" for d, v in ctx["soon_start"]]
    body = f"<ul>{''.join(items)}</ul>" if items else '<p class="sub">No periods start or end in the next 14 days.</p>'
    return f'<section><h2>Coming up (next 14 days from {ctx["today"]:%d %b})</h2>{body}</section>'


def alerts_section(ctx, w):
    e = html.escape
    if not ctx["alerts"]:
        return f'<section><h2>Alerts this {w}</h2><p class="sub">No alerts (risk areas, storms, ships gone quiet) this {w}.</p></section>'
    items = "".join(f"<li><span class=sub>{e(fmt_sgt(parse_iso(a['t']), False))}</span> · <b>{e(a['kind'])}</b>: {e(a['text'])}</li>"
                    for a in ctx["alerts"])
    return f'<section><h2>Alerts this {w} ({len(ctx["alerts"])})</h2><ul class="alerts">{items}</ul></section>'


def places_table(rows, w):
    e = html.escape
    trs = []
    for r in rows:
        if not r["track"]:
            continue
        ports = places_visited(r["track"])
        trs.append(f"<tr><td><b>{e(r['v']['id'])}</b> {e(r['v']['vessel_name'])}</td>"
                   f"<td>{e(', '.join(r['countries'])) or '—'}</td><td>{e(' → '.join(ports)) or '—'}</td>"
                   f"<td class=num>{len(r['calls'])}</td></tr>")
    countries = sorted({c for r in rows for c in r["countries"]})
    if not trs:
        return f'<p class="sub">No positions logged this {w}.</p>'
    return (f'<p><b>{len(countries)}</b> countr{"y" if len(countries) == 1 else "ies"} visited this {w}: {e(", ".join(countries)) or "—"}</p>'
            '<div class="tablewrap"><table class="small"><thead><tr><th>Ship</th><th>Countries</th><th>Ports (within 30 nm, in order)</th>'
            f'<th class=num>Port calls</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>')


def render_html(kind, rows, counts, follow_up, period, as_of, generated, ndays,
                total_fixes, heard_ships, ctx):
    e = html.escape
    monthly = kind != "weekly"
    w = WORD[kind]
    map_data, groups = [], {}
    for r in rows:
        v, last, seen = r["v"], r["last"], r["seen"]
        has_pos = bool(last) and last.get("lat") is not None
        pos = fmt_coord(last["lat"], last["lon"]) if has_pos else "—"
        if has_pos:
            map_data.append({
                "id": v["id"], "name": v["vessel_name"], "state": r["state"],
                "lat": last["lat"], "lon": last["lon"],
                "track": [[f["lat"], f["lon"]] for f in r["track"]],
            })
        motion = []
        if has_pos and last.get("nav_status"):
            motion.append(last["nav_status"])
        if has_pos and last.get("speed_kn") is not None:
            motion.append(f"{last['speed_kn']} kn")
        if has_pos and last.get("destination"):
            motion.append(f"→ {last['destination']}")
        place = place_label(last["lat"], last["lon"]) if has_pos else ""
        link = (f'<a href="https://www.vesselfinder.com/vessels/details/{e(v["imo"])}">IMO {e(v["imo"])}</a>'
                if v.get("imo") else "—")
        seen_sub = f"{e(fmt_sgt(seen))} SGT · {e(age_text(seen, as_of))}" if seen else "&nbsp;"
        visited = places_visited(r["track"])
        extra = f"<td>{e(' → '.join(visited)) if visited else '<span class=sub>None within 30 nm of a port</span>' if r['track'] else '—'}</td>"
        name_html = (f'<button type="button" class="vbtn" data-id="{e(v["id"])}" title="Show on map">{e(v["vessel_name"])}</button>'
                     if has_pos else f'{e(v["vessel_name"])} <span class="sub">(no position)</span>')
        cat = (v.get("category") or "").strip() or "No category"
        g = groups.setdefault(cat, {"rows": [], "heard": 0})
        g["heard"] += 1 if r["track"] else 0
        g["rows"].append(f"""
      <tr data-id="{e(v['id'])}">
        <td><b>{e(v['id'])}</b></td>
        <td>{name_html}<div class="sub">{e(v.get('company', ''))} · {link}</div></td>
        <td>{e(r['prog'])}</td>
        <td><span class="dot {r['state']}"></span>{e(LABEL[r['state']])}<div class="sub">{seen_sub}</div></td>
        <td><div class="mono">{e(pos)}</div><div class="place">{e(place)}</div><div class="sub">{e(' · '.join(motion)) or '&nbsp;'}</div></td>
        {extra}
        <td class="num">{r['days']}/{ndays}</td>
        <td class="num">{len(r['track'])}</td>
        <td class="num">{r['dist']:.0f}</td>
      </tr>""")

    follow = ""
    if follow_up:
        items = "".join(f"<li><b>{e(v['id'])}</b> {e(v['vessel_name'])}{' (' + e(v['company']) + ')' if v.get('company') else ''}</li>" for v in follow_up)
        follow = f"""<section class="callout"><h2>Follow up</h2>
      <p>No position received for over 7 days{(' by the end of the ' + w) if monthly else ''}. The ship may be mid-ocean (outside shore-based AIS coverage), in a high-risk area with AIS switched off, or the MMSI in vessels.csv may be wrong.</p>
      <ul>{items}</ul></section>"""

    n_calls = sum(len(r["calls"]) for r in rows)
    if kind == "quarterly":
        active = sum(1 for r in rows if r["active"])
        countries = {c for r in rows for c in r["countries"]}
        kpis = [(active, "Ships active this quarter", "ink"), (heard_ships, "Heard at least once", "fresh"),
                (total_fixes, "Positions logged", "ink"), (n_calls, "Port calls / stops", "ink"),
                (len(countries), "Countries visited", "ink"), (len(ctx["alerts"]), "Alerts", "old")]
        extra_head = "<th>Places this quarter (within 30 nm)</th>"
        last_head = "Position at quarter end"
        title = "Quarterly Vessel Tracking Summary"
        map_title = "Tracks this quarter"
        status_note = "Status is judged at the end of the quarter."
    elif monthly:
        kpis = [(len(rows), "Ships tracked", "ink"), (heard_ships, "Heard this month", "fresh"),
                (len(rows) - heard_ships, "Not heard this month", "old"),
                (total_fixes, "Positions logged", "ink"), (n_calls, "Port calls / stops", "ink")]
        extra_head = "<th>Places this month (within 30 nm)</th>"
        last_head = "Position at month end"
        title = "Monthly Vessel Tracking Report"
        map_title = "Tracks this month and position at month end"
        status_note = "Status is judged at the end of the month."
    else:
        kpis = [(len(rows), "Ships tracked", "ink"), (counts["fresh"], "Position in last 3 days", "fresh"),
                (counts["stale"], "3 to 7 days old", "stale"), (counts["old"], "Over 7 days old", "old"),
                (counts["none"], "No position yet", "none")]
        extra_head = "<th>Places this week (within 30 nm)</th>"
        last_head = "Position"
        title = "Weekly Vessel Tracking Report"
        map_title = "Last known positions and tracks this week"
        status_note = ""
    thead = (f'<thead><tr><th>ID</th><th>Vessel</th><th>Period</th><th>Last position received</th>'
             f'<th>{e(last_head)}</th>{extra_head}<th class="num">Days heard</th><th class="num">Positions</th>'
             f'<th class="num">Distance (nm)</th></tr></thead>')
    open_cat = latest_category(groups.keys())
    groups_html = "".join(
        f'<details class="grp"{" open" if cat == open_cat else ""}>'
        f'<summary><b>{e(cat)}</b> <span class="sub">· {len(g["rows"])} ship{"s" if len(g["rows"]) != 1 else ""}'
        f' · {g["heard"]} heard this {w}</span></summary>'
        f'<div class="tablewrap"><table>{thead}<tbody>{"".join(g["rows"])}</tbody></table></div></details>'
        for cat, g in sorted(groups.items(), key=lambda kv: category_rank(kv[0], open_cat)))
    # timeline (monthly + quarterly): ships whose period overlaps a window around the report period
    timeline = ""
    if monthly:
        ps, pe = ctx["start"].astimezone(SGT).date(), (as_of.astimezone(SGT) - timedelta(seconds=1)).date()
        order = sorted(ctx["roster"], key=lambda v: (category_rank((v.get("category") or "No category"),
                       latest_category({(x.get("category") or "No category") for x in ctx["roster"]})), v["id"]))
        svg = timeline_svg(order, category_colours(ctx["roster"]), ctx["today"], highlight=(ps, pe))
        timeline = (f'<section class="tl"><h2>Tracking periods</h2>{svg}<p class="sub">Bars are each ship\'s tracking period '
                    f'(colour = category). The shaded band is this {w}; the red line is today.</p></section>')
    extra_sections = alerts_section(ctx, w) + coming_up(ctx) + timeline
    if kind != "quarterly":     # the one-pager shows port-call counts in the places table instead
        extra_sections += f'<section><h2>Port calls and stops this {w}</h2>{calls_table(rows, w)}</section>'
    if monthly:
        extra_sections += f'<section><h2>Countries and ports visited this {w}</h2>{places_table(rows, w)}</section>'
    if kind == "quarterly":     # one-pager: no long per-ship detail table
        groups_html = ""
    kpi_html = "".join(f'<div class="kpi"><b style="color:var(--{c})">{n}</b><span>{e(l)}</span></div>' for n, l, c in kpis)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} {e(period)}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  :root {{ --ink:#14212b; --muted:#5b6b78; --line:#dde3e8; --bg:#f6f8fa; --card:#fff;
          --fresh:#1f8a4c; --stale:#c98a00; --old:#c0392b; --none:#8a96a0; --accent:#0b4f7a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; color:var(--ink); background:var(--bg); }}
  main {{ max-width:1140px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  h2 {{ font-size:16px; margin:0 0 10px; }}
  .meta {{ color:var(--muted); margin-bottom:18px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin-bottom:16px; }}
  .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
  .kpi b {{ display:block; font-size:24px; }}
  .kpi span {{ color:var(--muted); font-size:12px; }}
  section {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:16px; }}
  .callout {{ border-left:4px solid var(--old); }}
  #map {{ height:380px; border-radius:8px; }}
  .tablewrap {{ overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; min-width:960px; }}
  th, td {{ text-align:left; padding:8px 6px; border-bottom:1px solid var(--line); vertical-align:top; }}
  th {{ font-size:12px; color:var(--muted); font-weight:600; }}
  .num {{ text-align:right; }}
  .mono {{ font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .sub {{ color:var(--muted); font-size:12px; }}
  .place {{ font-size:12px; }}
  .dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; }}
  .dot.fresh {{ background:var(--fresh); }} .dot.stale {{ background:var(--stale); }}
  .dot.old {{ background:var(--old); }} .dot.none {{ background:var(--none); }}
  a {{ color:var(--accent); }}
  .foot {{ color:var(--muted); font-size:12px; }}
  details.grp {{ border:1px solid var(--line); border-radius:8px; margin-top:10px; }}
  details.grp > summary {{ cursor:pointer; padding:10px 12px; list-style:none; display:flex; gap:8px; align-items:center; }}
  details.grp > summary::-webkit-details-marker {{ display:none; }}
  details.grp > summary::before {{ content:"▸"; color:var(--muted); transition:transform .15s; }}
  details.grp[open] > summary::before {{ transform:rotate(90deg); }}
  details.grp[open] > summary {{ border-bottom:1px solid var(--line); }}
  details.grp .tablewrap {{ padding:0 8px 8px; }}
  .vbtn {{ font:inherit; font-weight:600; color:var(--accent); background:none; border:0; padding:0; cursor:pointer; text-align:left; text-decoration:underline; text-underline-offset:2px; }}
  tr.hl td {{ background:#eaf3f9; }}
  table.small {{ min-width:640px; font-size:13px; }}
  ul.alerts {{ margin:0; padding-left:18px; }} ul.alerts li {{ margin:3px 0; }}
  .tl svg {{ display:block; }}
  @media print {{ .vbtn {{ text-decoration:none; color:inherit; }} body {{ background:#fff; }} section, .kpi {{ break-inside:avoid; }} #map {{ height:300px; }} }}
</style></head>
<body><main>
  <h1>{e(title)}</h1>
  <div class="meta">Period {e(period)} · Generated {e(fmt_sgt(generated))} SGT{(' · ' + status_note) if status_note else ''}</div>
  <div class="kpis">{kpi_html}</div>
  {follow}
  <section><h2>{e(map_title)}</h2><div id="map"></div></section>
  {extra_sections}
  {'' if not groups_html else f"""<section><h2>Ship details</h2>
  <p class="sub" style="margin-top:-6px">Click a vessel name to show it on the map. Click a category to open or close it.</p>
  {groups_html}</section>"""}
  <p class="foot">Positions come from shore-based AIS receivers (AISStream), logged on a schedule. Ships far from coasts may show older positions until they come back into range. "Distance" is the straight-line sum between logged positions in the period, so it understates the real distance sailed. Places are the nearest ports from the World Port Index (NGA Pub. 150).</p>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  const ships = {json.dumps(map_data)};
  const colors = {{fresh:'#1f8a4c', stale:'#c98a00', old:'#c0392b', none:'#8a96a0'}};
  try {{
    const map = L.map('map', {{worldCopyJump:true}}).setView([5, 105], 3);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom:12, attribution:'© OpenStreetMap'}}).addTo(map);
    const pts = [], byId = {{}};
    ships.forEach(s => {{
      const line = s.track.length > 1 ? L.polyline(s.track, {{color:colors[s.state], weight:2, opacity:.6}}).addTo(map) : null;
      const mk = L.circleMarker([s.lat, s.lon], {{radius:7, color:'#fff', weight:2, fillColor:colors[s.state], fillOpacity:1}})
        .bindTooltip(s.id + ' · ' + s.name, {{permanent:ships.length <= 12, direction:'right', offset:[8,0]}}).addTo(map);
      byId[s.id] = {{s, mk, line}};
      pts.push([s.lat, s.lon]);
      s.track.forEach(p => pts.push(p));
    }});
    if (pts.length) map.fitBounds(pts, {{padding:[30,30], maxZoom:7}});
    let current = null;
    document.querySelectorAll('.vbtn').forEach(b => b.addEventListener('click', () => {{
      const o = byId[b.dataset.id]; if (!o) return;
      if (current) {{ current.mk.setRadius(7); if (current.line) current.line.setStyle({{weight:2, opacity:.6}}); }}
      document.querySelectorAll('tr.hl').forEach(t => t.classList.remove('hl'));
      b.closest('tr').classList.add('hl');
      o.mk.setRadius(11); o.mk.bringToFront();
      if (o.line) {{ o.line.setStyle({{weight:4, opacity:1}}); o.line.bringToFront(); o.mk.bringToFront(); }}
      document.getElementById('map').scrollIntoView({{behavior:'smooth', block:'center'}});
      const bounds = o.s.track.length > 1 ? L.latLngBounds(o.s.track.concat([[o.s.lat, o.s.lon]])) : null;
      if (bounds) map.fitBounds(bounds, {{padding:[40,40], maxZoom:9}}); else map.setView([o.s.lat, o.s.lon], 8);
      o.mk.openTooltip();
      current = o;
    }}));
  }} catch (err) {{ document.getElementById('map').textContent = 'Map could not load.'; }}
  // Printing / Save as PDF shows every category
  window.addEventListener('beforeprint', () => document.querySelectorAll('details.grp').forEach(d => {{ d.dataset.was = d.open; d.open = true; }}));
  window.addEventListener('afterprint', () => document.querySelectorAll('details.grp').forEach(d => {{ d.open = d.dataset.was === 'true'; }}));
</script>
</body></html>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--monthly", action="store_true", help="build the monthly report")
    ap.add_argument("--month", help="YYYY-MM to report on (default: previous month)")
    ap.add_argument("--quarterly", action="store_true", help="build the quarterly one-page summary")
    ap.add_argument("--quarter", help="YYYY-Qn to report on (default: previous quarter)")
    args = ap.parse_args()
    if args.quarterly or args.quarter:
        kind, which = "quarterly", args.quarter
    else:
        kind, which = ("monthly" if args.monthly or args.month else "weekly"), args.month
    print(json.dumps(build(kind, month=which), indent=2, default=str))
