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
    active_in, category_colours, countries_visited, destination_text, port_calls, timeline_svg,
    upcoming_changes,
)
from common import (  # noqa: E402
    DATA_DIR, LATEST, REPORT_INDEX, REPORTS_DIR, REQUIRED_DAYS, completion_date, period_info, freshness, haversine_nm, load_roster,
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
    """Days on board out of 182 (26 weeks), counting only the stints actually on board."""
    stints = v.get("stints") or []
    p = period_info(stints, today) if stints else {"status": "nodates", "days": 0}
    pct = round(100 * min(p["days"], REQUIRED_DAYS) / REQUIRED_DAYS)
    if p["status"] == "nodates":
        return "—", None
    if p["status"] == "completed":
        return "Completed", 100
    if p["status"] == "upcoming":
        return f"Starts {p['next_start']:%d %b}", 0
    if p["status"] == "paused":
        return f"Paused since {p['paused_since']:%d %b} · Day {p['days']} of {REQUIRED_DAYS}", pct
    return f"Day {p['days']} of {REQUIRED_DAYS} · exp. finish {p['expected_end']:%d %b %Y}", pct


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
    standby = [v for v in load_roster(include_standby=True) if v["standby"]]
    p_start, p_end = start.astimezone(SGT).date(), (as_of.astimezone(SGT) - timedelta(seconds=1)).date()
    completed = sorted(((d, v) for v in roster for d in (completion_date(v.get("stints", [])),)
                        if d and p_start <= d <= p_end), key=lambda x: x[0])
    ctx = {"roster": roster, "standby": standby, "completed": completed, "today": today, "start": start, "soon_end": soon_end, "soon_start": soon_start,
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
        "generated": ref.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
    if kind == "quarterly":
        lines += ["", f"Completed 182 days on board this quarter: {len(completed)}"]
        lines += [f"- {v['id']} {v['vessel_name']} ({d:%d %b %Y})" for d, v in completed]
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


def calls_table(rows, w, colours=None, open_cat=""):
    """Port calls as category -> ship -> list of calls; everything starts closed."""
    e = html.escape
    colours = colours or {}
    cats = {}
    for r in rows:
        if not r["calls"]:
            continue
        cat = (r["v"].get("category") or "").strip() or "No category"
        cats.setdefault(cat, []).append(r)
    if not cats:
        return f'<p class="sub">No port calls or stops detected this {w}.</p>'
    head = ('<thead><tr><th>Type</th><th>Place</th><th>First logged stopped (SGT)</th>'
            '<th>Logged under way again</th><th class=num>Stopped for</th></tr></thead>')
    out = []
    for cat in sorted(cats, key=lambda c: category_rank(c, open_cat)):
        ships = []
        for r in cats[cat]:
            v, calls = r["v"], r["calls"]
            trs = "".join(
                f"<tr><td>{e(c['kind'])}</td><td>{e(c['place'] or '—')}</td>"
                f"<td class=mono>{e(fmt_sgt(c['start'], False))}</td>"
                f"<td class=mono>{e(fmt_sgt(c['departed'], False) if c['departed'] else 'still there at last report')}</td>"
                f"<td class=num>{e(stay_text(c))}</td></tr>" for c in calls)
            places = []
            for c in calls:
                name = (c["place"] or "").split(",")[0]
                if name and name not in places:
                    places.append(name)
            ships.append(
                f'<details class="ship"><summary><b>{e(v["id"])}</b>&nbsp;{e(v["vessel_name"])}'
                f' <span class="sub">· {len(calls)} call{"s" if len(calls) != 1 else ""}'
                f'{(" · " + e(", ".join(places[:4])) + (" …" if len(places) > 4 else "")) if places else ""}</span></summary>'
                f'<div class="tablewrap" style="margin:0 0 10px 18px"><table class="small">{head}<tbody>{trs}</tbody></table></div></details>')
        n = sum(len(r["calls"]) for r in cats[cat])
        out.append(
            f'<details class="grp"><summary><span class="dot" style="background:{colours.get(cat, "#8a96a0")}"></span>'
            f'<b>{e(cat)}</b> <span class="sub">· {n} call{"s" if n != 1 else ""} · {len(cats[cat])} ship{"s" if len(cats[cat]) != 1 else ""}</span></summary>'
            f'<div class="ships">{"".join(ships)}</div></details>')
    return ("".join(out) +
            '<p class="sub">Detected from logged positions: stopped (under 0.5 kn) or AIS status Moored / At anchor. '
            '"Berthed" = within 5 nm of a port or Moored; "At anchor" = within 30 nm; "Stopped offshore" = further out '
            '(possible anchorage or ship-to-ship work). Times are when the logger heard the ship, so real arrival is earlier '
            'and departure later. "Stopped for" gives the range the logged positions allow.</p>')


def coming_up(ctx, kind="weekly"):
    e = html.escape
    done = ""
    if kind == "quarterly":
        comp = ctx.get("completed", [])
        names = "".join(f"<li><b>{e(v['id'])}</b> {e(v['vessel_name'])}: completed 182 days on board on {d:%d %b %Y}</li>"
                        for d, v in comp)
        done = (f'<p><b>{len(comp)}</b> completed their 182 days on board this quarter.</p>'
                + (f"<ul>{names}</ul>" if names else ""))
    items = [f"<li><b>{e(v['id'])}</b> {e(v['vessel_name'])}: period <b>ends</b> {d:%a %d %b %Y}</li>" for d, v in ctx["soon_end"]]
    items += [f"<li><b>{e(v['id'])}</b> {e(v['vessel_name'])}: period <b>starts</b> {d:%a %d %b %Y}</li>" for d, v in ctx["soon_start"]]
    body = f"<ul>{''.join(items)}</ul>" if items else '<p class="sub">No periods start or end in the next 14 days.</p>'
    if done:
        return (f'<section><h2>Completed and coming up</h2>{done}'
                f'<p class="sub" style="margin:12px 0 4px">Next 14 days from {ctx["today"]:%d %b}:</p>{body}</section>')
    return f'<section><h2>Coming up (next 14 days from {ctx["today"]:%d %b})</h2>{body}</section>'


def alerts_section(ctx, w):
    e = html.escape
    if not ctx["alerts"]:
        return f'<section><h2>Alerts this {w}</h2><p class="sub">No alerts (risk areas, storms, ships gone quiet) this {w}.</p></section>'
    items = "".join(f"<li><span class=sub>{e(fmt_sgt(parse_iso(a['t']), False))}</span> · <b>{e(a['kind'])}</b>: {e(a['text'])}</li>"
                    for a in ctx["alerts"])
    return f'<section><h2>Alerts this {w} ({len(ctx["alerts"])})</h2><ul class="alerts">{items}</ul></section>'


def places_table(rows, w, colours=None, open_cat=""):
    """Countries and ports as category -> ship -> details; everything starts closed."""
    e = html.escape
    colours = colours or {}
    cats = {}
    for r in rows:
        if r["track"]:
            cat = (r["v"].get("category") or "").strip() or "No category"
            cats.setdefault(cat, []).append(r)
    if not cats:
        return f'<p class="sub">No positions logged this {w}.</p>'
    countries = sorted({c for r in rows for c in r["countries"]})
    out = [f'<p><b>{len(countries)}</b> countr{"y" if len(countries) == 1 else "ies"} visited this {w}: '
           f'{e(", ".join(countries)) or "—"}</p>']
    for cat in sorted(cats, key=lambda c: category_rank(c, open_cat)):
        ships, cat_countries = [], set()
        for r in cats[cat]:
            v = r["v"]
            ports = places_visited(r["track"])
            cat_countries.update(r["countries"])
            ships.append(
                f'<details class="ship"><summary><b>{e(v["id"])}</b>&nbsp;{e(v["vessel_name"])}'
                f' <span class="sub">· {e(", ".join(r["countries"])) or "no port within 30 nm"}</span></summary>'
                f'<dl class="kv"><dt>Countries</dt><dd>{e(", ".join(r["countries"])) or "—"}</dd>'
                f'<dt>Ports (in order)</dt><dd>{e(" → ".join(ports)) or "None within 30 nm of a port"}</dd>'
                f'<dt>Port calls / stops</dt><dd>{len(r["calls"])}</dd></dl></details>')
        out.append(
            f'<details class="grp"><summary><span class="dot" style="background:{colours.get(cat, "#8a96a0")}"></span>'
            f'<b>{e(cat)}</b> <span class="sub">· {len(cat_countries)} countr{"y" if len(cat_countries) == 1 else "ies"}'
            f' · {len(cats[cat])} ship{"s" if len(cats[cat]) != 1 else ""}</span></summary>'
            f'<div class="ships">{"".join(ships)}</div></details>')
    return "".join(out)


def render_html(kind, rows, counts, follow_up, period, as_of, generated, ndays,
                total_fixes, heard_ships, ctx):
    e = html.escape
    monthly = kind != "weekly"
    w = WORD[kind]
    last_head = {"weekly": "Last position", "monthly": "Position at month end",
                 "quarterly": "Position at quarter end"}[kind]
    colours = category_colours(ctx["roster"])
    map_data, groups = [], {}
    for r in rows:
        v, last, seen = r["v"], r["last"], r["seen"]
        has_pos = bool(last) and last.get("lat") is not None
        pos = fmt_coord(last["lat"], last["lon"]) if has_pos else "—"
        if has_pos:
            map_data.append({
                "id": v["id"], "name": v["vessel_name"], "state": r["state"],
                "cat": (v.get("category") or "").strip() or "No category",
                "lat": last["lat"], "lon": last["lon"],
                "track": [[f["lat"], f["lon"]] for f in r["track"]],
            })
        motion = []
        if has_pos and last.get("nav_status"):
            motion.append(last["nav_status"])
        if has_pos and last.get("speed_kn") is not None:
            motion.append(f"{last['speed_kn']} kn")
        if has_pos and last.get("destination"):
            motion.append(f"→ next port {destination_text(last['destination'])}")
        place = place_label(last["lat"], last["lon"]) if has_pos else ""
        link = (f'<a href="https://www.vesselfinder.com/vessels/details/{e(v["imo"])}">IMO {e(v["imo"])}</a>'
                if v.get("imo") else "—")
        seen_sub = f"{e(fmt_sgt(seen))} SGT · {e(age_text(seen, as_of))}" if seen else "&nbsp;"
        visited = places_visited(r["track"])
        extra = f"<td>{e(' → '.join(visited)) if visited else '<span class=sub>None within 30 nm of a port</span>' if r['track'] else '—'}</td>"
        map_btn = (f'<button type="button" class="vbtn" data-id="{e(v["id"])}" title="Show on map">Map</button>'
                   if has_pos else '<span class="sub">no position</span>')
        cat = (v.get("category") or "").strip() or "No category"
        g = groups.setdefault(cat, {"rows": [], "heard": 0})
        g["heard"] += 1 if r["track"] else 0
        short_seen = age_text(seen, as_of) if seen else "no position yet"
        places_txt = (" → ".join(visited) if visited else "None within 30 nm of a port") if r["track"] else "—"
        g["rows"].append(f"""
      <details class="ship" data-id="{e(v['id'])}">
        <summary><span class="dot {r['state']}"></span><b>{e(v['id'])}</b>&nbsp;{e(v['vessel_name'])}
          <span class="sub">· {e(short_seen)}{(' · ' + e(place)) if place else ''}</span>
          <span class="sp"></span>{map_btn}</summary>
        <dl class="kv">
          <dt>Company</dt><dd>{e(v.get('company', '')) or '—'} · {link}</dd>
          <dt>Period</dt><dd>{e(r['prog'])}</dd>
          <dt>{e(last_head)}</dt><dd><span class="dot {r['state']}"></span>{e(LABEL[r['state']])}<div class="sub">{seen_sub}</div></dd>
          <dt>Position</dt><dd><span class="mono">{e(pos)}</span>{('<div>' + e(place) + '</div>') if place else ''}<div class="sub">{e(' · '.join(motion))}</div></dd>
          <dt>Places this {w}</dt><dd>{e(places_txt)}</dd>
          <dt>Logged this {w}</dt><dd>{r['days']}/{ndays} days heard · {len(r['track'])} positions · {r['dist']:.0f} nm</dd>
        </dl>
      </details>""")

    for v in ctx.get("standby", []):
        cat = (v.get("category") or "").strip() or "No category"
        g = groups.setdefault(cat, {"rows": [], "heard": 0})
        g["sb"] = g.get("sb", 0) + 1
        g.setdefault("sbrows", []).append(
            f'<div class="sbline"><b>{e(v["id"])}</b> <span class="sub">Standby · no vessel assigned yet</span></div>')

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
    def grp_summary(g):
        parts = []
        if g["rows"]:
            parts += [f'{len(g["rows"])} ship{"s" if len(g["rows"]) != 1 else ""}', f'{g["heard"]} heard this {w}']
        if g.get("sb"):
            parts.append(f'{g["sb"]} standby')
        return " · ".join(parts)
    # Category -> ship -> details; everything starts closed (printing opens all).
    groups_html = "".join(
        f'<details class="grp" data-cat="{e(cat)}">'
        f'<summary><span class="dot" style="background:{colours.get(cat, "#8a96a0")}"></span><b>{e(cat)}</b>'
        f' <span class="sub">· {e(grp_summary(g))}</span></summary>'
        f'<div class="ships">{"".join(g["rows"] + g.get("sbrows", []))}</div></details>'
        for cat, g in sorted(groups.items(), key=lambda kv: category_rank(kv[0], open_cat)))
    # timeline (monthly + quarterly): ships whose period overlaps a window around the report period
    timeline = ""
    if monthly:
        ps, pe = ctx["start"].astimezone(SGT).date(), (as_of.astimezone(SGT) - timedelta(seconds=1)).date()
        # One collapsible timeline per category, all on the same time scale so they line up.
        dated = [st for v in ctx["roster"] for st in v.get("stints", []) if st["start"]]
        ends = [x for v in ctx["roster"] for x in ((v.get("period") or {}).get("expected_end"),) if x]
        ends += [st["end"] for st in dated if st["end"]]
        lo = min([st["start"] for st in dated] + [ps]) if dated else ps
        hi = max(ends + [ctx["today"], pe])
        by_cat = {}
        for v in ctx["roster"]:
            by_cat.setdefault((v.get("category") or "").strip() or "No category", []).append(v)
        parts = []
        for cat in sorted(by_cat, key=lambda c: category_rank(c, open_cat)):
            ships = sorted(by_cat[cat], key=lambda v: v["id"])
            svg = timeline_svg(ships, colours, ctx["today"], window_start=lo, window_end=hi, highlight=(ps, pe))
            parts.append(f'<details class="grp"><summary><span class="dot" style="background:{colours.get(cat, "#8a96a0")}"></span>'
                         f'<b>{e(cat)}</b> <span class="sub">· {len(ships)} ship{"s" if len(ships) != 1 else ""}</span></summary>'
                         f'<div style="padding:8px 10px">{svg}</div></details>')
        svg = "".join(parts)
        timeline = (f'<section class="tl"><h2>Tracking periods</h2>{svg}<p class="sub">Solid = time on board (each stint); '
                    f'dashed = expected time still needed to reach 182 days (26 weeks). Colour = category. '
                    f'The shaded band is this {w}; the red line is today.</p></section>')
    side_sections = alerts_section(ctx, w) + coming_up(ctx, kind)
    lower_sections = []          # shown side by side on wide screens
    if kind != "quarterly":     # the one-pager shows port-call counts in the places table instead
        lower_sections.append(f'<section><h2>Port calls and stops this {w}</h2>{calls_table(rows, w, colours, open_cat)}</section>')
    lower_sections.append(f'<section><h2>Countries and ports visited this {w}</h2>{places_table(rows, w, colours, open_cat)}</section>')
    if kind == "quarterly":     # one-pager: no long per-ship detail table; fill the column beside the map
        groups_html = ""
        side_sections += timeline + "".join(lower_sections)
        timeline, lower_sections = "", []
    kpi_html = "".join(f'<div class="kpi"><b style="color:var(--{c})">{n}</b><span>{e(l)}</span></div>' for n, l, c in kpis)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} {e(period)}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
  :root {{ --ink:#14212b; --muted:#5b6b78; --line:#dde3e8; --bg:#f6f8fa; --card:#fff;
          --fresh:#1f8a4c; --stale:#c98a00; --old:#c0392b; --none:#8a96a0; --accent:#0b4f7a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; color:var(--ink); background:var(--bg); }}
  main {{ max-width:1680px; margin:0 auto; padding:24px 16px 48px; }}
  /* wide screens: map on the left (stays in view), details on the right; lower tables side by side */
  .cols, .cols2 {{ display:grid; grid-template-columns:minmax(0,1fr); gap:0 16px; }}
  @media (min-width:1100px) {{
    .cols {{ grid-template-columns:minmax(0,1.25fr) minmax(0,1fr); align-items:start; }}
    .colL {{ position:sticky; top:12px; }}
    #map {{ height:min(68vh, 620px) !important; }}
    .cols2 {{ grid-template-columns:repeat(auto-fit, minmax(480px, 1fr)); align-items:start; }}
    .kpis {{ grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); }}
  }}
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
  details.grp .ships {{ padding:4px 8px 8px 22px; }}
  details.ship {{ border-bottom:1px solid var(--line); }}
  details.ship:last-child {{ border-bottom:0; }}
  details.ship > summary {{ cursor:pointer; list-style:none; display:flex; flex-wrap:wrap; gap:4px 6px; align-items:center; padding:8px 4px; }}
  details.ship > summary::-webkit-details-marker {{ display:none; }}
  details.ship > summary::before {{ content:"▸"; color:var(--muted); font-size:12px; transition:transform .15s; }}
  details.ship[open] > summary::before {{ transform:rotate(90deg); }}
  details.ship .sp {{ flex:1; }}
  dl.kv {{ display:grid; grid-template-columns:max-content 1fr; gap:4px 14px; margin:0 0 10px 18px; font-size:13px; }}
  dl.kv dt {{ color:var(--muted); }} dl.kv dd {{ margin:0; }}
  .sbline {{ padding:6px 4px; border-bottom:1px solid var(--line); }}
  .maptools {{ display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; margin-bottom:8px; }}
  .seg {{ display:inline-flex; border:1px solid var(--line); border-radius:7px; overflow:hidden; }}
  .seg button {{ font:inherit; font-size:12px; font-weight:600; border:0; background:#fff; color:var(--muted); padding:4px 10px; cursor:pointer; }}
  .seg button + button {{ border-left:1px solid var(--line); }}
  .seg button.on {{ background:var(--accent); color:#fff; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .catchip {{ font:inherit; font-size:12px; display:inline-flex; align-items:center; padding:2px 9px; border:1px solid var(--line); border-radius:999px; background:#fff; cursor:pointer; }}
  .catchip[aria-pressed="false"] {{ color:var(--muted); border-style:dashed; background:transparent; }}
  .catchip[aria-pressed="false"] .dot {{ background:transparent !important; box-shadow:inset 0 0 0 1.5px var(--none); }}
  .catchip[aria-pressed="false"] .cn {{ text-decoration:line-through; }}
  .legend {{ display:flex; gap:10px; font-size:12px; color:var(--muted); }}
  .legend[hidden] {{ display:none; }}
  @media print {{ .maptools .seg, .chips {{ display:none; }} }}
  .vbtn {{ font:inherit; font-weight:600; color:var(--accent); background:none; border:0; padding:0; cursor:pointer; text-align:left; text-decoration:underline; text-underline-offset:2px; }}
  tr.hl td, details.ship.hl > summary {{ background:#eaf3f9; }}
  table.small {{ min-width:640px; font-size:13px; }}
  tr.sb td {{ padding:4px 6px; }}
  ul.alerts {{ margin:0; padding-left:18px; }} ul.alerts li {{ margin:3px 0; }}
  .tl svg {{ display:block; max-width:1100px; }}
  @media print {{ .vbtn {{ text-decoration:none; color:inherit; }} body {{ background:#fff; }} section, .kpi {{ break-inside:avoid; }} #map {{ height:300px !important; }} .cols, .cols2 {{ display:block; }} .colL {{ position:static; }} }}
</style></head>
<body><main>
  <h1>{e(title)}</h1>
  <div class="meta">Period {e(period)} · Generated {e(fmt_sgt(generated))} SGT{(' · ' + status_note) if status_note else ''}</div>
  <div class="kpis">{kpi_html}</div>
  {follow}
  <div class="cols">
  <div class="colL">
  <section class="mapsec"><h2>{e(map_title)}</h2>
  <div class="maptools">
    <div class="seg" role="group" aria-label="Colour ships by"><button type="button" data-c="cat" class="on">Category</button><button type="button" data-c="state">Last seen</button></div>
    <div class="chips" id="chips" aria-label="Show or hide categories on the map">{"".join(
        f'<button type="button" class="catchip" data-hc="{e(c)}" aria-pressed="true" title="Hide {e(c)} on the map"><span class="dot" style="background:{colours.get(c, "#8a96a0")}"></span><span class="cn">{e(c)}</span></button>'
        for c in sorted({m["cat"] for m in map_data}, key=lambda c: category_rank(c, open_cat)))}</div>
    <div class="legend" id="legend" hidden><span><span class="dot fresh"></span>Last 3 days</span><span><span class="dot stale"></span>3–7 days</span><span><span class="dot old"></span>Over 7 days</span></div>
  </div>
  <div id="map"></div></section>
  </div>
  <div class="colR">
  {'' if not groups_html else f"""<section><h2>Ship details</h2>
  <p class="sub" style="margin-top:-6px">Open a category, then a ship for its details. "Map" shows the ship on the map.</p>
  {groups_html}</section>"""}
  {side_sections}
  </div>
  </div>
  {timeline}
  <div class="cols2">{"".join(lower_sections)}</div>
  <p class="foot">Positions come from shore-based AIS receivers (AISStream), logged on a schedule. Ships far from coasts may show older positions until they come back into range. "Distance" is the straight-line sum between logged positions in the period, so it understates the real distance sailed. Places are the nearest ports from the World Port Index (NGA Pub. 150).</p>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
  const ships = {json.dumps(map_data)};
  const colors = {{fresh:'#1f8a4c', stale:'#c98a00', old:'#c0392b', none:'#8a96a0'}};
  const catColors = {json.dumps(colours)};
  let colourBy = 'cat';
  const hidden = new Set();
  const colOf = s => colourBy === 'cat' ? (catColors[s.cat] || '#8a96a0') : colors[s.state];
  try {{
    const map = L.map('map', {{worldCopyJump:true}}).setView([5, 105], 3);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{maxZoom:12, attribution:'Tiles © Esri — Esri, HERE, Garmin, USGS, NGA, and other contributors'}}).addTo(map);
    const pts = [], byId = {{}};
    ships.forEach(s => {{
      const line = s.track.length > 1 ? L.polyline(s.track, {{color:colOf(s), weight:2, opacity:.6}}).addTo(map) : null;
      const mk = L.circleMarker([s.lat, s.lon], {{radius:7, color:'#fff', weight:2, fillColor:colOf(s), fillOpacity:1}})
        .bindTooltip(s.id + ' · ' + s.name, {{permanent:ships.length <= 12, direction:'right', offset:[8,0]}}).addTo(map);
      byId[s.id] = {{s, mk, line}};
      pts.push([s.lat, s.lon]);
      s.track.forEach(p => pts.push(p));
    }});
    if (pts.length) map.fitBounds(pts, {{padding:[30,30], maxZoom:7}});
    const recolour = () => Object.values(byId).forEach(o => {{ o.mk.setStyle({{fillColor:colOf(o.s)}}); if (o.line) o.line.setStyle({{color:colOf(o.s)}}); }});
    document.querySelectorAll('.seg [data-c]').forEach(b => b.addEventListener('click', () => {{
      colourBy = b.dataset.c;
      document.querySelectorAll('.seg [data-c]').forEach(x => x.classList.toggle('on', x === b));
      document.getElementById('legend').hidden = colourBy !== 'state';
      recolour();
    }}));
    const showCat = (cat, on) => Object.values(byId).forEach(o => {{
      if (o.s.cat !== cat) return;
      [o.mk, o.line].forEach(l => {{ if (!l) return; if (on) l.addTo(map); else map.removeLayer(l); }});
    }});
    document.querySelectorAll('.catchip').forEach(b => b.addEventListener('click', () => {{
      const c = b.dataset.hc, on = hidden.has(c);
      on ? hidden.delete(c) : hidden.add(c);
      b.setAttribute('aria-pressed', on); b.title = (on ? 'Hide ' : 'Show ') + c + ' on the map';
      showCat(c, on);
    }}));
    let current = null;
    document.querySelectorAll('.vbtn').forEach(b => b.addEventListener('click', ev => {{
      ev.preventDefault(); ev.stopPropagation();          // the button sits in a summary: don't toggle it
      const o = byId[b.dataset.id]; if (!o) return;
      if (hidden.has(o.s.cat)) {{ const chip = [...document.querySelectorAll('.catchip')].find(x => x.dataset.hc === o.s.cat); if (chip) chip.click(); }}
      if (current) {{ current.mk.setRadius(7); if (current.line) current.line.setStyle({{weight:2, opacity:.6}}); }}
      document.querySelectorAll('details.ship.hl').forEach(t => t.classList.remove('hl'));
      b.closest('details.ship').classList.add('hl');
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
  window.addEventListener('beforeprint', () => document.querySelectorAll('details').forEach(d => {{ d.dataset.was = d.open; d.open = true; }}));
  window.addEventListener('afterprint', () => document.querySelectorAll('details').forEach(d => {{ d.open = d.dataset.was === 'true'; }}));
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
