import argparse
import html
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import completion
import idtools
from common import REPORT_INDEX, REPORTS_DIR, load_roster, now_utc, read_json, write_json
from countries_report import CSS
from insights import category_colours

SGT = timezone(timedelta(hours=8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="")
    ap.add_argument("--to", dest="end", default="")
    ap.add_argument("--category", default="")
    a = ap.parse_args()
    now = now_utc()
    today = now.astimezone(SGT).date()
    start = date.fromisoformat(a.start) if a.start else today.replace(day=1)
    end = date.fromisoformat(a.end) if a.end else today
    if end < start:
        sys.exit("--to is before --from")
    roster = load_roster()
    if a.category:
        roster = [v for v in roster if (v.get("category") or "").strip() == a.category.strip()]
    g = completion.gather(roster, start, end, today)
    label = f"{start:%d %b %Y} – {min(end, today):%d %b %Y}"
    period = label + (f" · category {a.category}" if a.category else "")
    e = html.escape
    rows = [{"Code": v["id"], "Vessel": v["vessel_name"], "Category": (v.get("category") or "").strip()} for v in roster]
    body = completion.section(g, label, category_colours(roster))
    kpis = "".join(f'<div class="kpi"><b>{n}</b><span>{e(t)}</span></div>' for n, t in
                   [(len(g["completed"]), "Completed in range"), (len(g["expected"]), "On board"),
                    (len(g["paused"]), "Paused")])
    tag = f"{now.astimezone(SGT):%Y-%m-%d-%H%M}"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Completion</title><style>{CSS}{idtools.CSS}</style></head>
<body><main><h1>Completion</h1><div class="meta">{e(period)} · Generated {now.astimezone(SGT):%d %b %Y %H:%M} SGT</div>
{idtools.block(rows, idtools.export_name(f"completion-{tag}"), [completion.sheet(g)])}
<div class="kpis">{kpis}</div>{body}</main></body></html>"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    fname = f"completion-{tag}.html"
    with open(os.path.join(REPORTS_DIR, fname), "w", encoding="utf-8") as f:
        f.write(page)
    entry = {"kind": "completion", "date": tag, "file": fname, "period": period,
             "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    index = [r for r in read_json(REPORT_INDEX, []) if r.get("file") != fname]
    write_json(REPORT_INDEX, sorted([entry] + index, key=lambda r: r.get("date", ""), reverse=True)[:200])
    md = [f"Completion report: {period}.", ""] + completion.summary_lines(g, label) + [
        "", "The full report is attached (codes only; press Load in the report to add your own list)."]
    with open(os.path.join(REPORTS_DIR, "latest-completion-summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(json.dumps({"file": fname, "period": period, "kind": "completion", "date": tag}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
