import argparse
import html
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import countries as ctry
import idtools
from common import (REPORT_INDEX, REPORTS_DIR, completion_date, load_roster, now_utc,
                    read_json, read_positions, write_json)
from insights import active_in, category_colours
from weekly_report import category_rank, latest_category, load_fixes

SGT = timezone(timedelta(hours=8))
LEAFLET = ('<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" '
           'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">',
           '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" '
           'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>')
CSS = """
  :root { --ink:#14212b; --muted:#5b6b78; --line:#dde3e8; --bg:#f6f8fa; --card:#fff; --accent:#0b4f7a; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; color:var(--ink); background:var(--bg); }
  main { max-width:1680px; margin:0 auto; padding:24px 16px 48px; }
  h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:16px; margin:0 0 10px; }
  .meta, .sub { color:var(--muted); } .sub { font-size:12px; } .meta { margin-bottom:16px; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin-bottom:16px; }
  .kpi { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
  .kpi b { display:block; font-size:24px; } .kpi span { color:var(--muted); font-size:12px; }
  section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:16px; }
  .cols { display:grid; gap:16px; } @media (min-width:1100px) { .cols { grid-template-columns:minmax(0,1.3fr) minmax(0,1fr); align-items:start; } .cols > section:first-child { position:sticky; top:12px; } }
  .cmap { height:min(62vh,560px); border-radius:8px; }
  .maptools { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; margin-bottom:8px; }
  .maptools select { font:inherit; font-size:13px; padding:4px 6px; border:1px solid var(--line); border-radius:7px; background:#fff; }
  .tablewrap { overflow-x:auto; } table { width:100%; border-collapse:collapse; }
  table.small { font-size:13px; } th, td { text-align:left; padding:6px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { font-size:12px; color:var(--muted); font-weight:600; } .num { text-align:right; } .mono { font-variant-numeric:tabular-nums; white-space:nowrap; }
  .dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; }
  details.grp { border:1px solid var(--line); border-radius:8px; margin-top:10px; }
  details.grp > summary, details.ship > summary { cursor:pointer; list-style:none; display:flex; flex-wrap:wrap; gap:4px 6px; align-items:center; padding:9px 10px; }
  details > summary::-webkit-details-marker { display:none; }
  details.grp > summary::before, details.ship > summary::before { content:"▸"; color:var(--muted); font-size:12px; transition:transform .15s; }
  details[open] > summary::before { transform:rotate(90deg); }
  details.grp .ships { padding:0 8px 8px 22px; } details.ship { border-bottom:1px solid var(--line); } details.ship:last-child { border-bottom:0; }
  .foot { color:var(--muted); font-size:12px; }
  @media print { body { background:#fff; } section, .kpi { break-inside:avoid; } .cmap { height:320px; } .cols { display:block; } }
"""


def page(title, meta, kpis, body, ships=(), export_tag="countries", aci_all=None, aci_now=None):
    e = html.escape
    k = "".join(f'<div class="kpi"><b>{e(str(n))}</b><span>{e(l)}</span></div>' for n, l in kpis)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>{LEAFLET[0]}<style>{CSS}{idtools.CSS}</style></head>
<body><main><h1>{e(title)}</h1><div class="meta">{e(meta)}</div>{idtools.block(export_rows(ships), idtools.export_name(export_tag), export_sheets(ships, aci_all, aci_now))}<div class="kpis">{k}</div>{body}
<p class="foot">A country counts as visited when the ship berthed or anchored at one of its ports (detected from hourly
AIS positions). Short calls between two logged positions, or in areas without AIS
coverage, can be missed, so counts are a minimum. Ports: World Port Index (NGA Pub. 150); outlines: Natural Earth.</p>
</main>{LEAFLET[1]}
<script>window.addEventListener('beforeprint', () => document.querySelectorAll('details').forEach(d => d.open = true));</script>
</body></html>
"""


def export_rows(ships):
    out = []
    for s in ships:
        a = ctry.aci(s["calls"])
        out.append({"Code": s["id"], "Category": s["cat"], "Vessel": s["name"],
                    "Countries visited": ", ".join(ctry.country_names(s["calls"])),
                    "Port calls": len(s["calls"]),
                    "ASEAN (excl. Singapore)": ", ".join(a["ASEAN"]), "China (incl. HK, Macao)": ", ".join(a["China"]),
                    "India": "Yes" if a["India"] else ""})
    return out


def export_sheets(ships, aci_all=None, aci_now=None):
    return [("Countries visited", ctry.XLSX_HEADER, ctry.xlsx_rows(ships)),
            ("ASEAN China India", *ctry.aci_xlsx(aci_all or list(ships), aci_now))]


def gather(roster, fixes, start=None, end=None, category=None):
    ships = []
    for v in roster:
        cat = (v.get("category") or "").strip() or "No category"
        if category and cat != category:
            continue
        hist = [f for f in fixes.get(v["id"], []) if not end or f["t"] <= end]
        ships.append({"id": v["id"], "name": v["vessel_name"], "cat": cat, "v": v,
                      "calls": ctry.visits(v, hist, start, end)})
    return ships


def save(fname, html_text, entry, md_lines):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(os.path.join(REPORTS_DIR, fname), "w", encoding="utf-8") as f:
        f.write(html_text)
    index = [r for r in read_json(REPORT_INDEX, []) if r.get("file") != fname
             and (r.get("by") or not (r.get("kind") == entry.get("kind") and r.get("date") == entry.get("date")))]
    write_json(REPORT_INDEX, sorted([entry] + index, key=lambda r: r.get("date", ""), reverse=True)[:200])
    with open(os.path.join(REPORTS_DIR, "latest-countries-summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")


def write_xlsx(out_dir, name, ships, aci_all=None, aci_now=None):
    from export_csv import write_xlsx as wx
    os.makedirs(out_dir, exist_ok=True)
    summ = [[s["id"], s["name"], s["cat"], len(ctry.by_country(s["calls"])), len(s["calls"]),
             ", ".join(ctry.country_names(s["calls"]))] for s in ships]
    return wx(os.path.join(out_dir, name), [
        ("Summary", ["Code", "Vessel", "Category", "Countries", "Port calls", "Countries (in order of first visit)"], summ),
        ("Countries visited", ctry.XLSX_HEADER, ctry.xlsx_rows(ships)),
        ("ASEAN China India", *ctry.aci_xlsx(aci_all or ships, aci_now))])


def on_demand(a):
    ref = now_utc()
    roster = load_roster()
    fixes = load_fixes(read_positions())
    start = datetime.combine(date.fromisoformat(a.date_from), datetime.min.time(), SGT) if a.date_from else None
    end = (datetime.combine(date.fromisoformat(a.date_to), datetime.min.time(), SGT) + timedelta(days=1)) if a.date_to else ref
    end = min(end, ref)
    ships = gather(roster, fixes, start, end, a.category or None)
    to_date = gather(roster, fixes, None, end, a.category or None) if start else ships
    if start:
        for s in ships:
            s["active"] = active_in(s["v"], start.astimezone(SGT).date(), (end - timedelta(seconds=1)).astimezone(SGT).date())
    colours = category_colours(roster)
    open_cat = latest_category({s["cat"] for s in ships})
    allc = sorted({c["country"] for s in ships for c in s["calls"]})
    span = (f"{start:%d %b %Y} – {(end - timedelta(seconds=1)).astimezone(SGT):%d %b %Y}" if start
            else f"Whole period to {end.astimezone(SGT):%d %b %Y}")
    scope = f"Category {a.category}" if a.category else "All categories"
    tag = f"{ref.astimezone(SGT):%Y-%m-%d-%H%M}"
    body = ('<div class="cols"><section><h2>Map</h2>' + ctry.map_block(ships, colours) + '</section>'
            '<div><section><h2>By category and ship</h2><p class="sub" style="margin:-4px 0 6px">Open a category or ship to show it on the map.</p>' + ctry.ship_table(ships, colours, category_rank, open_cat, map_id="cmap") + '</section>'
            '<section><h2>Most visited</h2>' + (ctry.ranking_html(ships) or '<p class="sub">No port calls.</p>') + '</section></div></div>'
            '<section><h2>ASEAN, China, India</h2>' + ctry.aci_block(
                to_date, colours, category_rank, open_cat, ships_now=ships if start else None,
                now_label="Selected period", all_label=f"To date ({(end - timedelta(seconds=1)).astimezone(SGT):%d %b %Y})") + '</section>')
    title = "Countries Visited"
    fname = f"countries-{tag}.html"
    entry = {"kind": "countries", "date": tag, "file": fname, "period": f"{scope} · {span}",
             "tracked": len(ships), "countries": len(allc), "generated": ref.strftime("%Y-%m-%dT%H:%M:%SZ")}
    md = [f"Countries visited report: {scope}, {span}.", "",
          f"- Countries visited (port calls): {len(allc)}",
          f"- Ships with port calls: {sum(1 for s in ships if s['calls'])} of {len(ships)}",
          f"- Port calls: {sum(len(s['calls']) for s in ships)}", ""]
    md += [f"- {c}: {n} ship{'s' if n != 1 else ''}, {k} call{'s' if k != 1 else ''}" for c, n, k in ctry.ranking(ships)]
    c_all = ctry.aci_counts(to_date)
    md += ["", f"ASEAN (excl. Singapore) / China / India — IDs that called there{' (selected period; to date)' if start else ' (to date)'}:"]
    if start:
        now_set = [s for s in ships if s.get("active", True)]
        c_now = ctry.aci_counts(now_set)
        md += [f"- {ctry.ACI_LABEL[k]}: {c_now[k]} of {len(now_set)}; {c_all[k]} of {len(to_date)}" for k in ctry.ACI_KEYS]
    else:
        md += [f"- {ctry.ACI_LABEL[k]}: {c_all[k]} of {len(to_date)}" for k in ctry.ACI_KEYS]
    md += ["", "The full report (map, per ship) is attached."]
    save(fname, page(title, f"{scope} · {span} · Generated {ref.astimezone(SGT):%d %b %Y %H:%M} SGT",
                     [(len(allc), "Countries visited"), (sum(len(s['calls']) for s in ships), "Port calls"),
                      (sum(1 for s in ships if s['calls']), "Ships with port calls"), (len(ships), "Ships")], body,
                     ships, f"countries-{tag}", to_date, ships if start else None), entry, md)
    if a.xlsx:
        entry["xlsx"] = write_xlsx(a.xlsx, f"countries_{tag}.xlsx", ships, to_date, ships if start else None)
    return entry


def period_end(a):
    ref = now_utc()
    roster = load_roster()
    v = next((x for x in roster if x["id"] == a.period_end), None)
    if not v:
        sys.exit(f"Unknown ID {a.period_end}")
    done = completion_date(v.get("stints", []))
    first = min((s["start"] for s in v.get("stints", []) if s["start"]), default=None)
    if not done or not first:
        sys.exit(f"{v['id']} has not completed yet.")
    if not a.force and any(r.get("kind") == "period_end" and r.get("date", "").startswith(v["id"] + "_")
                           for r in read_json(REPORT_INDEX, [])):
        print(json.dumps({"skip": True}))
        sys.exit(10)
    start = datetime.combine(first, datetime.min.time(), SGT)
    end = datetime.combine(done, datetime.min.time(), SGT) + timedelta(days=1)
    fixes = load_fixes(read_positions())
    ships = gather([v], fixes, start, min(end, ref))
    s = ships[0]
    colours = category_colours(roster)
    bc = ctry.by_country(s["calls"])
    vessels = []
    for st in v.get("stints", []):
        if st["start"]:
            vessels.append(f'{html.escape(st["vessel_name"])} ({st["start"]:%d %b %Y} – '
                           f'{st["end"]:%d %b %Y}' if st["end"] else f'{html.escape(st["vessel_name"])} ({st["start"]:%d %b %Y} –')
            vessels[-1] += ")" if st["end"] else " on board)"
    calls_rows = "".join(
        f'<tr><td class=mono>{c["start"].astimezone(SGT):%d %b %Y}</td><td>{html.escape(c["place"])}</td>'
        f'<td>{html.escape(c["kind"])}</td><td class=num>{html.escape(ctry.fmt_dur(ctry.stay_hours(c)))}</td></tr>' for c in s["calls"])
    body = ('<div class="cols"><section><h2>Map</h2>' + ctry.map_block(ships, colours) + '</section><div>'
            f'<section><h2>Period</h2><p><b>{html.escape(v["id"])}</b> · {html.escape(v.get("category", ""))}<br>'
            f'Vessel{"s" if len(vessels) > 1 else ""}: {"; ".join(vessels)}<br>'
            f'Started {first:%d %b %Y} · completed {done:%d %b %Y}<br>'
            f'{html.escape(ctry.aci_line(s["calls"]))}</p></section>'
            '<section><h2>Countries</h2>' + ctry.ship_table(ships, colours, category_rank) + '</section>'
            '<section><h2>All port calls</h2><div class="tablewrap"><table class="small"><thead><tr><th>Arrived</th><th>Port</th>'
            f'<th>Type</th><th class=num>Time in port</th></tr></thead><tbody>{calls_rows or "<tr><td colspan=4 class=sub>No port calls recorded</td></tr>"}'
            '</tbody></table></div></section></div></div>')
    fname = f"period-end-{v['id']}-{done:%Y-%m-%d}.html"
    entry = {"kind": "period_end", "date": f"{v['id']}_{done:%Y-%m-%d}", "file": fname,
             "period": f"{v['id']} {v['vessel_name']} · {first:%d %b %Y} – {done:%d %b %Y}",
             "tracked": 1, "countries": len(bc), "generated": ref.strftime("%Y-%m-%dT%H:%M:%SZ")}
    md = [f"End-of-period summary: {v['id']} {v['vessel_name']} ({v.get('category', '')}).", "",
          f"- Started {first:%d %b %Y}; completed {done:%d %b %Y}",
          f"- Countries visited (port calls): {len(bc)}" + (f" — {', '.join(bc)}" if bc else ""),
          f"- Port calls: {len(s['calls'])}",
          f"- {ctry.aci_line(s['calls'])} (Singapore not counted as ASEAN; China includes Hong Kong and Macao; Taiwan not counted)", "",
          "The full summary (map, countries, port calls) is attached."]
    save(fname, page(f"End of Period · {v['id']}", f"{v['vessel_name']} · {first:%d %b %Y} – {done:%d %b %Y}",
                     [(len(bc), "Countries visited"), (len(s["calls"]), "Port calls"),
                      (sum(len(x["ports"]) for x in bc.values()), "Ports")], body,
                     ships, f"period-end-{v['id']}-{done:%Y-%m-%d}"), entry, md)
    if a.xlsx:
        entry["xlsx"] = write_xlsx(a.xlsx, f"period_end_{v['id']}_{done:%Y-%m-%d}.xlsx", ships)
    return entry


def due():
    today = now_utc().astimezone(SGT).date()
    made = {r.get("date", "").split("_")[0] for r in read_json(REPORT_INDEX, []) if r.get("kind") == "period_end"}
    out = []
    for v in load_roster():
        d = completion_date(v.get("stints", []))
        if d and d <= today and (today - d).days <= 14 and v["id"] not in made:
            out.append(v["id"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", default="")
    ap.add_argument("--to", dest="date_to", default="")
    ap.add_argument("--category", default="")
    ap.add_argument("--period-end", dest="period_end", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--due", action="store_true")
    ap.add_argument("--xlsx", default="")
    a = ap.parse_args()
    if a.due:
        print(" ".join(due()))
        return 0
    entry = period_end(a) if a.period_end else on_demand(a)
    print(json.dumps(entry, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
