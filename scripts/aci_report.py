import argparse
import html
import json
import os
import sys
from datetime import date, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acicomp
import idtools
from common import REPORT_INDEX, REPORTS_DIR, load_roster, now_utc, read_json, read_positions_all, write_json
from insights import category_colours
from weekly_report import load_fixes

SGT = timezone(timedelta(hours=8))

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="")
    ap.add_argument("--to", dest="end", default="")
    ap.add_argument("--category", default="")
    a = ap.parse_args()
    now = now_utc()
    today = now.astimezone(SGT).date()
    start = date.fromisoformat(a.start) if a.start else today.replace(day=1)
    end = date.fromisoformat(a.end) if a.end else (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if end < start:
        sys.exit("--to is before --from")
    roster = load_roster()
    if a.category:
        roster = [v for v in roster if (v.get("category") or "").strip() == a.category.strip()]
    g = acicomp.gather(roster, load_fixes(read_positions_all()), start, end, today)
    label = f"{start:%d %b %Y} – {end:%d %b %Y}"
    period = label + (f" · category {a.category}" if a.category else "")
    e = html.escape
    n, done, exp, c = acicomp.counts(g)
    rows = [{"Code": x["v"]["id"], "Vessel": x["v"]["vessel_name"], "Category": (x["v"].get("category") or "").strip()}
            for x in g["items"]]
    kpis = "".join(f'<div class="kpi"><b>{k}</b><span>{e(t)}</span></div>' for k, t in
                   [(n, "Completing in range"), (done, "Completed"), (exp, "Expected"), (c["Any"], "Visited ACI")])
    tag = f"{now.astimezone(SGT):%Y-%m-%d-%H%M}"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ACI &amp; completion</title><style>{CSS}{idtools.CSS}</style></head>
<body><main><h1>ACI &amp; completion</h1><div class="meta">{e(period)} · Generated {now.astimezone(SGT):%d %b %Y %H:%M} SGT</div>
{idtools.block(rows, idtools.export_name(f"aci-completion-{tag}"), [acicomp.sheet(g)])}
<div class="kpis">{kpis}</div>{acicomp.section(g, label, category_colours(roster))}</main></body></html>"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    fname = f"aci-{tag}.html"
    with open(os.path.join(REPORTS_DIR, fname), "w", encoding="utf-8") as f:
        f.write(page)
    entry = {"kind": "aci", "date": tag, "file": fname, "period": period, "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    index = [r for r in read_json(REPORT_INDEX, []) if r.get("file") != fname]
    write_json(REPORT_INDEX, sorted([entry] + index, key=lambda r: r.get("date", ""), reverse=True)[:200])
    md = [f"ACI & completion report: {period}.", ""] + acicomp.summary_lines(g, label) + [
        "", "The full report is attached (codes only; press Load in the report to add your own list)."]
    with open(os.path.join(REPORTS_DIR, "latest-aci-summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(json.dumps({"file": fname, "period": period, "kind": "aci", "date": tag}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
