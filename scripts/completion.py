import html

from common import REQUIRED_DAYS, completion_date, period_info

HEADER = ["Code", "Vessel", "Category", "Group", "Days on board", "Days left",
          "Completed on / expected", "Signed off", "Next sign-on"]


def gather(roster, start, end, today):
    end = min(end, today)
    done, expected, paused = [], [], []
    for v in roster:
        st = v.get("stints", [])
        p = period_info(st, today)
        d = completion_date(st)
        if d and start <= d <= end:
            done.append((d, v))
        if p["status"] == "onboard" and p["expected_end"]:
            expected.append((p["expected_end"], v, p["days"]))
        elif p["status"] == "paused" or (p["status"] == "upcoming" and p["days"] > 0):
            paused.append((v, p))
    cat = lambda v: (v.get("category") or "").strip() or "No category"
    done.sort(key=lambda x: (x[0], x[1]["id"]))
    expected.sort(key=lambda x: (x[0], x[1]["id"]))
    paused.sort(key=lambda x: (cat(x[0]), x[0]["id"]))
    return {"completed": done, "expected": expected, "paused": paused, "start": start, "end": end, "today": today}


def _cat(v):
    return (v.get("category") or "").strip() or "No category"


def section(g, range_label, colours=None, heading="Completion"):
    e = html.escape
    colours = colours or {}
    dot = lambda v: f'<span class="dot" style="background:{colours.get(_cat(v), "#8a96a0")}"></span>'
    today = g["today"]

    def bar(days):
        pct = max(0, min(100, round(100 * days / REQUIRED_DAYS)))
        return (f'<span style="display:inline-block;width:70px;height:6px;border-radius:3px;background:#e3e8ee;'
                f'vertical-align:middle;margin-right:6px"><span style="display:block;width:{pct}%;height:100%;'
                f'border-radius:3px;background:#0b4f7a"></span></span>{pct}%')

    rows_c = "".join(f'<tr><td>{dot(v)}<b>{e(v["id"])}</b></td><td>{e(v["vessel_name"])}</td><td>{e(_cat(v))}</td>'
                     f'<td>{d:%d %b %Y}</td></tr>' for d, v in g["completed"])
    rows_e = "".join(f'<tr><td>{dot(v)}<b>{e(v["id"])}</b></td><td>{e(v["vessel_name"])}</td><td>{e(_cat(v))}</td>'
                     f'<td class=num>{days}</td><td class=num>{max(0, (d - today).days)}</td><td>{d:%d %b %Y}</td>'
                     f'<td>{bar(days)}</td></tr>' for d, v, days in g["expected"])
    def paused_row(v, p):
        off = f'{p["paused_since"]:%d %b %Y}' if p.get("paused_since") else ""
        nxt = (f'{p["next_start"]:%d %b %Y} (exp. {p["expected_end"]:%d %b %Y})'
               if p.get("next_start") and p.get("expected_end") else '<span class="sub">not set</span>')
        return (f'<tr><td>{dot(v)}<b>{e(v["id"])}</b></td><td>{e(v["vessel_name"])}</td><td>{e(_cat(v))}</td>'
                f'<td class=num>{p["days"]}</td><td>{off}</td><td>{nxt}</td></tr>')
    rows_p = "".join(paused_row(v, p) for v, p in g["paused"])

    def grp(title, n, head, rows, empty, open_=True):
        body = (f'<div class="tablewrap" style="padding:0 0 8px 18px"><table class="small" style="min-width:0;white-space:nowrap"><thead><tr>{head}'
                f'</tr></thead><tbody>{rows}</tbody></table></div>') if rows else f'<p class="sub" style="margin:4px 0 10px 18px">{empty}</p>'
        return f'<details class="grp"{" open" if open_ else ""}><summary><b>{title}</b> <span class="sub">· {n}</span></summary>{body}</details>'

    n_c, n_e, n_p = len(g["completed"]), len(g["expected"]), len(g["paused"])
    return (f'<section><h2>{e(heading)}</h2>'
            f'<p><b>{n_c}</b> completed in {e(range_label)} · <b>{n_e}</b> on board '
            f'· <b>{n_p}</b> signed off (paused).</p>'
            + grp(f"Completed in {e(range_label)}", n_c, "<th>Code</th><th>Vessel</th><th>Category</th><th>Completed on</th>",
                  rows_c, "None in this period.")
            + grp("Expected completion (still on board, soonest first)", n_e,
                  "<th>Code</th><th>Vessel</th><th>Category</th><th class=num>Days on board</th><th class=num>Days left</th>"
                  "<th>Expected</th><th>Progress</th>", rows_e, "No codes on board.")
            + grp("Signed off (paused)", n_p,
                  "<th>Code</th><th>Vessel</th><th>Category</th><th class=num>Days so far</th><th>Signed off</th><th>Next sign-on</th>",
                  rows_p, "None.", open_=bool(n_p))
            + '</section>')


def sheet(g):
    rows = []
    for d, v in g["completed"]:
        rows.append([v["id"], v["vessel_name"], _cat(v), "Completed", REQUIRED_DAYS, 0, f"{d:%Y-%m-%d}", "", ""])
    for d, v, days in g["expected"]:
        rows.append([v["id"], v["vessel_name"], _cat(v), "On board", days, max(0, (d - g["today"]).days), f"{d:%Y-%m-%d}", "", ""])
    for v, p in g["paused"]:
        rows.append([v["id"], v["vessel_name"], _cat(v), "Signed off", p["days"], REQUIRED_DAYS - p["days"],
                     f"{p['expected_end']:%Y-%m-%d}" if p.get("expected_end") else "",
                     f"{p['paused_since']:%Y-%m-%d}" if p.get("paused_since") else "",
                     f"{p['next_start']:%Y-%m-%d}" if p.get("next_start") else ""])
    return ("Completion", HEADER, rows)


def summary_lines(g, range_label):
    soon = [x for x in g["expected"] if (x[0] - g["today"]).days <= 30]
    return [f"Completion: {len(g['completed'])} completed in {range_label}; "
            f"{len(g['expected'])} on board ({len(soon)} expected to complete in the next 30 days); "
            f"{len(g['paused'])} signed off (paused)."]
