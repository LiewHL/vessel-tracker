import html
import json
import os
from datetime import datetime, time, timedelta, timezone

from common import NEAR_NM, ROOT, nearest_port, read_json
from insights import _stopped, port_calls

SGT = timezone(timedelta(hours=8))
GEO_FILE = os.path.join(ROOT, "assets", "countries.geojson")
VISIT_KINDS = ("Berthed", "At anchor")
ALIAS = {"Congo": "Republic of the Congo"}
SHIP_COLS = ["#2a78d6", "#eb6834", "#1baf7a", "#9b51e0", "#e8b100", "#e34c8c",
             "#00a5b5", "#7a5c2e", "#5b6cff", "#d1452f", "#3f9e3f", "#8a8f98"]


def _on_board(v, t):
    d = t.astimezone(SGT).date()
    stints = [s for s in v.get("stints", []) if s["start"]]
    if not stints:
        return True
    return any(s["start"] <= d and (s["end"] is None or d <= s["end"]) for s in stints)


SG = "Singapore"
SG_POS = (1.26, 103.84)
SG_NAMES = {"singapore", "sg", "sin", "sgsin", "spore", "s'pore"}


def _sgt_day(t):
    return t.astimezone(SGT).date()


def _sg_named(text):
    t = (text or "").strip().lower()
    return None if not t else (t in SG_NAMES or t.startswith("singapore"))


def _sg_fix(fixes, d):
    """A stopped position at or off Singapore on SGT date d, if any."""
    for f in fixes:
        if _sgt_day(f["t"]) != d or not _stopped(f):
            continue
        np_ = nearest_port(f["lat"], f["lon"])
        if np_ and np_[1] == SG and np_[2] <= NEAR_NM:
            return f
    return None


def edge_visits(v, fixes, real, start=None, end=None):
    """Start or end of a period in Singapore: from the start_port / end_port column, else from the ship's position that day."""
    out, today = [], datetime.now(SGT).date()
    sg_days = {_sgt_day(c["start"]) for c in real if c["country"] == SG} | {_sgt_day(c["end"]) for c in real if c["country"] == SG}
    for st in v.get("stints", []):
        for d, col, kind in ((st.get("start"), st.get("start_port"), "Start of period"),
                             (st.get("end"), st.get("end_port"), "End of period")):
            if not d or d > today or d in sg_days:
                continue
            named = _sg_named(col)
            if named is False:
                continue
            f = _sg_fix(fixes, d) if named is None else None
            if named is None and not f:
                continue
            t = f["t"] if f else datetime.combine(d, time(12), SGT)
            if (start and t < start) or (end and t > end):
                continue
            lat, lon = (f["lat"], f["lon"]) if f else SG_POS
            out.append({"kind": kind, "place": SG, "country": SG, "start": t, "end": t, "departed": None,
                        "hours": 0.0, "fixes": 0, "lat": lat, "lon": lon})
            sg_days.add(d)
    return out


def visits(v, fixes, start=None, end=None):
    out = []
    for c in port_calls(fixes):
        if c["kind"] not in VISIT_KINDS or not c["country"]:
            continue
        if (start and c["end"] < start) or (end and c["start"] > end):
            continue
        if not _on_board(v, c["start"]):
            continue
        out.append(c)
    return sorted(out + edge_visits(v, fixes, out, start, end), key=lambda c: c["start"])


def stay_hours(c):
    stop = c["departed"] or c["end"]
    return max(0.0, (stop - c["start"]).total_seconds() / 3600)


def by_country(calls):
    out = {}
    for c in calls:
        e = out.setdefault(c["country"], {"first": c["start"], "last": c["start"], "ports": [], "calls": 0, "hours": 0.0})
        port = (c["place"] or "").split(",")[0].strip()
        if port and port not in e["ports"]:
            e["ports"].append(port)
        e["calls"] += 1
        e["hours"] += stay_hours(c)
        e["last"] = max(e["last"], c["start"])
    return out


def country_names(calls):
    return list(by_country(calls).keys())


def ports_in_order(calls):
    seen, out = set(), []
    for c in calls:
        p = c["place"] or ""
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def fmt_dur(h):
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.1f} days"


def _geo(ports_by_country):
    feats = read_json(GEO_FILE, {}).get("features", [])
    want = {ALIAS.get(n, n): pts for n, pts in ports_by_country.items()}
    out = []
    for f in feats:
        pts = want.get(f["properties"]["name"])
        if pts is None:
            continue
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]

        def near(poly, pad=3.0):
            xs = [x for x, _ in poly[0]]
            ys = [y for _, y in poly[0]]
            return any(min(xs) - pad <= lon <= max(xs) + pad and min(ys) - pad <= lat <= max(ys) + pad
                       for lat, lon in pts)
        keep = [pl for pl in polys if near(pl)] or polys
        out.append({"type": "Feature", "properties": f["properties"],
                    "geometry": {"type": "MultiPolygon", "coordinates": keep}})
    return out


def map_block(ships, colours, mid="cmap", title="Map"):
    e = html.escape
    data, names = [], {}
    for i, s in enumerate(ships):
        bc = by_country(s["calls"])
        if not bc:
            continue
        for c in s["calls"]:
            if c.get("lat") is not None and c.get("lon") is not None:
                names.setdefault(c["country"], []).append((c["lat"], c["lon"]))
            else:
                names.setdefault(c["country"], [])
        data.append({"id": s["id"], "name": s["name"], "cat": s["cat"], "col": SHIP_COLS[i % len(SHIP_COLS)],
                     "countries": [ALIAS.get(c, c) for c in bc],
                     "ports": [{"p": c["place"], "lat": c["lat"], "lon": c["lon"]} for c in s["calls"]]})
    if not data:
        return '<p class="sub">No port calls recorded yet, so there is nothing to map.</p>'
    cats = sorted({d["cat"] for d in data})
    opts = (['<option value="all">All ships (shaded by number of ships)</option>']
            + [f'<option value="c:{e(c)}">Category {e(c)}</option>' for c in cats]
            + ['<option value="" hidden id="' + mid + '-ship"></option>'])
    geo = {"type": "FeatureCollection", "features": _geo(names)}
    return f"""<div class="maptools"><select id="{mid}-view" aria-label="Show countries for">{''.join(opts)}</select>
  <span class="sub" id="{mid}-info"></span></div>
<div id="{mid}" class="cmap"></div>
<script>
window.addEventListener('DOMContentLoaded', function() {{
  const ships = {json.dumps(data)}, geo = {json.dumps(geo, separators=(',', ':'))}, catCols = {json.dumps(colours)};
  try {{
    const map = L.map('{mid}', {{worldCopyJump:true}}).setView([15, 60], 2);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}', {{maxZoom:10, attribution:'Tiles © Esri; countries: Natural Earth'}}).addTo(map);
    let layer = null, dots = [];
    const sel = document.getElementById('{mid}-view'), info = document.getElementById('{mid}-info');
    function draw() {{
      if (layer) map.removeLayer(layer); dots.forEach(d => map.removeLayer(d)); dots = [];
      const v = sel.value, pick = v === 'all' ? ships : v.startsWith('c:') ? ships.filter(s => s.cat === v.slice(2)) : ships.filter(s => s.id === v.slice(2));
      const count = {{}}; pick.forEach(s => s.countries.forEach(c => count[c] = (count[c] || 0) + 1));
      const max = Math.max(1, ...Object.values(count));
      const col = v.startsWith('s:') ? pick[0].col : v.startsWith('c:') ? (catCols[v.slice(2)] || '#2a78d6') : '#0b4f7a';
      layer = L.geoJSON(geo, {{
        filter: f => count[f.properties.name],
        style: f => ({{color:col, weight:1, fillColor:col, fillOpacity: v === 'all' ? .2 + .6 * count[f.properties.name] / max : .55}}),
        onEachFeature: (f, l) => l.bindTooltip(f.properties.name + ' · ' + count[f.properties.name] + ' ship' + (count[f.properties.name] > 1 ? 's' : ''), {{sticky:true}})
      }}).addTo(map);
      pick.forEach(s => s.ports.forEach((p, i) => dots.push(L.circleMarker([p.lat, p.lon], {{radius: v.startsWith('s:') ? 6 : 4, color:'#fff', weight:1.5, fillColor: v.startsWith('s:') ? s.col : col, fillOpacity:1}})
        .bindTooltip((v.startsWith('s:') ? (i + 1) + '. ' : s.id + ' · ') + p.p, {{direction:'top'}}).addTo(map))));
      info.textContent = Object.keys(count).length + ' countr' + (Object.keys(count).length === 1 ? 'y' : 'ies') + ' · ' + pick.length + ' ship' + (pick.length === 1 ? '' : 's');
      const pts = dots.map(d => d.getLatLng());
      if (pts.length) map.fitBounds(L.latLngBounds(pts), {{padding:[40, 40], maxZoom:v.startsWith('s:') ? 6 : 5}});
    }}
    // The ship list drives the map: open a ship -> that ship; open a category -> that category;
    // close it again -> back out. The menu only offers All / categories; a ship picked in the list
    // shows as the selected entry.
    const shipOpt = document.getElementById('{mid}-ship');
    function setView(v) {{
      if (v.startsWith('s:')) {{ const s = ships.find(x => x.id === v.slice(2)); shipOpt.value = v; shipOpt.textContent = s.id + ' · ' + s.name; shipOpt.hidden = false; }}
      else shipOpt.hidden = true;
      sel.value = v; draw();
    }}
    document.querySelectorAll('details[data-map="{mid}"]').forEach(d => d.addEventListener('toggle', () => {{
      if (d.open) {{
        if (d.dataset.view.startsWith('s:')) document.querySelectorAll('details[data-map="{mid}"][data-view^="s:"]').forEach(o => {{ if (o !== d) o.open = false; }});
        setView(d.dataset.view);
      }} else if (sel.value === d.dataset.view) {{
        const parent = d.parentElement.closest('details[data-map="{mid}"]');
        setView(parent && parent.open ? parent.dataset.view : 'all');
      }}
    }}));
    sel.addEventListener('change', () => setView(sel.value)); draw();
  }} catch (err) {{ document.getElementById('{mid}').textContent = 'Map could not load.'; }}
}});
</script>"""


def ship_table(ships, colours, rank, open_cat="", map_id=""):
    e = html.escape
    cats = {}
    for s in ships:
        if s["calls"]:
            cats.setdefault(s["cat"], []).append(s)
    if not cats:
        return '<p class="sub">No port calls recorded.</p>'
    out = []
    for cat in sorted(cats, key=lambda c: rank(c, open_cat)):
        rows, allc = [], set()
        for s in cats[cat]:
            bc = by_country(s["calls"])
            allc.update(bc)
            trs = "".join(f"<tr><td><b>{e(c)}</b></td><td class=mono>{x['first'].astimezone(SGT):%d %b %Y}</td>"
                          f"<td>{e(', '.join(x['ports']))}</td><td class=num>{x['calls']}</td><td class=num>{e(fmt_dur(x['hours']))}</td></tr>"
                          for c, x in bc.items())
            link = f' data-map="{map_id}" data-view="s:{e(s["id"])}"' if map_id else ""
            rows.append(f'<details class="ship"{link}><summary><b>{e(s["id"])}</b>&nbsp;{e(s["name"])} <span class="sub">· {len(bc)} '
                        f'countr{"y" if len(bc) == 1 else "ies"} · {len(s["calls"])} port call{"s" if len(s["calls"]) != 1 else ""}</span></summary>'
                        f'<div class="tablewrap" style="margin:0 0 10px 18px"><table class="small" style="min-width:0"><thead><tr><th>Country</th><th>First visit</th>'
                        f'<th>Ports</th><th class=num>Calls</th><th class=num>Time in port (approx.)</th></tr></thead><tbody>{trs}</tbody></table></div></details>')
        glink = f' data-map="{map_id}" data-view="c:{e(cat)}"' if map_id else ""
        out.append(f'<details class="grp"{glink}><summary><span class="dot" style="background:{colours.get(cat, "#8a96a0")}"></span><b>{e(cat)}</b>'
                   f' <span class="sub">· {len(allc)} countr{"y" if len(allc) == 1 else "ies"} · {len(cats[cat])} ship{"s" if len(cats[cat]) != 1 else ""}</span></summary>'
                   f'<div class="ships">{"".join(rows)}</div></details>')
    return "".join(out)


def ranking(ships, top=10):
    agg = {}
    for s in ships:
        for c, x in by_country(s["calls"]).items():
            a = agg.setdefault(c, [0, 0])
            a[0] += 1
            a[1] += x["calls"]
    return sorted(((c, a[0], a[1]) for c, a in agg.items()), key=lambda r: (-r[1], -r[2], r[0]))[:top]


def ranking_html(ships):
    e = html.escape
    rk = ranking(ships)
    if not rk:
        return ""
    trs = "".join(f"<tr><td>{e(c)}</td><td class=num>{n}</td><td class=num>{k}</td></tr>" for c, n, k in rk)
    return ('<div class="tablewrap"><table class="small" style="min-width:0"><thead><tr><th>Most visited</th>'
            f'<th class=num>Ships</th><th class=num>Port calls</th></tr></thead><tbody>{trs}</tbody></table></div>')


def xlsx_rows(ships):
    rows = []
    for s in ships:
        for c in s["calls"]:
            rows.append([s["id"], s["name"], s["cat"], c["country"], (c["place"] or "").split(",")[0], c["kind"],
                         c["start"].astimezone(SGT).strftime("%Y-%m-%d %H:%M"),
                         c["departed"].astimezone(SGT).strftime("%Y-%m-%d %H:%M") if c["departed"] else "",
                         round(stay_hours(c), 1)])
    return rows


XLSX_HEADER = ["Code", "Vessel", "Category", "Country", "Port", "Type", "Arrived (first logged, SGT)",
               "Departed (first logged under way, SGT)", "Time in port (h, approx.)"]


ASEAN = ["Brunei", "Cambodia", "Indonesia", "Laos", "Malaysia", "Myanmar", "Philippines", "Singapore", "Thailand",
         "Timor-Leste", "Vietnam"]
CHINA = ["China", "Hong Kong", "Macao"]
ACI_KEYS = ["ASEAN", "China", "India", "Any"]
ACI_LABEL = {"ASEAN": "ASEAN (incl. Singapore)", "China": "China (incl. Hong Kong, Macao)", "India": "India",
             "Any": "Any of these"}


def aci(calls):
    names = country_names(calls)
    a = {"ASEAN": [c for c in names if c in ASEAN], "China": [c for c in names if c in CHINA], "India": "India" in names}
    a["Any"] = bool(a["ASEAN"] or a["China"] or a["India"])
    return a


def aci_counts(ships):
    hits = [aci(s["calls"]) for s in ships]
    return {k: sum(1 for h in hits if h[k]) for k in ACI_KEYS}


def aci_line(calls):
    a = aci(calls)
    return (f"ASEAN: {', '.join(a['ASEAN']) or 'no'} · China: {', '.join(a['China']) or 'no'} · "
            f"India: {'yes' if a['India'] else 'no'}")


def _pct(n, d):
    return f"<b>{n}</b> of {d}" + (f' <span class="sub">({round(100 * n / d)}%)</span>' if d else "")


def aci_block(ships_all, colours, rank, open_cat="", ships_now=None, now_label="", all_label="To date"):
    e = html.escape
    now_by = {s["id"]: s for s in (ships_now or [])}
    now_set = [s for s in (ships_now or []) if s.get("active", True)]
    c_all, n_all = aci_counts(ships_all), len(ships_all)
    c_now = aci_counts(now_set) if ships_now is not None else None
    head = (f'<th class=num>{e(now_label)}</th>' if c_now else "") + f'<th class=num>{e(all_label)}</th>'
    trs = "".join(f'<tr><td>{e(ACI_LABEL[k])}</td>'
                  + (f'<td class=num>{_pct(c_now[k], len(now_set))}</td>' if c_now else "")
                  + f'<td class=num>{_pct(c_all[k], n_all)}</td></tr>' for k in ACI_KEYS)
    out = [f'<div class="tablewrap"><table class="small" style="min-width:0;max-width:640px"><thead><tr><th>Called at</th>{head}</tr></thead>'
           f'<tbody>{trs}</tbody></table></div>']
    cats = {}
    for s in ships_all:
        cats.setdefault(s["cat"], []).append(s)
    for cat in sorted(cats, key=lambda c: rank(c, open_cat)):
        lst = cats[cat]
        cc = aci_counts(lst)
        rows = []
        for s in lst:
            a = aci(s["calls"])
            b = aci(now_by[s["id"]]["calls"]) if s["id"] in now_by else {"ASEAN": [], "China": [], "India": False}
            names_of = lambda k: ", ".join(f"<b>{e(c)}</b>" if c in b[k] else e(c) for c in a[k]) or '<span class="sub">—</span>'
            india = ("<b>Yes</b>" if b["India"] else "Yes") if a["India"] else '<span class="sub">—</span>'
            rows.append(f'<tr><td><b>{e(s["id"])}</b></td><td>{e(s["name"])}</td><td>{names_of("ASEAN")}</td><td>{names_of("China")}</td><td>{india}</td></tr>')
        out.append(f'<details class="grp"><summary><span class="dot" style="background:{colours.get(cat, "#8a96a0")}"></span><b>{e(cat)}</b>'
                   f' <span class="sub">· ASEAN {cc["ASEAN"]} · China {cc["China"]} · India {cc["India"]} · any {cc["Any"]} of {len(lst)}</span></summary>'
                   f'<div class="tablewrap" style="padding:0 8px 8px 22px"><table class="small" style="min-width:0"><thead><tr><th>ID</th><th>Vessel</th>'
                   f'<th>ASEAN countries</th><th>China / Hong Kong / Macao</th><th>India</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>')
    note = "Counts are IDs, whole period to date unless stated; standby places are not counted."
    if c_now:
        note += f" Bold = also counted in the “{e(now_label)}” column."
    out.append(f'<p class="sub" style="margin-top:8px">{note} ASEAN includes Singapore (also a start or end of period there); '
               'China includes Hong Kong and Macao; Taiwan is not counted.</p>')
    return "".join(out)


def aci_xlsx(ships_all, ships_now=None):
    now_by = {s["id"]: aci(s["calls"]) for s in (ships_now or [])}
    hdr = ["Code", "Vessel", "Category", "ASEAN countries (to date)", "China (to date)", "India (to date)", "Any ACI (to date)"]
    if ships_now is not None:
        hdr += ["ASEAN countries (period)", "China (period)", "India (period)", "Any ACI (period)"]
    rows = []
    for s in ships_all:
        a = aci(s["calls"])
        r = [s["id"], s["name"], s["cat"], ", ".join(a["ASEAN"]), ", ".join(a["China"]), "Yes" if a["India"] else "", "Yes" if a["Any"] else ""]
        if ships_now is not None:
            b = now_by.get(s["id"], {"ASEAN": [], "China": [], "India": False, "Any": False})
            r += [", ".join(b["ASEAN"]), ", ".join(b["China"]), "Yes" if b["India"] else "", "Yes" if b["Any"] else ""]
        rows.append(r)
    return hdr, rows
